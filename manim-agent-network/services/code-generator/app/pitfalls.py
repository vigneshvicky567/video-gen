"""Self-tuning prompt hints from the fleet's real failure history.

shared/render_errors.py appends every render/codegen failure to
{WORKSPACE_DIR}/logs/render_errors.jsonl with a classified error_class, where
each class maps onto ONE fixable prompt rule. This module closes the loop:
it aggregates the recent log and injects the top recurring classes as a
"COMMON PITFALLS" block into FRESH generation prompts — so the base prompt
hardens against whatever this deployment actually keeps getting wrong, not
just what the author guessed. (Per-scene retries already carry their own
error + full attempt history; this block targets the FIRST attempt.)

Cheap by construction: reads at most the last ~1MB of the log, cached 60s.
Empty/no log -> empty block, zero cost.
"""

from __future__ import annotations

import json
import os
import time
from collections import Counter

from shared.config import settings
from shared.log import get_logger

logger = get_logger(__name__)

_LOG_REL = "logs/render_errors.jsonl"
_TAIL_BYTES = 1_000_000   # aggregate over the recent past, not all history
_CACHE_TTL_S = 60
_MIN_COUNT = 3            # a class must recur to earn prompt space
_TOP_N = 3

# error_class -> the one prompt rule that prevents it. Keep each hint short,
# imperative, and self-contained — it lands verbatim in the generation prompt.
_MANIM_HINTS = {
    "latex": "LaTeX errors recur: use MathTex with raw strings (r\"...\"), only standard commands — no custom packages, no \\text with special chars.",
    "name_error": "NameErrors recur: define every variable before use and reference only names that `from manim import *` actually provides.",
    "attribute_error": "AttributeErrors recur: use only current Manim CE methods — no removed/renamed API (check the forbidden list in the rules).",
    "type_error": "TypeErrors recur: match current Manim CE signatures exactly — no invented keyword arguments.",
    "value_error": "ValueErrors recur: keep ranges/coordinates consistent (points inside axes ranges, valid color strings).",
    "index_key_error": "Index/KeyErrors recur: never index into empty groups; build VGroups before indexing them.",
    "import_error": "ImportErrors recur: import ONLY `from manim import *` — no other modules exist in the sandbox.",
    "manim_api_misuse": "Deprecated-API failures recur: re-check the deprecated/forbidden identifier list before writing any animation call.",
    "timeout": "Render timeouts recur: fewer, cheaper animations — cap total self.play run_time within the scene budget; avoid huge point counts.",
}
_HF_HINTS = {
    "js_reference_error": "JS ReferenceErrors recur: define every const before use; register the timeline EXACTLY per the template block.",
    "js_syntax_error": "JS syntax errors recur: keep the <script> minimal — one timeline, plain GSAP calls, no clever syntax.",
    "selector_missing": "Missing-selector failures recur: every selector passed to gsap must match an element that exists in THIS document.",
    "css_error": "CSS failures recur: plain flat CSS only — no preprocessor syntax, no nested rules, standard properties.",
    "asset_load": "Asset-load failures recur: reference ONLY __IMAGE_k__ placeholders and the exact GSAP CDN URL — no other external resources.",
    "compile_error": "Compile failures recur: emit one complete, well-formed HTML document — every tag closed, no stray fragments.",
    "timeout": "Capture timeouts recur: finite deterministic timelines only — no repeat:-1, no Math.random, no waiting on external events.",
}

_cache: dict = {"at": 0.0, "sig": None, "counts": None}


def _log_path() -> str:
    return os.path.join(settings.WORKSPACE_DIR, _LOG_REL)


def _recent_counts() -> dict:
    """{content_type: Counter(error_class)} over the recent log tail. Cached."""
    now = time.monotonic()
    try:
        st = os.stat(_log_path())
        sig = (st.st_mtime_ns, st.st_size)
    except OSError:
        return {}
    if _cache["counts"] is not None and _cache["sig"] == sig \
            and now - _cache["at"] < _CACHE_TTL_S:
        return _cache["counts"]

    counts: dict = {"manim": Counter(), "hyperframes": Counter()}
    try:
        with open(_log_path(), "rb") as f:
            if st.st_size > _TAIL_BYTES:
                f.seek(-_TAIL_BYTES, os.SEEK_END)
                f.readline()  # drop the partial first line
            for raw in f:
                try:
                    rec = json.loads(raw)
                except ValueError:
                    continue
                ct = (rec.get("content_type") or "manim").lower()
                if ct not in counts:
                    ct = "manim"
                counts[ct][rec.get("error_class") or "other"] += 1
    except OSError as e:
        logger.warning("pitfalls: could not read render_errors log", extra={"error": str(e)})
        return {}

    _cache.update(at=now, sig=sig, counts=counts)
    return counts


def pitfalls_block(content_type: str) -> str:
    """Prompt block naming this deployment's top recurring failure classes.

    Empty string when there's no history or nothing recurs — the block only
    spends prompt tokens when the data has something to say."""
    try:
        counts = _recent_counts().get((content_type or "manim").lower())
        if not counts:
            return ""
        hints = _MANIM_HINTS if content_type != "hyperframes" else _HF_HINTS
        lines = []
        for cls, n in counts.most_common(_TOP_N):
            if n < _MIN_COUNT:
                break
            hint = hints.get(cls)
            if hint:
                lines.append(f"- ({n}x recently) {hint}")
        if not lines:
            return ""
        return ("\nCOMMON PITFALLS in this deployment's recent failures — "
                "actively avoid each:\n" + "\n".join(lines) + "\n")
    except Exception as e:  # noqa: BLE001 — a hint block must never break generation
        logger.warning("pitfalls block failed", extra={"error": str(e)[:160]})
        return ""
