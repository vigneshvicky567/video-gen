"""Neon-backed (Postgres) job/user store, SQLAlchemy Core so the same code runs
on sqlite for tests. Writes are on-request only (no idle polling) to respect
Neon free-tier autosuspend / CU-hr budget."""
import datetime as dt
from sqlalchemy import (
    create_engine, MetaData, Table, Column, String, Integer, Boolean,
    DateTime, Text, JSON, select, insert, update, func, and_,
)
from .config import settings

metadata = MetaData()

users = Table(
    "users", metadata,
    Column("clerk_id", String, primary_key=True),
    Column("email", String, default=""),
    Column("role", String, default="user"),
    Column("daily_job_quota", Integer, nullable=True),
    Column("banned", Boolean, default=False),
    Column("created_at", DateTime),
)

jobs = Table(
    "jobs", metadata,
    Column("id", String, primary_key=True),
    Column("owner_user_id", String, index=True),
    Column("topic", Text),
    Column("brief", JSON, nullable=True),
    Column("status", String, default="queued", index=True),   # queued|running|done|failed|cancelled
    Column("state", JSON, nullable=True),
    Column("video_url", String, nullable=True),                # R2 object key
    Column("target_duration_s", Integer, nullable=True),
    Column("idempotency_key", String, nullable=True, index=True),
    Column("created_at", DateTime, index=True),
    Column("updated_at", DateTime),
)

usage_minutes = Table(
    "usage_minutes", metadata,
    Column("owner_user_id", String, primary_key=True),
    Column("month", String, primary_key=True),                 # YYYY-MM
    Column("runner_minutes", Integer, default=0),
    Column("jobs_count", Integer, default=0),
)

_ACTIVE = ("queued", "running")
_engine = None


def _now() -> dt.datetime:
    # naive UTC for consistent sqlite/postgres comparisons
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(settings.DATABASE_URL, future=True)
    return _engine


def set_engine(url: str):
    """Test hook: point at a throwaway database and create the schema."""
    global _engine
    _engine = create_engine(url, future=True)
    metadata.create_all(_engine)
    return _engine


def init_db():
    metadata.create_all(get_engine())


def _row(r):
    return dict(r._mapping) if r is not None else None


# --- users -------------------------------------------------------------------
def get_or_create_user(clerk_id: str, email: str = "", role: str = "user"):
    eng = get_engine()
    with eng.begin() as c:
        row = c.execute(select(users).where(users.c.clerk_id == clerk_id)).first()
        if row:
            return _row(row)
        c.execute(insert(users).values(
            clerk_id=clerk_id, email=email, role=role,
            daily_job_quota=None, banned=False, created_at=_now(),
        ))
        return _row(c.execute(select(users).where(users.c.clerk_id == clerk_id)).first())


def set_user_role(clerk_id: str, role: str):
    with get_engine().begin() as c:
        c.execute(update(users).where(users.c.clerk_id == clerk_id).values(role=role))


# --- jobs --------------------------------------------------------------------
def create_job(job_id, owner, topic, brief, target_duration_s, idempotency_key=None):
    now = _now()
    with get_engine().begin() as c:
        c.execute(insert(jobs).values(
            id=job_id, owner_user_id=owner, topic=topic, brief=brief,
            status="queued", state=None, video_url=None,
            target_duration_s=target_duration_s, idempotency_key=idempotency_key,
            created_at=now, updated_at=now,
        ))
    return get_job(job_id)


def get_job(job_id):
    with get_engine().connect() as c:
        return _row(c.execute(select(jobs).where(jobs.c.id == job_id)).first())


def list_jobs(owner, limit=60):
    with get_engine().connect() as c:
        rows = c.execute(
            select(jobs).where(jobs.c.owner_user_id == owner)
            .order_by(jobs.c.created_at.desc()).limit(limit)
        ).all()
    return [_row(r) for r in rows]


def list_all_jobs(limit=200):
    with get_engine().connect() as c:
        rows = c.execute(select(jobs).order_by(jobs.c.created_at.desc()).limit(limit)).all()
    return [_row(r) for r in rows]


def find_by_idempotency(owner, key):
    if not key:
        return None
    with get_engine().connect() as c:
        return _row(c.execute(select(jobs).where(and_(
            jobs.c.owner_user_id == owner, jobs.c.idempotency_key == key,
        ))).first())


def update_status(job_id, status, video_url=None, state=None):
    vals = {"status": status, "updated_at": _now()}
    if video_url is not None:
        vals["video_url"] = video_url
    if state is not None:
        vals["state"] = state
    with get_engine().begin() as c:
        c.execute(update(jobs).where(jobs.c.id == job_id).values(**vals))
    return get_job(job_id)


def count_user_jobs_today(owner) -> int:
    midnight = _now().replace(hour=0, minute=0, second=0, microsecond=0)
    with get_engine().connect() as c:
        return c.execute(select(func.count()).select_from(jobs).where(and_(
            jobs.c.owner_user_id == owner, jobs.c.created_at >= midnight,
        ))).scalar_one()


def count_active_jobs() -> int:
    with get_engine().connect() as c:
        return c.execute(select(func.count()).select_from(jobs).where(
            jobs.c.status.in_(_ACTIVE)
        )).scalar_one()


def sweep_stale(minutes: int) -> int:
    """Mark jobs stuck in 'queued' past the staleness window as failed — covers
    the case where workflow_dispatch fired but no runner ever checked in."""
    cutoff = _now() - dt.timedelta(minutes=minutes)
    with get_engine().begin() as c:
        res = c.execute(update(jobs).where(and_(
            jobs.c.status == "queued", jobs.c.created_at < cutoff,
        )).values(status="failed", state={"error": "no runner (staleness sweep)"}, updated_at=_now()))
        return res.rowcount or 0


def add_usage(owner, month, minutes, jobs_count=1):
    with get_engine().begin() as c:
        row = c.execute(select(usage_minutes).where(and_(
            usage_minutes.c.owner_user_id == owner, usage_minutes.c.month == month,
        ))).first()
        if row:
            c.execute(update(usage_minutes).where(and_(
                usage_minutes.c.owner_user_id == owner, usage_minutes.c.month == month,
            )).values(
                runner_minutes=row._mapping["runner_minutes"] + minutes,
                jobs_count=row._mapping["jobs_count"] + jobs_count,
            ))
        else:
            c.execute(insert(usage_minutes).values(
                owner_user_id=owner, month=month,
                runner_minutes=minutes, jobs_count=jobs_count,
            ))
