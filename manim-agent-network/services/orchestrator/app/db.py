"""
Persistent job storage using SQLite.
Provides durability across orchestrator restarts.
"""
import sqlite3
import json
import threading
import typing
from pathlib import Path
from typing import Optional, Dict, Any, List
from contextlib import contextmanager
from shared.log import get_logger
from shared.models.agent_state import LangGraphState

logger = get_logger(__name__)


def _scene_keyed_fields() -> tuple:
    """Every Dict[int, ...] field of LangGraphState.

    JSON serialises int keys to strings, so on reload (resume after restart)
    every `scene_id in render_paths` check would fail and the graph would
    re-run finished work and never reach the assembler. Deriving the list from
    the typed state (instead of a hand-maintained tuple) means a new
    Dict[int, ...] field gets key revival automatically — the two can't drift.
    """
    fields = []
    for name, tp in typing.get_type_hints(LangGraphState).items():
        if typing.get_origin(tp) is dict and (typing.get_args(tp) or (None,))[0] is int:
            fields.append(name)
    return tuple(fields)


_SCENE_KEYED = _scene_keyed_fields()


def _revive_scene_keys(state: Dict[str, Any]) -> Dict[str, Any]:
    for k in _SCENE_KEYED:
        v = state.get(k)
        if isinstance(v, dict):
            out = {}
            for kk, vv in v.items():
                try:
                    out[int(kk)] = vv
                except (ValueError, TypeError):
                    out[kk] = vv
            state[k] = out
    return state


