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
import re
from pathlib import Path
from typing import Dict, List

from shared.config import settings
from shared.llm_client import get_llm_client
from shared.log import get_logger

logger = get_logger(__name__)

# Cap base64 payload: skip absurdly large files rather than blow up the request.
_MAX_IMAGE_BYTES = 6 * 1024 * 1024  # 6 MB

# Vision vet is a JUNK REJECTOR, not a fine ranker. Measured (llama-3.2-90b-vision
# on NIM): on-topic ocean photo -> 8, off-topic paint -> 1, but 5 similar water
# photos all tie at 8. So we drop anything below this and KEEP SigLIP's order
# among survivors (SigLIP does the real continuous ranking).
# ponytail: bump if junk leaks through; lower if good images get rejected.
_VISION_KEEP_MIN = 5.0


def _data_url(path: str) -> str:
    raw = Path(path).read_bytes()
    if len(raw) > _MAX_IMAGE_BYTES:
        raise ValueError(f"image too large for vision request: {len(raw)} bytes")
    b64 = base64.b64encode(raw).decode("ascii")
    mime = "image/png" if raw[:4] == bytes([0x89, 0x50, 0x4E, 0x47]) else "image/jpeg"
    return f"data:{mime};base64,{b64}"


def _parse_score(content: str):
    """Pull the first 0-10 number out of the model reply; None if none found."""
    m = re.search(r"\d+(?:\.\d+)?", content or "")
    if not m:
        return None
    return max(0.0, min(10.0, float(m.group())))


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
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": content}],
                temperature=0.0,
                max_tokens=2000,  # headroom for reasoning models; we only read the number
            )
            score = _parse_score(resp.choices[0].message.content or "")
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

    # `scored` is in input (SigLIP) order. Keep on-topic survivors in that order —
    # do NOT sort by the score: the model ties similar candidates, so sorting adds
    # false precision. The vet only rejects junk; SigLIP already ranked.
    survivors = [p for s, _, p in scored if s >= _VISION_KEEP_MIN]
    if not survivors:
        best = max(s for s, _, _ in scored)
        logger.warning(
            "Vision vet rejected all %d candidates (best=%.1f < %.1f); keeping SigLIP order",
            len(scored), best, _VISION_KEEP_MIN,
        )
        return paths[:keep]
    rejected = len(scored) - len(survivors)
    logger.info("Vision vet kept on-topic images",
                extra={"attempted": attempted, "scored": len(scored),
                       "rejected": rejected, "kept": min(keep, len(survivors))})
    return survivors[:keep]
