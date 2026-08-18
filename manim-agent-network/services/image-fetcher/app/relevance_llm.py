"""
Vision-LLM final image vet for the image-fetcher service.

Stage 2 of relevance filtering. SigLIP (stage 1) ranks the candidate pool
visually; this stage hands the top survivors to a vision-capable LLM that
actually SEES each image and keeps only the ones that genuinely fit the scene
(rejecting watermarks, memes, text-heavy slides, wrong-subject photos that
SigLIP rated highly on coarse visual similarity).

Graceful by design — mirrors siglip_scorer's pass-through philosophy: on any
error, a non-vision model, or an unparseable reply, return the input order
truncated to `keep`. The pipeline never hard-fails on this stage.

Requires a vision model in settings.IMAGE_EVAL_MODEL (e.g.
meta/llama-3.2-90b-vision-instruct on NVIDIA NIM). The shared LLM client is
OpenAI-compatible, so the standard image_url message format works unchanged.
"""

import base64
import os
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from pathlib import Path
from typing import Dict, List

from shared.config import settings
from shared.llm_client import get_llm_client
from shared.log import get_logger

logger = get_logger(__name__)

# Cap base64 payload: skip absurdly large files rather than blow up the request.
_MAX_IMAGE_BYTES = 6 * 1024 * 1024  # 6 MB

# Per-image scoring is a one-token reply; the LLM client's own timeout ceiling
# is 300s, far too long here. Bound each scoring call so one stuck request can't
# stall the whole vet. Tunable via env; default 30s.
_VISION_CALL_TIMEOUT_S = float(os.getenv("VISION_SCORE_TIMEOUT_SECONDS", "30"))

# The score is one small integer; ask for almost no output tokens. (Was 2000,
# then 200 — a scoring reply is a single digit, so ~10 covers "8", "8.", or a
# terse "Score: 8" while cutting generation latency and cost dramatically.)
_VISION_SCORE_MAX_TOKENS = 10

# Vision vet is a JUNK REJECTOR with a coarse tier, not a fine ranker.
# Measured (llama-3.2-90b-vision on NIM): on-topic ocean photo -> 8, off-topic
# paint -> 1, similar candidates tie.
#
# High tier (>= 8) = "directly shows the topic": always keep these first.
# Mid tier (6-7) = acceptable-but-not-ideal: used ONLY to backfill when the
#   high tier alone yields fewer than `keep`. This keeps the effective floor at
#   7 in the common case while still surfacing something when nothing scores 8.
# The old floor of 5 was the prompt's own definition of "loosely related", so
# off-topic-ish photos survived and could outrank relevant ones.
# SigLIP order is preserved WITHIN each tier.
_VISION_TIER_HIGH = 8.0
_VISION_TIER_MID = 6.0  # backfill floor; below this is rejected outright


def _data_url(path: str) -> str:
    raw = Path(path).read_bytes()
    if len(raw) > _MAX_IMAGE_BYTES:
        raise ValueError(f"image too large for vision request: {len(raw)} bytes")
    b64 = base64.b64encode(raw).decode("ascii")
    mime = "image/png" if raw[:4] == bytes([0x89, 0x50, 0x4E, 0x47]) else "image/jpeg"
    return f"data:{mime};base64,{b64}"


def _parse_score(content: str):
    """Pull the score out of the model reply; None if not found.

    Prefers an explicitly labeled score ("Score: 8", "Rating - 7") when present,
    since that is unambiguous. Otherwise falls back to the LAST in-range (0-10)
    number — not the first number anywhere — because a chatty reply ("Considering
    the 3 subjects... I rate it 8") used to be scored 3 by the first-number grab.
    With max_tokens now ~10 the reply is almost always a bare integer anyway."""
    text = content or ""
    labeled = re.search(r"(?:score|rating)\D{0,4}(\d+(?:\.\d+)?)", text, re.IGNORECASE)
    if labeled:
        val = float(labeled.group(1))
        if 0.0 <= val <= 10.0:
            return val
    candidates = [float(m) for m in re.findall(r"\d+(?:\.\d+)?", text)]
    in_range = [c for c in candidates if 0.0 <= c <= 10.0]
    if not in_range:
        return None
    return in_range[-1]


