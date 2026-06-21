"""Synchronous topic analysis via NVIDIA NIM. Reimplemented in the web tier (the
script-writer service only exists inside an ephemeral runner). This is the one
place the web tier holds NVIDIA_API_KEY."""
import json
import httpx
from .config import settings

_SYS = (
    "You analyze a proposed educational-video topic. Respond ONLY with compact JSON: "
    '{"feasible": bool, "reason": str, "suggested_duration_seconds": int, '
    '"audience_level": "beginner|intermediate|advanced"}.'
)


def analyze_topic(topic: str, client: httpx.Client | None = None) -> dict:
    if not settings.NVIDIA_API_KEY:
        return {"feasible": True, "reason": "analyzer not configured",
                "suggested_duration_seconds": 120, "audience_level": "intermediate"}
    own = client is None
    c = client or httpx.Client(timeout=60)
    try:
        r = c.post(
            f"{settings.NVIDIA_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {settings.NVIDIA_API_KEY}"},
            json={
                "model": settings.ANALYZE_MODEL,
                "messages": [{"role": "system", "content": _SYS},
                             {"role": "user", "content": topic[:2000]}],
                "temperature": 0.2, "max_tokens": 300,
            },
        )
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
        return _parse(content)
    finally:
        if own:
            c.close()


def _parse(content: str) -> dict:
    content = content.strip()
    if content.startswith("```"):
        # strip the ```json fence without eating leading j/s/o/n data chars
        content = content.split("```")[1].removeprefix("json").strip()
    try:
        return json.loads(content)
    except (ValueError, IndexError):
        return {"feasible": True, "reason": "unparseable analyzer output",
                "suggested_duration_seconds": 120, "audience_level": "intermediate"}
