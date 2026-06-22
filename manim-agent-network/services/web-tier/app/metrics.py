"""Best-effort agentless Datadog metrics via the HTTP API (api/v2/series).

No Datadog Agent required — works on Azure App Service free F1, which can't host
a sidecar. APM / distributed tracing DOES need an Agent, so it is deferred until
the web tier runs somewhere with a sidecar (e.g. the $100 Azure VM with a
dd-agent container). Telemetry never breaks the request path: emit() is a
best-effort, short-timeout inline call that swallows all errors, and is only
invoked on the infrequent /generate path (never on the polled /job path). No-op
when DD_API_KEY is unset."""
import time
import httpx
from .config import settings

_TYPE = {"count": 1, "rate": 2, "gauge": 3}


def _build_payload(metric, value, tags, mtype, now=None):
    ts = int(now if now is not None else time.time())
    return {"series": [{
        "metric": metric,
        "type": _TYPE.get(mtype, 1),
        "points": [{"timestamp": ts, "value": float(value)}],
        "tags": list(tags or []) + [f"service:{settings.DD_SERVICE}", f"env:{settings.DD_ENV}"],
    }]}


def emit(metric, value=1, tags=None, mtype="count") -> bool:
    if not settings.DD_API_KEY:
        return False
    try:
        httpx.post(
            f"https://api.{settings.DD_SITE}/api/v2/series",
            headers={"DD-API-KEY": settings.DD_API_KEY, "Content-Type": "application/json"},
            json=_build_payload(metric, value, tags, mtype),
            timeout=0.5,   # bounded so telemetry can't add latency to /generate
        )
        return True
    except Exception:
        return False   # telemetry must never break a user request