def _score_one(client, model: str, content: list) -> str:
    """One vision scoring completion, bounded by _VISION_CALL_TIMEOUT_S.

    The LLM client's own read timeout is 300s (code-gen sized); a scoring reply
    is a single token, so a stuck request here would otherwise stall the whole
    per-image loop. Runs the (blocking) create() in a helper thread and abandons
    it on timeout. vision_select's per-image try/except turns any raise here
    (including FutureTimeoutError) into score=None for that image."""
    with ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(
            client.chat.completions.create,
            model=model,
            messages=[{"role": "user", "content": content}],
            temperature=0.0,
            max_tokens=_VISION_SCORE_MAX_TOKENS,
        )
        resp = future.result(timeout=_VISION_CALL_TIMEOUT_S)
    return resp.choices[0].message.content or ""


def vision_select(
    paths: List[str],
    alts: Dict[str, str],
    narration: str,
    visual_desc: str,
    keep: int = 3,
) -> List[str]:
    """
    Keep the best <= `keep` images that fit the scene, judged by a vision LLM
    that sees the pixels.

    Args:
        paths: candidate image paths (already SigLIP-ranked, best first).
        alts: url/path -> alt/caption text (best-effort context for the model).
        narration: scene narration text.
        visual_desc: scene visual description.
        keep: max images to return.

    Returns:
        Subset of `paths` (preserving the model's preference order). Falls back
        to paths[:keep] on any failure.
    """
    if not paths:
        return []
    if len(paths) <= 1:
        return paths

    model = settings.IMAGE_EVAL_MODEL
    if not model:
        logger.info("IMAGE_EVAL_MODEL not set; skipping vision vet (SigLIP order kept)")
        return paths[:keep]

    # Score ONE image per request. NIM vision models cap at 1 image/request
    # (OpenAI allows many), so a single multi-image call 400s on NIM — per-image
    # scoring works on both, and independent judgments rank cleanly.
    client = get_llm_client()
    scored: List[tuple] = []   # (score, original_index, path) — index breaks ties stably
    attempted = 0
    for idx, p in enumerate(paths):
        try:
            url = _data_url(p)
        except Exception as e:
            logger.warning("Vision vet skipping unreadable image", extra={"path": p, "error": str(e)})
            continue
        caption = alts.get(p) or alts.get(str(p)) or ""
        prompt = (
            "You are choosing a background photo for one scene of an educational video.\n"
            f"Scene narration: {narration}\n"
            f"Scene visual description: {visual_desc}\n"
            + (f"Image caption: {caption}\n" if caption else "")
            + "Rate from 1 to 10 how well THIS photo's subject matches the scene's topic "
            "(1 = unrelated subject / watermark / logo / heavy text / meme, "
            "5 = loosely related, 10 = directly shows the topic). "
            "Judge subject/topic match, not whether every detail is present.\n"
            "Reply with ONLY the integer."
        )
        content = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": url}},
        ]
        try:
            attempted += 1
            reply = _score_one(client, model, content)  # bounded by per-call timeout
            score = _parse_score(reply)
        except FutureTimeoutError:
            logger.warning("Vision vet score timed out for image",
                           extra={"path": p, "timeout_s": _VISION_CALL_TIMEOUT_S})
            score = None
        except Exception as e:
            logger.warning("Vision vet score failed for image", extra={"path": p, "error": str(e)})
            score = None
        if score is not None:
            scored.append((score, idx, p))

    if not scored:
        logger.warning(
            "Vision vet produced no scores; keeping SigLIP order. "
            "Check IMAGE_EVAL_MODEL is vision-capable and reachable."
        )
        return paths[:keep]

    # `scored` is in input (SigLIP) order. Tier survivors coarsely and keep
    # SigLIP's order WITHIN each tier — never fine-sort by the score: the model
    # ties similar candidates, so a full sort adds false precision.
    # Prefer the high tier (>=8, directly shows the topic). Only backfill from
    # the mid tier (6-7) when high alone gives fewer than `keep`.
    high = [p for s, _, p in scored if s >= _VISION_TIER_HIGH]
    mid = [p for s, _, p in scored if _VISION_TIER_MID <= s < _VISION_TIER_HIGH]
    survivors = high if len(high) >= keep else high + mid
    if not survivors:
        best = max(s for s, _, _ in scored)
        # An off-topic image is WORSE than no image — the scene renders fine on
        # its palette background. (The old fallback shipped the junk anyway.)
        logger.warning(
            "Vision vet rejected all %d candidates (best=%.1f < %.1f); scene will "
            "render without stock imagery",
            len(scored), best, _VISION_TIER_MID,
        )
        return []
    rejected = len(scored) - len(survivors)
    logger.info("Vision vet kept on-topic images",
                extra={"attempted": attempted, "scored": len(scored),
                       "rejected": rejected, "high_tier": len(high),
                       "mid_tier": len(mid), "kept": min(keep, len(survivors))})
    return survivors[:keep]
