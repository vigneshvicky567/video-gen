"""Runs INSIDE the GitHub Actions render runner.

1. Reads the web-tier job row (topic/brief/target) from Neon by JOB_ID.
2. POSTs the in-runner orchestrator /generate, gets its internal job id.
3. Polls the orchestrator /job/{internal} and mirrors status to the Neon row
   (event-driven UPSERT — NOT a Neon timer; we poll localhost, write Neon only
   on change). Respects a watchdog so a 6h GH kill never leaves Neon 'running'.
4. On completion, uploads the final mp4 to R2 and sets video_url + status=done.

Pure helpers (status mapping, R2 key, upload/terminal decisions) are unit-tested
in tests/test_runner_mirror.py; the IO shell is thin.
"""
import datetime as dt
import json
import os
import sys
import time

_DEFAULT_TARGET = int(os.environ.get("WEBTIER_DEFAULT_TARGET", "120"))

# Web-tier job lifecycle: queued -> running -> done | failed | cancelled
_TERMINAL = {"done", "failed", "cancelled"}


def map_status(orch_status: str) -> str:
    """Map an orchestrator status to a web-tier status."""
    s = (orch_status or "").lower()
    if s in ("completed", "complete", "done", "succeeded"):
        return "done"
    if s in ("failed", "error"):
        return "failed"
    if s == "cancelled":
        return "cancelled"
    return "running"


def r2_key(job_id: str) -> str:
    return f"jobs/{job_id}/final.mp4"


def is_terminal(web_status: str) -> bool:
    return web_status in _TERMINAL


def should_upload(web_status: str, final_output_path: str | None) -> bool:
    return web_status == "done" and bool(final_output_path)


# --- IO shell (only runs under __main__) ------------------------------------
def _read_job(conn, job_id):
    with conn.cursor() as cur:
        cur.execute("SELECT topic, brief, target_duration_s, owner_user_id "
                    "FROM jobs WHERE id=%s", (job_id,))
        row = cur.fetchone()
    if not row:
        raise SystemExit(f"job {job_id} not found in Neon")
    topic, brief, target, owner = row
    brief = dict(brief or {})
    # the orchestrator REQUIRES target_duration_seconds — guarantee it
    brief.setdefault("target_duration_seconds", target or _DEFAULT_TARGET)
    return topic, brief, owner


def _record_minutes(conn, owner, minutes):
    """Account runner wall-clock minutes against the monthly Actions budget."""
    if not owner:
        return
    month = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m")
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO usage_minutes (owner_user_id, month, runner_minutes, jobs_count) "
            "VALUES (%s,%s,%s,1) ON CONFLICT (owner_user_id, month) DO UPDATE SET "
            "runner_minutes = usage_minutes.runner_minutes + EXCLUDED.runner_minutes, "
            "jobs_count = usage_minutes.jobs_count + 1",
            (owner, month, minutes))
    conn.commit()


def _neon_update(conn, job_id, status, video_url=None, state=None):
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE jobs SET status=%s, video_url=COALESCE(%s, video_url), "
            "state=COALESCE(%s, state), updated_at=now() WHERE id=%s",
            (status, video_url, json.dumps(state) if state is not None else None, job_id),
        )
    conn.commit()


def _upload_r2(local_path, key):
    import boto3
    s3 = boto3.client(
        "s3",
        endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )
    s3.upload_file(local_path, os.environ["R2_BUCKET"], key)


def main():
    import httpx
    import psycopg

    job_id = os.environ["JOB_ID"]
    orch = os.environ.get("ORCH_URL", "http://localhost:8010")
    watchdog = int(os.environ.get("WATCHDOG_SECONDS", "20400"))
    started = time.monotonic()

    conn = psycopg.connect(os.environ["NEON_DATABASE_URL"])
    topic, brief, owner = _read_job(conn, job_id)
    _neon_update(conn, job_id, "running")

    last = None
    try:
        # 4xx from the orchestrator (e.g. brief validation) must FAIL the Neon row,
        # never crash the runner before it can record state.
        try:
            r = httpx.post(f"{orch}/generate", json={"topic": topic, "brief": brief}, timeout=60)
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            _neon_update(conn, job_id, "failed",
                         state={"error": f"orchestrator rejected job (HTTP {e.response.status_code})"})
            last = "failed"
            return
        internal_id = r.json()["job_id"]

        while True:
            if time.monotonic() - started > watchdog:
                _neon_update(conn, job_id, "failed", state={"error": "runner wallclock watchdog"})
                last = "failed"
                break
            try:
                js = httpx.get(f"{orch}/job/{internal_id}", timeout=30).json()
            except Exception:
                time.sleep(5)
                continue
            web = map_status(js.get("status", ""))
            if web != last:
                _neon_update(conn, job_id, web, state=js)   # mirror full orchestrator state
                last = web
            if is_terminal(web):
                final = js.get("final_output_path")
                if should_upload(web, final):
                    key = r2_key(job_id)
                    _upload_r2(final, key)
                    _neon_update(conn, job_id, "done", video_url=key)
                break
            time.sleep(5)
    finally:
        # record consumed runner minutes against the monthly Actions budget
        minutes = max(1, int((time.monotonic() - started) / 60))
        try:
            _record_minutes(conn, owner, minutes)
        finally:
            conn.close()
    print(f"job {job_id} finished: {last}")


if __name__ == "__main__":
    sys.exit(main())
