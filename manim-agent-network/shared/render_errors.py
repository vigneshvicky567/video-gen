"""Structured, append-only log of render failures (Manim + HyperFrames) for
prompt/structure fine-tuning.

Every failed attempt appends ONE JSON line to {WORKSPACE_DIR}/logs/render_errors.jsonl
with a classified error category + trimmed excerpts + the offending code head.
Unlike the per-scene `error_logs` in job state (latest-only, cleared on success),
this is a durable, queryable failure dataset across all jobs and attempts.

Best-effort: any failure inside logging is swallowed — capturing a render failure
must never cause one. Aggregate with tools/render_error_stats.py.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Optional

from shared.config import settings

_LOG_REL = "logs/render_errors.jsonl"

# Ordered, first-match-wins. Each label is meant to map onto ONE fixable prompt
# rule, so a frequency table points straight at what to tighten in codegen.
_MANIM_PATTERNS = [
    ("latex", r"latex error|undefined control sequence|misplaced|dvisvgm|\.tex\b"),
    ("name_error", r"\bNameError\b"),
    ("attribute_error", r"\bAttributeError\b|has no attribute"),
    ("type_error", r"\bTypeError\b|unexpected keyword argument|positional argument"),
    ("value_error", r"\bValueError\b"),
    ("index_key_error", r"\bIndexError\b|\bKeyError\b"),
    ("import_error", r"ModuleNotFoundError|ImportError|No module named"),
    ("syntax_error", r"\bSyntaxError\b|IndentationError"),
    ("manim_api_misuse", r"\bMobject\b|\bVMobject\b|Animation|deprecated"),
    ("timeout", r"timed out|TimeoutExpired|\btimeout\b"),
]
_HF_PATTERNS = [
    ("js_reference_error", r"ReferenceError|is not defined"),
    ("js_syntax_error", r"\bSyntaxError\b|Unexpected token|Unexpected identifier"),
    ("selector_missing", r"querySelector|selector|Cannot read prop|of null|of undefined"),
    ("css_error", r"\bcss\b|stylesheet|unknown property|invalid property"),
    ("asset_load", r"Failed to load|net::ERR|ENOENT|\b404\b"),
    ("compile_error", r"Failed to compile|compilation"),
    ("timeout", r"Navigation timeout|timed out|\btimeout\b"),
]
_GENERIC_ERR = re.compile(r"\b(\w+Error)\b")


def classify_error(text: str, content_type: Optional[str]) -> str:
    """Bucket an error into a fixable category. HF and Manim use different tables."""
    t = text or ""
    patterns = _HF_PATTERNS if (content_type or "").lower() == "hyperframes" else _MANIM_PATTERNS
    for label, rx in patterns:
        if re.search(rx, t, re.IGNORECASE):
            return label
    m = _GENERIC_ERR.search(t)
    return m.group(1).lower() if m else "other"


def _excerpt(text: str, head: int = 400, tail: int = 900) -> dict:
    """Tracebacks carry the real cause at the END; HF stderr often at the start.
    Keep both ends, drop the middle, so the record stays small but diagnostic."""
    t = (text or "").strip()
    if len(t) <= head + tail:
        return {"full": t}
    return {"head": t[:head], "tail": t[-tail:]}


def log_render_failure(
    *,
    job_id: str,
    scene_id,
    content_type: Optional[str],
    attempt: Optional[int],
    error_text: str,
    code_text: Optional[str] = None,
    model: Optional[str] = None,
    source: str = "render",
) -> None:
    """Append one structured failure record. Never raises."""
    try:
        path = os.path.join(settings.WORKSPACE_DIR, _LOG_REL)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        rec = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "job_id": job_id,
            "scene_id": scene_id,
            "content_type": content_type,
            "attempt": attempt,
            "source": source,  # codegen | render | hf_render
            "model": model,
            "error_class": classify_error(error_text or "", content_type),
            "error": _excerpt(error_text or ""),
        }
        if code_text:
            rec["code_head"] = "\n".join((code_text or "").splitlines()[:40])
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass  # logging is best-effort; a sink failure must not break the pipeline
