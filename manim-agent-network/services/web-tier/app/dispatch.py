"""Fire a GitHub Actions render run. Fire-and-forget: workflow_dispatch returns
204 with no run id, so correlation is purely by the job_id we pass. The runner
reads topic/brief/target from the Neon job row (keeps inputs tiny + avoids the
Actions input-size limits)."""
import httpx
from .config import settings


def dispatch_render(job_id: str, client: httpx.Client | None = None) -> tuple[bool, int]:
    if not (settings.GITHUB_TOKEN and settings.GITHUB_REPO):
        # not configured (local/dev) — treat as a no-op success so the row stays queued
        return False, 0
    url = (f"{settings.GITHUB_API}/repos/{settings.GITHUB_REPO}"
           f"/actions/workflows/{settings.GITHUB_WORKFLOW}/dispatches")
    payload = {"ref": settings.GITHUB_REF, "inputs": {"job_id": job_id}}
    headers = {
        "Authorization": f"Bearer {settings.GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    own = client is None
    c = client or httpx.Client(timeout=20)
    try:
        r = c.post(url, json=payload, headers=headers)
        return r.status_code == 204, r.status_code
    finally:
        if own:
            c.close()
