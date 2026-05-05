"""
Shared structured logging for all Manim Agent Network services.

Usage in any service:
    from shared.log import get_logger
    logger = get_logger(__name__)

Features:
- JSON-structured output (machine-readable in prod, pretty in dev)
- Automatic request_id / job_id / scene_id context via contextvars
- Timing helpers: timed_block(), log_subprocess()
- LLM call logging: log_llm_call()
- File operation logging: log_file()
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
import traceback
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Dict, List, Optional, Sequence

# ── Context variables (set per-request, inherited by all log calls) ──────────
_ctx_job_id: ContextVar[str] = ContextVar("job_id", default="")
_ctx_scene_id: ContextVar[str] = ContextVar("scene_id", default="")
_ctx_request_id: ContextVar[str] = ContextVar("request_id", default="")

def set_log_context(
    job_id: str = "",
    scene_id: str | int = "",
    request_id: str = "",
) -> None:
    if job_id:
        _ctx_job_id.set(str(job_id))
    if scene_id != "":
        _ctx_scene_id.set(str(scene_id))
    if request_id:
        _ctx_request_id.set(str(request_id))

def clear_log_context() -> None:
    _ctx_job_id.set("")
    _ctx_scene_id.set("")
    _ctx_request_id.set("")


# ── JSON formatter ────────────────────────────────────────────────────────────
_USE_JSON = os.getenv("LOG_FORMAT", "pretty").lower() == "json"

class _StructuredFormatter(logging.Formatter):
    """Emits one JSON object per log line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Inject context
        for key, var in (
            ("job_id", _ctx_job_id),
            ("scene_id", _ctx_scene_id),
            ("request_id", _ctx_request_id),
        ):
            val = var.get("")
            if val:
                payload[key] = val

        # Extra fields attached via logger.info("msg", extra={"k": v})
        for k, v in record.__dict__.items():
            if k not in (
                "name", "msg", "args", "levelname", "levelno", "pathname",
                "filename", "module", "exc_info", "exc_text", "stack_info",
                "lineno", "funcName", "created", "msecs", "relativeCreated",
                "thread", "threadName", "processName", "process", "message",
                "taskName",
            ) and not k.startswith("_"):
                payload[k] = v

        if record.exc_info:
            payload["traceback"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


class _PrettyFormatter(logging.Formatter):
    """Human-readable coloured output for local dev."""

    _COLORS = {
        "DEBUG":    "\033[36m",   # cyan
        "INFO":     "\033[32m",   # green
        "WARNING":  "\033[33m",   # yellow
        "ERROR":    "\033[31m",   # red
        "CRITICAL": "\033[35m",   # magenta
    }
    _RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self._COLORS.get(record.levelname, "")
        ctx_parts = []
        for label, var in (("job", _ctx_job_id), ("scene", _ctx_scene_id)):
            val = var.get("")
            if val:
                ctx_parts.append(f"{label}={val[:8]}")
        ctx = f" [{', '.join(ctx_parts)}]" if ctx_parts else ""

        # Extra fields
        extras = {
            k: v for k, v in record.__dict__.items()
            if k not in (
                "name", "msg", "args", "levelname", "levelno", "pathname",
                "filename", "module", "exc_info", "exc_text", "stack_info",
                "lineno", "funcName", "created", "msecs", "relativeCreated",
                "thread", "threadName", "processName", "process", "message",
                "taskName",
            ) and not k.startswith("_")
        }
        extra_str = ""
        if extras:
            extra_str = "  " + "  ".join(f"{k}={v}" for k, v in extras.items())

        base = (
            f"{color}{record.levelname:<8}{self._RESET} "
            f"{self.formatTime(record, '%H:%M:%S')} "
            f"{record.name}{ctx} — {record.getMessage()}{extra_str}"
        )
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


def _build_handler() -> logging.Handler:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_StructuredFormatter() if _USE_JSON else _PrettyFormatter())
    return handler


