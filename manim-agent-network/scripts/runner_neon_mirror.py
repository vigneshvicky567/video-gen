#!/usr/bin/env python3
"""CI render driver (referenced by .github/workflows/render-job.yml).

One ephemeral GitHub runner = one render job. The web tier fire-and-forgets a
workflow_dispatch carrying only JOB_ID; this script does everything else:

  1. read topic/brief from the Neon `jobs` row (web-tier schema),
  2. POST the local orchestrator /generate and poll /job/{id},
  3. mirror every status change back to the Neon row,
  4. on success: download the mp4 (+ captions) and upload to R2 under
     jobs/{JOB_ID}/final.mp4, mark the row done,
  5. record ACTUAL runner minutes into usage_minutes — this is the only writer
     of that table; the web tier's monthly budget gate sums it.

Env (set by the workflow): JOB_ID, ORCH_URL, NEON_DATABASE_URL,
R2_ACCOUNT_ID, R2_BUCKET, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY,
WATCHDOG_SECONDS (flush 'failed' before the Actions 6h kill).

Module import is dependency-free (stdlib only) so the pure mapping helpers are
unit-testable without psycopg/httpx/boto3 — heavy imports happen inside main().
Exit code 0 only when the Neon row reached a terminal state we wrote ourselves.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import os
import sys
import time

POLL_SECONDS = 15

# Orchestrator terminal statuses. "partial" = a degraded-but-delivered film
# (some scenes dropped) — the video exists, so it maps to done.
_ORCH_OK = {"completed", "complete", "partial"}
_ORCH_BAD = {"failed", "error", "cancelled"}
_NEON_TERMINAL = {"done", "failed", "cancelled"}


# ── Pure mapping helpers (unit-tested; no I/O) ───────────────────────────────

def map_status(orch_status) -> str:
    """Orchestrator pipeline status -> Neon jobs.status."""
    s = (orch_status or "").strip().lower()
    if s in _ORCH_OK:
        return "done"
    if s == "cancelled":
        return "cancelled"
    if s in _ORCH_BAD:
        return "failed"
    return "running"


def r2_key(job_id: str) -> str:
    return f"jobs/{job_id}/final.mp4"


def is_terminal(neon_status) -> bool:
    return (neon_status or "") in _NEON_TERMINAL


def should_upload(neon_status, video_path) -> bool:
    return neon_status == "done" and bool(video_path)


def log(msg: str) -> None:
    print(f"[runner {dt.datetime.now(dt.timezone.utc).strftime('%H:%M:%S')}] {msg}", flush=True)


# ── Neon ─────────────────────────────────────────────────────────────────────

def _neon():
    import psycopg
    return psycopg.connect(os.environ["NEON_DATABASE_URL"], autocommit=True)


def read_job_row(job_id: str) -> dict:
    with _neon() as conn:
        row = conn.execute(
            "SELECT id, owner_user_id, topic, brief, target_duration_s, status "
            "FROM jobs WHERE id = %s", (job_id,),
        ).fetchone()
    if row is None:
        raise SystemExit(f"Neon row not found for job {job_id}")
    keys = ("id", "owner_user_id", "topic", "brief", "target_duration_s", "status")
    return dict(zip(keys, row))


def mirror(job_id: str, status: str, state: dict | None = None,
           video_url: str | None = None) -> None:
    sets = ["status = %s", "updated_at = %s"]
    vals: list = [status, dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)]
    if state is not None:
        sets.append("state = %s")
        vals.append(json.dumps(state))
    if video_url is not None:
        sets.append("video_url = %s")
        vals.append(video_url)
    vals.append(job_id)
    with _neon() as conn:
        conn.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id = %s", vals)


def record_usage(owner: str, minutes: int) -> None:
    """Upsert ACTUAL runner minutes — the web tier's budget gate sums these."""
    month = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m")
    with _neon() as conn:
        conn.execute(
            """
            INSERT INTO usage_minutes (owner_user_id, month, runner_minutes, jobs_count)
            VALUES (%s, %s, %s, 1)
            ON CONFLICT (owner_user_id, month) DO UPDATE SET
                runner_minutes = usage_minutes.runner_minutes + EXCLUDED.runner_minutes,
                jobs_count = usage_minutes.jobs_count + 1
            """,
            (owner, month, minutes),
        )
    log(f"usage recorded: owner={owner} month={month} +{minutes}min")


# ── R2 ───────────────────────────────────────────────────────────────────────

def upload_to_r2(local_path: str, key: str, content_type: str) -> None:
    import boto3

    s3 = boto3.client(
        "s3",
        endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )
    s3.upload_file(local_path, os.environ["R2_BUCKET"], key,
                   ExtraArgs={"ContentType": content_type})
    log(f"uploaded {local_path} -> r2://{os.environ['R2_BUCKET']}/{key}")


