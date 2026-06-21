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
import json
import os
import sys
import time

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
        cur.execute("SELECT topic, brief, target_duration_s FROM jobs WHERE id=%s", (job_id,))
        row = cur.fetchone()
    if not row:
        raise SystemExit(f"job {job_id} not found in Neon")
    topic, brief, target = row
    return topic, (brief or {}), target


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
    topic, brief, target = _read_job(conn, job_id)
    _neon_update(conn, job_id, "running")

    r = httpx.post(f"{orch}/generate", json={"topic": topic, "brief": brief}, timeout=60)
    r.raise_for_status()
    internal_id = r.json()["job_id"]

    last = None
    while True:
        if time.monotonic() - started > watchdog:
            _neon_update(conn, job_id, "failed", state={"error": "runner wallclock watchdog"})
            raise SystemExit("watchdog: exceeded budget")
        try:
            js = httpx.get(f"{orch}/job/{internal_id}", timeout=30).json()
        except Exception:
            time.sleep(5)
            continue
        web = map_status(js.get("status", ""))
        if web != last:
            _neon_update(conn, job_id, web, state={"orchestrator": js.get("status")})
            last = web
        if is_terminal(web):
            final = js.get("final_output_path")
            if should_upload(web, final):
                key = r2_key(job_id)
                _upload_r2(final, key)
                _neon_update(conn, job_id, "done", video_url=key)
            break
        time.sleep(5)

    conn.close()
    print(f"job {job_id} finished: {last}")


if __name__ == "__main__":
    sys.exit(main())
