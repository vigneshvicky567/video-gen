"""Web-tier behaviour tests — auth scoping, quotas, idempotency, dispatch
failure, staleness sweep, video presigning. Runs on sqlite with mocked
auth/dispatch/analyze (no keys, no network)."""
import datetime as dt

import pytest
from sqlalchemy import update

from app import db, dispatch, storage
from app.config import settings


# --- auth boundary -----------------------------------------------------------
def test_generate_requires_auth(raw_client):
    r = raw_client.post("/generate", json={"topic": "x"})
    assert r.status_code == 401


def test_health_is_open(raw_client):
    assert raw_client.get("/health").json() == {"status": "ok"}


# --- generate / dispatch -----------------------------------------------------
def test_generate_creates_job_and_dispatches(client):
    r = client.post("/generate", json={"topic": "Pythagoras"})
    assert r.status_code == 200
    jid = r.json()["job_id"]
    row = db.get_job(jid)
    assert row["status"] == "queued"
    assert row["owner_user_id"] == "user_a"


def test_generate_dispatch_failure_marks_failed(client, monkeypatch):
    monkeypatch.setattr(dispatch, "dispatch_render", lambda job_id: (False, 422))
    r = client.post("/generate", json={"topic": "boom"})
    assert r.status_code == 502
    # the job row exists and is failed
    jobs = db.list_all_jobs()
    assert jobs and jobs[0]["status"] == "failed"


def test_generate_requires_topic(client):
    assert client.post("/generate", json={}).status_code == 422


# --- owner scoping -----------------------------------------------------------
def test_job_owner_scoping_404(client, as_user):
    as_user("user_a")
    jid = client.post("/generate", json={"topic": "mine"}).json()["job_id"]
    as_user("user_b")
    assert client.get(f"/job/{jid}").status_code == 404      # 404, not 403
    assert client.get(f"/video/{jid}").status_code == 404


def test_jobs_lists_only_owner(client, as_user):
    as_user("user_a")
    client.post("/generate", json={"topic": "a1"})
    as_user("user_b")
    client.post("/generate", json={"topic": "b1"})
    assert len(client.get("/jobs").json()) == 1              # only user_b's


# --- quotas ------------------------------------------------------------------
def test_daily_quota_enforced(client, monkeypatch):
    monkeypatch.setattr(settings, "DAILY_JOB_QUOTA_DEFAULT", 1)
    assert client.post("/generate", json={"topic": "1"}).status_code == 200
    assert client.post("/generate", json={"topic": "2"}).status_code == 429


def test_global_concurrency_cap(client, as_user, monkeypatch):
    monkeypatch.setattr(settings, "GLOBAL_CONCURRENCY_CAP", 1)
    monkeypatch.setattr(settings, "DAILY_JOB_QUOTA_DEFAULT", 100)
    as_user("user_a")
    assert client.post("/generate", json={"topic": "1"}).status_code == 200
    as_user("user_b")  # different user, but global cap is system-wide
    assert client.post("/generate", json={"topic": "2"}).status_code == 429


# --- idempotency -------------------------------------------------------------
def test_idempotency_key_dedups(client, monkeypatch):
    calls = []
    monkeypatch.setattr(dispatch, "dispatch_render",
                        lambda job_id: (calls.append(job_id), (True, 204))[1])
    h = {"Idempotency-Key": "abc-123"}
    j1 = client.post("/generate", json={"topic": "t"}, headers=h).json()["job_id"]
    j2 = client.post("/generate", json={"topic": "t"}, headers=h).json()["job_id"]
    assert j1 == j2
    assert len(calls) == 1                                   # dispatched once


# --- staleness sweep ---------------------------------------------------------
def test_staleness_sweep_fails_stuck_queued(client):
    jid = client.post("/generate", json={"topic": "stuck"}).json()["job_id"]
    # backdate created_at beyond the staleness window
    old = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - dt.timedelta(
        minutes=settings.QUEUE_STALENESS_MINUTES + 5)
    with db.get_engine().begin() as c:
        c.execute(update(db.jobs).where(db.jobs.c.id == jid).values(created_at=old))
    body = client.get(f"/job/{jid}").json()
    assert body["status"] == "failed"


# --- video presign -----------------------------------------------------------
def test_video_redirects_to_presigned(client):
    jid = client.post("/generate", json={"topic": "vid"}).json()["job_id"]
    db.update_status(jid, "done", video_url=storage.final_video_key(jid))
    r = client.get(f"/video/{jid}", follow_redirects=False)
    assert r.status_code == 302
    assert "X-Amz-Signature=" in r.headers["location"]


def test_video_not_ready_409(client):
    jid = client.post("/generate", json={"topic": "vid"}).json()["job_id"]
    assert client.get(f"/video/{jid}").status_code == 409


# --- admin -------------------------------------------------------------------
def test_admin_requires_admin_role(client, as_user):
    as_user("user_a", role="user")
    assert client.get("/admin/jobs").status_code == 403
    as_user("admin_1", role="admin")
    assert client.get("/admin/jobs").status_code == 200


def test_admin_analytics_counts(client, as_user):
    as_user("admin_1", role="admin")
    client.post("/generate", json={"topic": "x"})
    data = client.get("/admin/analytics").json()
    assert data["total"] >= 1 and "queued" in data["by_status"]


# --- presign determinism (money/security path) -------------------------------
def test_presign_is_deterministic(monkeypatch):
    monkeypatch.setattr(settings, "R2_ACCOUNT_ID", "acct")
    monkeypatch.setattr(settings, "R2_BUCKET", "bucket")
    monkeypatch.setattr(settings, "R2_ACCESS_KEY_ID", "AKID")
    monkeypatch.setattr(settings, "R2_SECRET_ACCESS_KEY", "SECRET")
    now = dt.datetime(2026, 6, 21, 12, 0, 0, tzinfo=dt.timezone.utc)
    u1 = storage.presign_get("jobs/j1/final.mp4", now=now)
    u2 = storage.presign_get("jobs/j1/final.mp4", now=now)
    assert u1 == u2
    assert u1.startswith("https://acct.r2.cloudflarestorage.com/bucket/jobs/j1/final.mp4?")
    assert "X-Amz-Signature=" in u1 and "X-Amz-Credential=AKID" in u1