# ── Orchestrator ─────────────────────────────────────────────────────────────

def start_render(client, orch_url: str, topic: str, brief) -> str:
    body: dict = {"topic": topic}
    if brief:
        body["brief"] = brief if isinstance(brief, dict) else json.loads(brief)
        # render_mode is a first-class brief field; surface it as the request
        # field too for older orchestrator builds that read it there.
        if isinstance(body["brief"], dict) and body["brief"].get("render_mode"):
            body["render_mode"] = body["brief"]["render_mode"]
    r = client.post(f"{orch_url}/generate", json=body, timeout=60)
    r.raise_for_status()
    orch_id = r.json()["job_id"]
    log(f"orchestrator job started: {orch_id}")
    return orch_id


def download(client, url: str, dest: str) -> bool:
    try:
        with client.stream("GET", url, timeout=600) as r:
            if r.status_code != 200:
                return False
            with open(dest, "wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)
        return True
    except Exception as e:  # noqa: BLE001 — caller decides severity
        log(f"download failed for {url}: {e}")
        return False


def main() -> int:
    import httpx

    job_id = os.environ["JOB_ID"]
    orch_url = os.environ.get("ORCH_URL", "http://localhost:8010").rstrip("/")
    watchdog_s = int(os.environ.get("WATCHDOG_SECONDS", "20400"))

    t0 = time.monotonic()
    deadline = t0 + watchdog_s
    row = read_job_row(job_id)
    owner = row["owner_user_id"]
    log(f"driving job {job_id} (owner={owner}, topic={str(row['topic'])[:80]!r})")

    def minutes_spent() -> int:
        return max(1, math.ceil((time.monotonic() - t0) / 60))

    try:
        with httpx.Client() as client:
            orch_id = start_render(client, orch_url, row["topic"], row["brief"])
            mirror(job_id, "running", state={"orch_job_id": orch_id, "stage": "starting"})

            last_status = ""
            st: dict = {}
            while True:
                if time.monotonic() > deadline:
                    mirror(job_id, "failed",
                           state={"error": f"runner watchdog fired after {watchdog_s}s",
                                  "orch_job_id": orch_id})
                    record_usage(owner, minutes_spent())
                    log("watchdog deadline hit — marked failed")
                    return 1

                try:
                    r = client.get(f"{orch_url}/job/{orch_id}", timeout=30)
                    r.raise_for_status()
                    st = r.json()
                except Exception as e:  # orchestrator briefly unreachable — keep polling
                    log(f"poll error (retrying): {e}")
                    time.sleep(POLL_SECONDS)
                    continue

                status = st.get("status", "")
                neon_status = map_status(status)
                if status != last_status:
                    last_status = status
                    log(f"orchestrator status: {status}")
                    if not is_terminal(neon_status):
                        mirror(job_id, "running", state={
                            "orch_job_id": orch_id, "stage": status,
                            "eta_seconds": st.get("eta_seconds"),
                            "dropped_scenes": st.get("dropped_scenes"),
                        })

                if neon_status == "done":
                    break
                if is_terminal(neon_status):
                    mirror(job_id, neon_status, state={
                        "orch_job_id": orch_id, "stage": status,
                        "error": st.get("overall_error") or f"pipeline {status}",
                    })
                    record_usage(owner, minutes_spent())
                    log(f"pipeline terminal: {status} -> {neon_status}")
                    return 1

                time.sleep(POLL_SECONDS)

            # Success path: pull artifacts and push to R2.
            if not download(client, f"{orch_url}/video/{orch_id}", "final.mp4"):
                mirror(job_id, "failed", state={"orch_job_id": orch_id,
                                                "error": "final video download failed"})
                record_usage(owner, minutes_spent())
                return 1
            key = r2_key(job_id)
            upload_to_r2("final.mp4", key, "video/mp4")

            # Captions are best-effort — never fail a delivered film over a VTT.
            if download(client, f"{orch_url}/captions/{orch_id}", "final.vtt"):
                try:
                    upload_to_r2("final.vtt", f"jobs/{job_id}/final.vtt", "text/vtt")
                except Exception as e:  # noqa: BLE001
                    log(f"caption upload failed (non-fatal): {e}")

            mirror(job_id, "done",
                   state={"orch_job_id": orch_id, "stage": last_status,
                          "dropped_scenes": st.get("dropped_scenes")},
                   video_url=key)
            record_usage(owner, minutes_spent())
            log(f"job {job_id} done in {minutes_spent()}min")
            return 0

    except Exception as e:  # noqa: BLE001 — always flush a terminal state to Neon
        log(f"runner crashed: {e}")
        try:
            mirror(job_id, "failed", state={"error": f"runner crash: {e}"})
            record_usage(owner, minutes_spent())
        except Exception as e2:  # noqa: BLE001
            log(f"could not flush failure to Neon: {e2}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
