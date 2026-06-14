"""
Persistent job storage using SQLite.
Provides durability across orchestrator restarts.
"""
import sqlite3
import json
import threading
from pathlib import Path
from typing import Optional, Dict, Any, List
from contextlib import contextmanager
from shared.log import get_logger

logger = get_logger(__name__)


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
        if status in ("completed", "failed"):
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
                    SET status = ?, state_json = ?, updated_at = CURRENT_TIMESTAMP
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
                state = json.loads(row["state_json"])
                state["webhook_url"] = row["webhook_url"]
                return state
            return None
    
    def list_jobs(self, status: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """List jobs with optional status filter."""
        with self._get_connection() as conn:
            if status:
                cursor = conn.execute("""
                    SELECT job_id, topic, status, created_at, updated_at, completed_at
                    FROM jobs WHERE status = ?
                    ORDER BY created_at DESC LIMIT ?
                """, (status, limit))
            else:
                cursor = conn.execute("""
                    SELECT job_id, topic, status, created_at, updated_at, completed_at
                    FROM jobs
                    ORDER BY created_at DESC LIMIT ?
                """, (limit,))
            
            return [dict(row) for row in cursor.fetchall()]
    
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


# Global database instance
db = JobDatabase()