class JobDatabase:
    """Thread-safe SQLite database for job persistence."""
    
    def __init__(self, db_path: str = "/workspace/jobs.db"):
        self.db_path = db_path
        self._local = threading.local()
        self._init_db()
        logger.info(f"Job database initialized at {db_path}")
    
    @contextmanager
    def _get_connection(self):
        """Get thread-local database connection."""
        if not hasattr(self._local, 'conn'):
            self._local.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._local.conn.row_factory = sqlite3.Row
            # Long jobs stream many state writes while /job reads run concurrently;
            # WAL + a busy timeout avoid 'database is locked' under that load.
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA busy_timeout=5000")
        try:
            yield self._local.conn
        except Exception as e:
            self._local.conn.rollback()
            raise e
    
    def _init_db(self):
        """Initialize database schema."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    topic TEXT NOT NULL,
                    status TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP,
                    webhook_url TEXT
                )
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_status ON jobs(status)
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_created_at ON jobs(created_at DESC)
            """)

            # Per-stage historical timing. Used to compute backend ETA.
            # scene_bucket = round(scene_count / 5) * 5 — groups similar-size jobs.
            # mean_seconds is updated online: running mean (no raw data kept).
            conn.execute("""
                CREATE TABLE IF NOT EXISTS stage_stats (
                    stage TEXT NOT NULL,
                    scene_bucket INTEGER NOT NULL,
                    mean_seconds REAL NOT NULL,
                    sample_count INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY (stage, scene_bucket)
                )
            """)

            conn.commit()
    
    def create_job(self, job_id: str, topic: str, state: Dict[str, Any], webhook_url: Optional[str] = None):
        """Create a new job record."""
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO jobs (job_id, topic, status, state_json, webhook_url)
                VALUES (?, ?, ?, ?, ?)
            """, (job_id, topic, state.get("status", "starting"), json.dumps(state), webhook_url))
            conn.commit()
        logger.info(f"Job created in database: {job_id}")
    
    def update_job(self, job_id: str, state: Dict[str, Any]):
        """Update job state."""
        status = state.get("status", "unknown")
        completed_at = None
        if status in ("completed", "partial", "failed"):
            completed_at = "CURRENT_TIMESTAMP"
        
        with self._get_connection() as conn:
            if completed_at:
                conn.execute("""
                    UPDATE jobs 
                    SET status = ?, state_json = ?, updated_at = CURRENT_TIMESTAMP, 
                        completed_at = CURRENT_TIMESTAMP
                    WHERE job_id = ?
                """, (status, json.dumps(state), job_id))
            else:
                conn.execute("""
                    UPDATE jobs
                    SET status = ?, state_json = ?, updated_at = CURRENT_TIMESTAMP,
                        completed_at = NULL
                    WHERE job_id = ?
                """, (status, json.dumps(state), job_id))
            conn.commit()
    
    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve job state."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT state_json, webhook_url FROM jobs WHERE job_id = ?
            """, (job_id,))
            row = cursor.fetchone()
            if row:
                state = _revive_scene_keys(json.loads(row["state_json"]))
                state["webhook_url"] = row["webhook_url"]
                return state
            return None
    
    def list_jobs(self, status: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """List jobs with optional status filter."""
        cols = """job_id, topic, status, created_at, updated_at, completed_at,
                  COALESCE(CAST(json_extract(state_json,'$.intro_duration_seconds') AS REAL),0)
                      AS intro_duration_seconds,
                  json_extract(state_json,'$.script.title') AS script_title"""
        with self._get_connection() as conn:
            if status:
                cursor = conn.execute(
                    f"SELECT {cols} FROM jobs WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                    (status, limit))
            else:
                cursor = conn.execute(
                    f"SELECT {cols} FROM jobs ORDER BY created_at DESC LIMIT ?",
                    (limit,))
            return [dict(row) for row in cursor.fetchall()]
    
    def list_running_jobs(self, max_age_hours: int = 10) -> List[Dict[str, Any]]:
        """Full state of recent jobs left in a non-terminal status.

        Used on orchestrator startup to resume jobs whose in-memory driver task
        died with the process. Excluded: terminal states (completed/failed/partial)
        AND 'cancelled' — a user deliberately stopped those, so auto-reviving them on
        every restart is wrong and races their manual resume (grabs the live driver
        first -> the user's Resume then 409s "already running"). Stale jobs (older than
        max_age_hours) are skipped. Newest first so the caller can resume serially.
        """
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT job_id, state_json FROM jobs
                WHERE status NOT IN ('completed', 'failed', 'partial', 'cancelled')
                  AND updated_at > datetime('now', '-' || ? || ' hours')
                ORDER BY updated_at DESC
            """, (max_age_hours,))
            out = []
            for row in cursor.fetchall():
                try:
                    out.append({"job_id": row["job_id"],
                                "state": _revive_scene_keys(json.loads(row["state_json"]))})
                except (ValueError, TypeError):
                    continue
            return out

    def mark_failed(self, job_id: str, reason: str) -> None:
        """Force a job to failed with a reason (e.g. abandoned on shutdown)."""
        with self._get_connection() as conn:
            row = conn.execute("SELECT state_json FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            if not row:
                return
            try:
                state = json.loads(row["state_json"])
            except (ValueError, TypeError):
                state = {}
            state["status"] = "failed"
            state["overall_error"] = reason
            conn.execute("""
                UPDATE jobs SET status='failed', state_json=?, updated_at=CURRENT_TIMESTAMP,
                    completed_at=CURRENT_TIMESTAMP WHERE job_id=?
            """, (json.dumps(state), job_id))
            conn.commit()

    def delete_job(self, job_id: str) -> bool:
        """Hard-delete a single job row. Returns True if a row was removed."""
        with self._get_connection() as conn:
            cursor = conn.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
            conn.commit()
        return cursor.rowcount > 0

    def delete_old_jobs(self, days: int = 7):
        """Delete jobs older than specified days."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                DELETE FROM jobs 
                WHERE created_at < datetime('now', '-' || ? || ' days')
            """, (days,))
            deleted = cursor.rowcount
            conn.commit()
        logger.info(f"Deleted {deleted} jobs older than {days} days")
        return deleted
    
    def get_webhook_url(self, job_id: str) -> Optional[str]:
        """Get webhook URL for a job."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT webhook_url FROM jobs WHERE job_id = ?
            """, (job_id,))
            row = cursor.fetchone()
            return row["webhook_url"] if row else None

    def record_stage_timing(self, stage: str, elapsed_s: float, scene_count: int) -> None:
        """Update the running mean for a stage+bucket. Called at job completion."""
        bucket = round(scene_count / 5) * 5  # e.g. 7 scenes -> bucket 5, 13 -> 15
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO stage_stats (stage, scene_bucket, mean_seconds, sample_count)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(stage, scene_bucket) DO UPDATE SET
                    mean_seconds = (mean_seconds * sample_count + excluded.mean_seconds)
                                   / (sample_count + 1),
                    sample_count = sample_count + 1
            """, (stage, bucket, elapsed_s))
            conn.commit()

    def get_stage_mean(self, stage: str, scene_count: int) -> Optional[float]:
        """Return historical mean duration for a stage, nearest bucket first."""
        bucket = round(scene_count / 5) * 5
        with self._get_connection() as conn:
            # Exact bucket match first; fall back to any sample for that stage.
            row = conn.execute("""
                SELECT mean_seconds FROM stage_stats
                WHERE stage = ? AND scene_bucket = ?
            """, (stage, bucket)).fetchone()
            if row:
                return row["mean_seconds"]
            # Nearest bucket fallback
            row = conn.execute("""
                SELECT mean_seconds FROM stage_stats
                WHERE stage = ?
                ORDER BY ABS(scene_bucket - ?) LIMIT 1
            """, (stage, bucket)).fetchone()
            return row["mean_seconds"] if row else None


# Global database instance
db = JobDatabase()
