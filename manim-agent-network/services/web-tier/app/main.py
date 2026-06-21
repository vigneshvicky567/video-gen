"""Thin always-on web tier (Azure F1). Does NO rendering: it authenticates
(Clerk), scopes/quota-gates requests, dispatches one GitHub Actions render run
per job, serves job status from Neon, and redirects video to a presigned R2 URL.
Serves the static frontend same-origin (no CORS)."""
import datetime as dt
import os
import uuid

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import analyze as analyze_mod
from . import db, dispatch, storage
from .auth import Principal, require_admin, require_user
from .config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="Manim Agent Network — Web Tier", lifespan=lifespan)


def _month() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m")


def _public_job(row: dict) -> dict:
    # never leak owner id or raw R2 key to the client
    return {k: row[k] for k in ("id", "topic", "status", "target_duration_s",
                                "created_at", "updated_at") if k in row} | {
        "has_video": bool(row.get("video_url")),
        "state": row.get("state"),
    }


# --- health ------------------------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/auth-config.json")
def auth_config():
    """Public: lets the static frontend fetch its Clerk publishable key
    (publishable keys are safe to expose). Empty key => frontend runs ungated
    (dev)."""
    return {
        "clerk_publishable_key": settings.CLERK_PUBLISHABLE_KEY,
        "clerk_frontend_api": settings.CLERK_FRONTEND_API,
    }


# --- analyze -----------------------------------------------------------------
@app.post("/analyze")
def analyze(payload: dict, _p: Principal = Depends(require_user)):
    topic = (payload or {}).get("topic", "").strip()
    if not topic:
        raise HTTPException(422, "topic required")
    return analyze_mod.analyze_topic(topic)


# --- generate ----------------------------------------------------------------
@app.post("/generate")
def generate(payload: dict, request: Request, p: Principal = Depends(require_user)):
    topic = (payload or {}).get("topic", "").strip()
    if not topic:
        raise HTTPException(422, "topic required")
    brief = (payload or {}).get("brief") or {}
    target = brief.get("target_duration_seconds")

    # idempotency: a client retry with the same key returns the same job
    idem = request.headers.get("Idempotency-Key")
    existing = db.find_by_idempotency(p.clerk_id, idem)
    if existing:
        return {"job_id": existing["id"], "message": "existing job"}

    # quotas
    user = db.get_or_create_user(p.clerk_id, p.email, p.role)
    quota = user.get("daily_job_quota") or settings.DAILY_JOB_QUOTA_DEFAULT
    if db.count_user_jobs_today(p.clerk_id) >= quota:
        raise HTTPException(429, "daily job quota reached")
    if db.count_active_jobs() >= settings.GLOBAL_CONCURRENCY_CAP:
        raise HTTPException(429, "system busy — try again shortly")

    job_id = str(uuid.uuid4())
    db.create_job(job_id, p.clerk_id, topic, brief, target, idempotency_key=idem)

    ok, code = dispatch.dispatch_render(job_id)
    if not ok and code not in (0,):  # 0 = dispatch not configured (local/dev): leave queued
        db.update_status(job_id, "failed", state={"error": f"dispatch failed (HTTP {code})"})
        raise HTTPException(502, "could not start render")
    return {"job_id": job_id, "message": "generation started"}


# --- job status (owner-scoped) ----------------------------------------------
@app.get("/jobs")
def list_jobs(p: Principal = Depends(require_user)):
    db.sweep_stale(settings.QUEUE_STALENESS_MINUTES)
    return [_public_job(r) for r in db.list_jobs(p.clerk_id)]


@app.get("/job/{job_id}")
def get_job(job_id: str, p: Principal = Depends(require_user)):
    db.sweep_stale(settings.QUEUE_STALENESS_MINUTES)
    row = db.get_job(job_id)
    if not row or row["owner_user_id"] != p.clerk_id:
        raise HTTPException(404, "not found")   # 404 (not 403) — no existence leak
    return _public_job(row)


@app.get("/video/{job_id}")
def get_video(job_id: str, p: Principal = Depends(require_user)):
    row = db.get_job(job_id)
    if not row or row["owner_user_id"] != p.clerk_id:
        raise HTTPException(404, "not found")
    if not row.get("video_url"):
        raise HTTPException(409, "video not ready")
    return RedirectResponse(storage.presign_get(row["video_url"]), status_code=302)


# --- admin (role-gated) ------------------------------------------------------
@app.get("/admin/jobs")
def admin_jobs(_p: Principal = Depends(require_admin)):
    return db.list_all_jobs()


@app.get("/admin/analytics")
def admin_analytics(_p: Principal = Depends(require_admin)):
    rows = db.list_all_jobs(limit=1000)
    by_status: dict[str, int] = {}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    return {"total": len(rows), "by_status": by_status, "month": _month()}


@app.post("/admin/users/{clerk_id}/role")
def admin_set_role(clerk_id: str, payload: dict, _p: Principal = Depends(require_admin)):
    role = (payload or {}).get("role")
    if role not in ("user", "admin"):
        raise HTTPException(422, "role must be user|admin")
    db.set_user_role(clerk_id, role)
    return {"clerk_id": clerk_id, "role": role}


# --- static frontend (same-origin; mount last so it doesn't shadow the API) --
if os.path.isdir(settings.FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=settings.FRONTEND_DIR, html=True), name="frontend")