def get_logger(name: str) -> logging.Logger:
    """Return a configured logger. Call once per module at import time."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.addHandler(_build_handler())
    logger.setLevel(logging.DEBUG if os.getenv("LOG_LEVEL", "INFO").upper() == "DEBUG" else logging.INFO)
    logger.propagate = False
    return logger


# ── Timing context manager ────────────────────────────────────────────────────
@contextmanager
def timed_block(logger: logging.Logger, label: str, **extra: Any):
    """Log start + end with elapsed time.

    with timed_block(logger, "manim render", scene_id=3):
        subprocess.run(...)
    """
    logger.info(f"▶ {label} started", extra=extra)
    t0 = time.perf_counter()
    try:
        yield
        elapsed = time.perf_counter() - t0
        logger.info(f"✔ {label} done", extra={**extra, "elapsed_s": round(elapsed, 3)})
    except Exception as exc:
        elapsed = time.perf_counter() - t0
        logger.error(
            f"✖ {label} failed",
            extra={**extra, "elapsed_s": round(elapsed, 3), "error": str(exc)},
            exc_info=True,
        )
        raise


# ── Subprocess helper ─────────────────────────────────────────────────────────
def log_subprocess(
    logger: logging.Logger,
    cmd: List[str],
    result: subprocess.CompletedProcess,
    label: str = "",
    **extra: Any,
) -> None:
    """Log a completed subprocess result with returncode, stdout, stderr."""
    tag = label or cmd[0]
    level = logging.INFO if result.returncode == 0 else logging.ERROR
    logger.log(
        level,
        f"{tag} returncode={result.returncode}",
        extra={
            **extra,
            "cmd": " ".join(cmd),
            "returncode": result.returncode,
            "stdout_tail": (result.stdout or "")[-800:].strip() or None,
            "stderr_tail": (result.stderr or "")[-800:].strip() or None,
        },
    )


# ── LLM call helper ───────────────────────────────────────────────────────────
def log_llm_call(
    logger: logging.Logger,
    model: str,
    prompt_chars: int,
    response_chars: int,
    elapsed_s: float,
    attempt: int = 1,
    **extra: Any,
) -> None:
    """Log an LLM round-trip with token-proxy metrics."""
    logger.info(
        "LLM call complete",
        extra={
            **extra,
            "model": model,
            "prompt_chars": prompt_chars,
            "response_chars": response_chars,
            "elapsed_s": round(elapsed_s, 3),
            "attempt": attempt,
        },
    )


# ── File operation helper ─────────────────────────────────────────────────────
def log_file(
    logger: logging.Logger,
    action: str,
    path: str,
    **extra: Any,
) -> None:
    """Log a file read/write with size."""
    import pathlib
    p = pathlib.Path(path)
    size = p.stat().st_size if p.exists() else -1
    logger.info(
        f"file {action}",
        extra={**extra, "path": path, "size_bytes": size},
    )


# ── FastAPI middleware factory ────────────────────────────────────────────────
def make_request_logging_middleware(service_name: str):
    """Returns a Starlette middleware that logs every HTTP request/response."""
    import uuid as _uuid
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request

    _mw_logger = get_logger(f"{service_name}.http")

    class _LoggingMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            req_id = request.headers.get("x-request-id", str(_uuid.uuid4())[:8])
            set_log_context(request_id=req_id)
            t0 = time.perf_counter()
            _mw_logger.info(
                f"→ {request.method} {request.url.path}",
                extra={"request_id": req_id, "client": request.client.host if request.client else "?"},
            )
            try:
                response = await call_next(request)
                elapsed = time.perf_counter() - t0
                _mw_logger.info(
                    f"← {request.method} {request.url.path} {response.status_code}",
                    extra={"request_id": req_id, "status": response.status_code, "elapsed_s": round(elapsed, 3)},
                )
                return response
            except Exception as exc:
                elapsed = time.perf_counter() - t0
                _mw_logger.error(
                    f"✖ {request.method} {request.url.path} unhandled",
                    extra={"request_id": req_id, "elapsed_s": round(elapsed, 3), "error": str(exc)},
                    exc_info=True,
                )
                raise

    return _LoggingMiddleware
