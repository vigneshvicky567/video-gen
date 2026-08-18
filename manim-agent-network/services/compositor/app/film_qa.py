"""Post-assembly film QA: deterministic ffmpeg defect scan + vision diagnosis.

Runs on the raw assembled film BEFORE finalize_film adds the intro/music bed,
so scene start times still line up with SceneTimingRecord and narration
silence isn't masked by background music. One ffmpeg pass finds black frames
(blackdetect), static/blank stretches (freezedetect — catches the blank WHITE
page blackdetect can't see) and silent audio (silencedetect) with exact
timestamps; ranges are mapped onto scene slots, and each flagged scene gets a
3-frame vision diagnosis whose critique flows back into the orchestrator's
existing code-gen retry loop (error_history source="film_qa").

Best-effort by contract: any failure here logs and returns empty findings —
film QA must never fail an assembly that already produced a film.
"""

import asyncio
import base64
import json
import os
import re
import tempfile
from typing import Dict, List, Tuple

from shared.config import settings
from shared.log import get_logger
from shared.proc import run_proc
from shared.schemas.common import SceneTimingRecord

from .chunking import slot_seconds
from .duration_prober import probe_duration

logger = get_logger(__name__)

# Detection floors (seconds) — below these ffmpeg doesn't report a range at all.
_BLACK_MIN_S = 1.0
_FREEZE_MIN_S = 3.0
_SILENCE_MIN_S = 2.0

# How much of a scene's slot a defect must cover before the scene is flagged.
# Freeze is deliberately lax: animations legitimately hold frames (and
# freeze_pad_renders clones the last frame by design), so only a near-total
# freeze — a page that never animated — is a candidate; the vision pass then
# separates "static but legible content" from "blank".
_FREEZE_COVER = 0.80
_SILENCE_COVER = 0.80

_RE_BLACK = re.compile(r"black_start:([\d.]+)\s+black_end:([\d.]+)")
_RE_FREEZE_START = re.compile(r"freeze_start:\s*([\d.]+)")
_RE_FREEZE_END = re.compile(r"freeze_end:\s*([\d.]+)")
_RE_SILENCE_START = re.compile(r"silence_start:\s*([-\d.]+)")
_RE_SILENCE_END = re.compile(r"silence_end:\s*([-\d.]+)")

_QA_FRAME_FRACS = (0.25, 0.50, 0.75)


def _pair(starts: List[float], ends: List[float], duration: float) -> List[Tuple[float, float]]:
    """Zip start/end timestamps into ranges; a start with no matching end means
    the defect ran to the end of the film (ffmpeg only closes a range when the
    condition stops), so close it at the film duration."""
    ranges = list(zip(starts, ends))
    if len(starts) > len(ends):
        ranges.append((starts[len(ends)], duration))
    return ranges


def _has_audio_stream(path: str) -> bool:
    try:
        r = run_proc(
            ["ffprobe", "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=index", "-of", "csv=p=0", path],
            timeout=60,
        )
        return r.returncode == 0 and bool(r.stdout.strip())
    except Exception:
        return False


def _detect_ranges(video_path: str) -> dict:
    """One ffmpeg decode pass over the film. Returns exact defect ranges:
    {"black": [(s,e)], "freeze": [(s,e)], "silence": [(s,e)],
     "has_audio": bool, "duration": float}."""
    duration = probe_duration(video_path)
    has_audio = _has_audio_stream(video_path)
    cmd = [
        "ffmpeg", "-hide_banner", "-nostats", "-i", video_path,
        "-vf", (f"blackdetect=d={_BLACK_MIN_S}:pix_th=0.10,"
                f"freezedetect=n=-60dB:d={_FREEZE_MIN_S}"),
    ]
    if has_audio:
        cmd += ["-af", f"silencedetect=n=-50dB:d={_SILENCE_MIN_S}"]
    else:
        cmd += ["-an"]
    cmd += ["-f", "null", "-"]
    r = run_proc(cmd, timeout=max(300, int(120 + 2 * duration)))
    out = (r.stderr or "") + "\n" + (r.stdout or "")
    return {
        "black": [(float(s), float(e)) for s, e in _RE_BLACK.findall(out)],
        "freeze": _pair([float(x) for x in _RE_FREEZE_START.findall(out)],
                        [float(x) for x in _RE_FREEZE_END.findall(out)], duration),
        "silence": _pair([max(0.0, float(x)) for x in _RE_SILENCE_START.findall(out)],
                         [max(0.0, float(x)) for x in _RE_SILENCE_END.findall(out)], duration),
        "has_audio": has_audio,
        "duration": duration,
    }


def _coverage(ranges: List[Tuple[float, float]], start: float, end: float) -> float:
    """Seconds of [start, end] covered by the given ranges."""
    return sum(max(0.0, min(e, end) - max(s, start)) for s, e in ranges)


def _scene_findings(ranges: dict, t: SceneTimingRecord, start: float, span: float) -> List[str]:
    end = start + span
    findings = []
    black_s = _coverage(ranges["black"], start, end)
    # Any sustained black is a defect (fades are shorter than the 1s floor):
    # 3s absolute, or half the slot for very short scenes.
    if black_s >= min(3.0, 0.5 * span):
        findings.append(f"black frames for {black_s:.1f}s of the {span:.1f}s slot")
    freeze_s = _coverage(ranges["freeze"], start, end)
    if span > 0 and freeze_s >= _FREEZE_COVER * span:
        findings.append(
            f"completely static for {freeze_s:.1f}s of the {span:.1f}s slot "
            f"(no motion — likely a blank or never-animating page)")
    if ranges["has_audio"] and t.audio_path:
        silence_s = _coverage(ranges["silence"], start, end)
        if span > 0 and silence_s >= _SILENCE_COVER * span:
            findings.append(
                f"narration inaudible: silence for {silence_s:.1f}s of the {span:.1f}s slot")
    return findings


def _extract_frame_at(video_path: str, ts: float, out_path: str) -> bool:
    try:
        r = run_proc(
            ["ffmpeg", "-y", "-ss", f"{max(0.1, ts):.3f}", "-i", video_path,
             "-vframes", "1", "-q:v", "2", out_path],
            timeout=60,
        )
        return r.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 0
    except Exception:
        return False


async def _vision_diagnose(video_path: str, start: float, span: float,
                           narration: str, visual_desc: str,
                           findings: List[str]) -> Tuple[bool, str]:
    """Show the vision model 3 frames from the flagged scene's slot in the
    FINAL film and ask it to confirm + diagnose. Returns (defective, diagnosis).
    Fail-open to (True, "") — the deterministic finding stands on its own."""
    from shared.llm_client import extract_json, get_llm_client
    content: list = []
    with tempfile.TemporaryDirectory() as td:
        for i, frac in enumerate(_QA_FRAME_FRACS):
            frame = os.path.join(td, f"qa_{i}.jpg")
            ok = await asyncio.to_thread(
                _extract_frame_at, video_path, start + frac * span, frame)
            if not ok:
                continue
            b64 = base64.b64encode(open(frame, "rb").read()).decode("ascii")
            content.append({"type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
    if not content:
        return True, ""
    prompt = (
        "These are 3 frames (25%, 50%, 75%) from one scene of a rendered educational "
        "video that automated analysis flagged as possibly defective.\n"
        f"Automated findings: {'; '.join(findings)}\n"
        f"The narration says: \"{(narration or '')[:600]}\"\n"
        f"The intended visual: \"{(visual_desc or '')[:400]}\"\n\n"
        "Is this scene actually defective? A scene is defective if the frames are "
        "blank, black, corrupt, or clearly fail to show the intended visual. A scene "
        "that is static but shows legible, relevant content is NOT defective.\n"
        'Reply with ONLY JSON: {"defective": true|false, "diagnosis": "one sentence '
        'naming the most likely cause", "fix_hint": "one concrete instruction for '
        'the code generator"}'
    )
    content.append({"type": "text", "text": prompt})
    resp = await get_llm_client().chat.completions.acreate(
        model=settings.IMAGE_EVAL_MODEL,
        messages=[{"role": "user", "content": content}],
        max_tokens=300,
        temperature=0.0,
    )
    data = json.loads(extract_json(resp.choices[0].message.content or ""))
    defective = bool(data.get("defective", True))
    diagnosis = str(data.get("diagnosis") or "").strip()
    fix = str(data.get("fix_hint") or "").strip()
    return defective, (diagnosis + (f" FIX: {fix}" if fix else "")).strip()


async def run_film_qa(video_path: str, scene_timings: List[SceneTimingRecord],
                      scene_plans: list) -> Tuple[Dict[int, str], List[str]]:
    """Scan the assembled film and return (qa_flagged, qa_film_issues):
    qa_flagged maps scene_id -> retry critique; qa_film_issues are film-level
    problems (e.g. missing audio stream) that regenerating a scene cannot fix.
    scene_timings must be the scenes actually IN the film, with
    start_time_seconds matching the film's timeline."""

    def _plan_field(plan, key, default=None):
        return plan.get(key, default) if isinstance(plan, dict) else getattr(plan, key, default)

    try:
        ranges = await asyncio.to_thread(_detect_ranges, video_path)
    except Exception as e:  # noqa: BLE001 — QA is best-effort
        logger.warning("film QA: defect scan failed; skipping", extra={"error": str(e)[:300]})
        return {}, []
    logger.info("film QA defect scan", extra={
        "black": ranges["black"], "freeze": ranges["freeze"],
        "silence": ranges["silence"], "has_audio": ranges["has_audio"],
    })

    film_issues: List[str] = []
    if not ranges["has_audio"] and any(t.audio_path for t in scene_timings):
        film_issues.append(
            "final film has NO audio stream although narrated scenes exist — "
            "assembly-level audio loss, not a per-scene defect")

    plans = {
        int(_plan_field(p, "scene_id")): p
        for p in (scene_plans or [])
        if _plan_field(p, "scene_id") is not None
    }
    flagged: Dict[int, str] = {}
    for t in scene_timings:
        start = t.start_time_seconds
        span = slot_seconds(t)
        findings = _scene_findings(ranges, t, start, span)
        if not findings:
            continue
        critique = (f"film QA: the final film is defective in this scene's slot "
                    f"({start:.1f}s-{start + span:.1f}s): {'; '.join(findings)}.")
        if settings.IMAGE_EVAL_MODEL:
            try:
                plan = plans.get(int(t.scene_id))
                defective, diagnosis = await _vision_diagnose(
                    video_path, start, span,
                    _plan_field(plan, "narration_text", "") if plan else "",
                    _plan_field(plan, "visual_description", "") if plan else "",
                    findings)
                if not defective:
                    logger.info("film QA: vision cleared flagged scene",
                                extra={"scene_id": t.scene_id, "findings": findings})
                    continue
                if diagnosis:
                    critique += f" Vision diagnosis: {diagnosis}"
            except Exception as e:  # noqa: BLE001 — deterministic finding stands alone
                logger.warning("film QA: vision diagnosis failed",
                               extra={"scene_id": t.scene_id, "error": str(e)[:200]})
        flagged[int(t.scene_id)] = critique
    return flagged, film_issues
