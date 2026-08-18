"""Deterministic HyperFrames HTML composition for the compositor service."""

from __future__ import annotations

import html
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from shared.config import settings
from shared.log import get_logger
from shared.schemas.common import SceneTimingRecord

logger = get_logger(__name__)


# Captions live on their own reserved track so sequential windows can never
# collide with scene visuals/audio (which start at track 1). z-index is a
# constant so captions always render above scene visuals (track index != z-order).
CAPTION_TRACK_INDEX = 0
CAPTION_MAX_CHARS = 90
CAPTION_Z_INDEX = 1000

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?;:])\s+")


def _vtt_ts(t: float) -> str:
    """Seconds -> WebVTT timestamp HH:MM:SS.mmm."""
    if t < 0:
        t = 0.0
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def build_vtt(
    scene_timings: List[SceneTimingRecord],
    audio_segments: Optional[Dict[Any, list]],
    scene_plans: Optional[List[Any]],
) -> str:
    """Build a WebVTT track for the whole film. Cues come from the REAL per-sentence
    TTS segments (audio_segments) so captions match the spoken audio exactly — no
    word-count drift. For any scene without segments (e.g. edge-tts/piper fallback)
    we fall back to the word-count windows so it still has captions.
    """
    def _field(plan, key, default=None):
        return plan.get(key, default) if isinstance(plan, dict) else getattr(plan, key, default)

    narr: Dict[int, str] = {}
    for p in (scene_plans or []):
        sid = _field(p, "scene_id")
        if sid is not None:
            narr[int(sid)] = _field(p, "narration_text", "") or ""

    segs = audio_segments or {}
    def _segs_for(sid: int) -> list:
        return segs.get(sid) or segs.get(str(sid)) or []

    cues: List[tuple] = []
    for t in scene_timings:
        sid = int(t.scene_id)
        base = t.start_time_seconds
        scene_segs = _segs_for(sid)
        if scene_segs:
            for s in scene_segs:
                try:
                    start = base + float(s.get("start", 0.0))
                    dur = float(s.get("duration", 0.0))
                except (TypeError, ValueError):
                    continue
                txt = (s.get("text") or "").strip()
                if txt and dur > 0:
                    cues.append((start, start + dur, txt))
        else:
            # No real cue sheet — approximate from narration (matches burned path).
            chunks = chunk_narration(narr.get(sid, ""))
            if not chunks:
                continue
            window = max(t.actual_video_duration_seconds, t.actual_audio_duration_seconds)
            audio_dur = t.actual_audio_duration_seconds if t.audio_path else 0.0
            for c_start, c_dur, c_text in allocate_caption_windows(chunks, audio_dur, window, base):
                if c_text.strip() and c_dur > 0:
                    cues.append((c_start, c_start + c_dur, c_text.strip()))

    cues.sort(key=lambda c: c[0])
    out: List[str] = ["WEBVTT", ""]
    for i, (a, b, txt) in enumerate(cues, start=1):
        if b <= a:
            b = a + 0.5
        out.append(str(i))
        out.append(f"{_vtt_ts(a)} --> {_vtt_ts(b)}")
        out.append(txt)
        out.append("")
    return "\n".join(out)


def chunk_narration(text: str, max_chars: int = CAPTION_MAX_CHARS) -> List[str]:
    """Split narration into caption-sized chunks on word boundaries.

    Lossless: " ".join(chunks) == " ".join(text.split()). Sentences are packed
    greedily up to max_chars; an over-long sentence falls back to greedy word
    packing (a single word longer than max_chars becomes its own chunk).
    """
    normalized = " ".join((text or "").split())
    if not normalized:
        return []

    chunks: List[str] = []
    for sentence in _SENTENCE_SPLIT.split(normalized):
        if not sentence:
            continue
        if chunks and len(chunks[-1]) + 1 + len(sentence) <= max_chars:
            chunks[-1] = f"{chunks[-1]} {sentence}"
        elif len(sentence) <= max_chars:
            chunks.append(sentence)
        else:
            # Sentence too long: pack its words.
            cur = ""
            for word in sentence.split(" "):
                if cur and len(cur) + 1 + len(word) <= max_chars:
                    cur = f"{cur} {word}"
                else:
                    if cur:
                        chunks.append(cur)
                    cur = word
            if cur:
                chunks.append(cur)
    return chunks


def allocate_caption_windows(
    chunks: List[str],
    audio_duration: float,
    slot: float,
    scene_start: float,
) -> List[tuple]:
    """Assign each chunk a (start, duration, text) window within the scene.

    Windows chain exactly in 3-decimal space (start[i+1] == start[i]+dur[i]) so
    there is zero same-track overlap. Duration is proportional to word count.
    The final chunk absorbs rounding drift and is clamped to end at
    scene_start + min(window, slot), so captions never bleed into the next scene.
    """
    window = audio_duration if audio_duration > 0 else slot
    # Captions must fit inside the scene slot. Normally slot = max(video, audio)
    # >= audio so this is a no-op, but clamp defensively so a stray window > slot
    # can never push a caption past the slot boundary.
    window = min(window, slot)
    if not chunks or window <= 0:
        return []

    weights = [max(1, len(c.split())) for c in chunks]
    total_w = sum(weights)
    end_limit = round(scene_start + window, 3)

    out: List[tuple] = []
    cur = round(scene_start, 3)
    for i, (chunk, w) in enumerate(zip(chunks, weights)):
        if i == len(chunks) - 1:
            # Rounding drift can push cur past end_limit, going negative — that
            # silently DROPPED the last caption. Clamp to a minimal window and
            # log instead: a 1ms cue beats vanished text.
            dur = round(end_limit - cur, 3)
            if dur <= 0:
                logger.warning("Final caption window clamped (drift %.3fs) for chunk %r",
                               dur, chunk[:60])
                dur = 0.001
        else:
            dur = round(window * w / total_w, 3)
        if dur <= 0:
            continue
        out.append((cur, dur, chunk))
        cur = round(cur + dur, 3)
    return out


def _scene_value(scene: Any, key: str, default: Any = None) -> Any:
    if isinstance(scene, dict):
        return scene.get(key, default)
    return getattr(scene, key, default)


def _is_hyperframes_scene(render_path: str) -> bool:
    return render_path.lower().endswith(".html")


def _format_seconds(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _relative_to_composition(path: str, comp_dir: Path) -> str:
    try:
        return Path(path).relative_to(comp_dir).as_posix()
    except ValueError:
        return Path(path).as_posix()


# NOTE: HyperFrames scenes are mounted as sub-composition clips via
# data-composition-src. The HyperFrames compiler inlines them itself
# (core/src/compiler/inlineSubCompositions.ts): it scopes each scene's CSS
# to its composition root, wraps each scene script in an isolated closure
# (no top-level `const` collisions between scenes), drops the scene's own
# data-start="0" root, and auto-nests window.__timelines["scene-N"] at the
# host element's data-start. Hand-rolled regex inlining (previous approach)
# bypassed all of that and produced blank scenes.

# ─────────────────────────────────────────────────────────────────────────────
# Phase 2: Inter-scene transition system
# ─────────────────────────────────────────────────────────────────────────────

# Energy → transition spec (CSS-only dip-to-color crossfade; no external shaders).
# Durations are generous and easing is symmetric sine for a gentle, non-blinking
# fade. High energy stays snappier but still eased. (Previously _transition_clip
# hardcoded power2 and ignored these ease_* values — now wired through.)
_TRANSITION_SPECS = {
    "calm":   {"dur": 0.90, "ease_in": "sine.in",   "ease_out": "sine.out"},
    "medium": {"dur": 0.65, "ease_in": "sine.in",   "ease_out": "sine.out"},
    "high":   {"dur": 0.45, "ease_in": "power2.in",  "ease_out": "power2.out"},
}
_TRANSITION_TRACK_BASE = 200  # well above scene tracks, below CAPTION_Z_INDEX
_TRANSITION_Z = 900


def _pick_transition(energy: str, scene_idx: int, total_scenes: int) -> dict:
    """Select transition spec based on energy level and narrative position."""
    # Narrative position overrides: opening and outro get calm regardless of energy
    if scene_idx == 0 or scene_idx == total_scenes - 1:
        return _TRANSITION_SPECS["calm"]
    return _TRANSITION_SPECS.get(energy or "medium", _TRANSITION_SPECS["medium"])


def _transition_clip(
    tr_id: int,
    start: float,
    dur: float,
    bg_color: str,
    track: int,
    ease_in: str = "sine.in",
    ease_out: str = "sine.out",
) -> str:
    """Build a crossfade overlay clip between two scenes.

    The clip fades IN over the first half (covering the outgoing scene's end),
    then fades OUT over the second half (revealing the incoming scene's start).
    start = scene_N_end - dur/2  (overlaps outgoing scene end)
    end   = start + dur           (overlaps incoming scene start)
    Does NOT alter any existing scene data-start/data-duration values.
    """
    half = round(dur / 2, 3)
    s = _format_seconds(start)
    d = _format_seconds(dur)
    h = _format_seconds(half)
    return f"""      <div id="tr-{tr_id}"
        class="clip transition-overlay"
        data-start="{s}"
        data-duration="{d}"
        data-track-index="{track}"
        style="position:absolute;inset:0;background:{bg_color};z-index:{_TRANSITION_Z};pointer-events:none;opacity:0;">
        <script>
          (function(){{
            window.__timelines=window.__timelines||{{}};
            var t=gsap.timeline({{paused:true}});
            t.to("#tr-{tr_id}",{{autoAlpha:1,duration:{h},ease:"{ease_in}"}},0)
             .to("#tr-{tr_id}",{{autoAlpha:0,duration:{h},ease:"{ease_out}"}},{h});
            window.__timelines["tr-{tr_id}"]=t;
          }})();
        </script>
      </div>"""


def compose_html(
    script_title: str,
    scene_timings: List[SceneTimingRecord],
    image_paths: Dict[int, List[str]],
    job_id: str,
    scene_plans: Optional[List[Any]] = None,
    job_style: Optional[Dict[str, Any]] = None,
) -> str:
    """Generate a stable HyperFrames composition from probed scene timings."""
    comp_dir = Path(settings.WORKSPACE_DIR) / "temp" / job_id
    output_path = comp_dir / "composition.html"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    narration_by_scene = {
        int(_scene_value(scene, "scene_id")): _scene_value(scene, "narration_text", "")
        for scene in (scene_plans or [])
    }
    total_duration = max(
        (
            timing.start_time_seconds
            + max(timing.actual_video_duration_seconds, timing.actual_audio_duration_seconds)
        )
        for timing in scene_timings
    ) if scene_timings else 0.001

    # Resolve the job palette ONCE — used for the backdrop behind EVERY scene AND
    # for transitions, so the whole composition shares one consistent background.
    # Previously host/body/master fell back to hardcoded #0a0f1c/#ffffff regardless
    # of job_style; a light-palette scene then mounted on a dark host, so whenever a
    # scene's own bg didn't fully cover (wrapper dropped / partial / LLM drift) the
    # wrong backdrop showed and its text/animation became invisible. One pal_bg fixes
    # bg+text mismatch and the transition flash on the auto and explicit-style paths.
    energy = (job_style or {}).get("energy", "medium")
    pal_bg = (job_style or {}).get("palette_bg", "#0e1116")
    tr_bg = pal_bg
    n_scenes = len(scene_timings)

    body_parts: List[str] = []
    track = 1
    for timing_idx, timing in enumerate(scene_timings):
        scene_id = timing.scene_id
        start = _format_seconds(timing.start_time_seconds)
        video_duration = _format_seconds(timing.actual_video_duration_seconds)
        audio_duration = _format_seconds(timing.actual_audio_duration_seconds)
        slot_duration = _format_seconds(
            max(timing.actual_video_duration_seconds, timing.actual_audio_duration_seconds)
        )
        rel_render = html.escape(_relative_to_composition(timing.render_path, comp_dir), quote=True)
        rel_audio = html.escape(_relative_to_composition(timing.audio_path, comp_dir), quote=True)
        narration_raw = narration_by_scene.get(scene_id, "") or ""

        if _is_hyperframes_scene(timing.render_path):
            # Sub-composition clip: the HyperFrames compiler inlines + scopes
            # the scene file and auto-nests window.__timelines["scene-N"] at
            # this host's data-start. data-composition-id MUST equal the
            # scene file's root data-composition-id and its timeline key.
            # Scene files are copied into compositions/ so the project keeps a
            # single root composition (the CLI lints root-level HTML files with
            # data-composition-id as duplicate entry points).
            comps_dir = comp_dir / "compositions"
            comps_dir.mkdir(parents=True, exist_ok=True)
            scene_dest = comps_dir / f"scene_{scene_id}.html"
            if Path(timing.render_path).resolve() != scene_dest.resolve():
                shutil.copyfile(timing.render_path, scene_dest)
            rel_sub = f"compositions/scene_{scene_id}.html"
            body_parts.append(
                f"""      <div class="clip scene-visual scene-host" id="host-scene-{scene_id}"
        data-composition-id="scene-{scene_id}"
        data-composition-src="{rel_sub}"
        data-start="{start}" data-duration="{slot_duration}"
        data-track-index="{track}"
        data-width="1920" data-height="1080"
        style="position:absolute;left:0;top:0;width:1920px;height:1080px;z-index:{track};background:{pal_bg};overflow:hidden;"></div>"""
            )
        else:
            # Use slot_duration (max of video/audio) so the video element holds
            # its last frame for the whole slot instead of vanishing to a white
            # frame when the narration audio outlasts the rendered video.
            body_parts.append(
                f"""      <video
        class="clip scene-visual"
        id="video-scene-{scene_id}"
        data-start="{start}"
        data-duration="{slot_duration}"
        data-track-index="{track}"
        src="{rel_render}"
        style="position:absolute;left:0;top:0;width:1920px;height:1080px;object-fit:contain;background:{pal_bg};z-index:{track};"
        muted
        playsinline></video>"""
            )
        track += 1

        if settings.BURN_CAPTIONS and narration_raw.strip():
            # Burned-in captions (opt-in via BURN_CAPTIONS). Default OFF: captions
            # ship as a soft WebVTT track (see build_vtt) so viewers can toggle CC.
            # Chunked captions: split narration into sentence-sized pieces, each
            # with its own timed window. Sequential windows on a single reserved
            # track (0) -> zero overlap; no 120-char truncation -> no lost text.
            chunks = chunk_narration(narration_raw)
            windows = allocate_caption_windows(
                chunks,
                timing.actual_audio_duration_seconds if timing.audio_path else 0.0,
                max(timing.actual_video_duration_seconds, timing.actual_audio_duration_seconds),
                timing.start_time_seconds,
            )
            for ci, (c_start, c_dur, c_text) in enumerate(windows, start=1):
                body_parts.append(
                    f"""      <div
        class="clip lower-third"
        id="caption-scene-{scene_id}-{ci}"
        data-start="{_format_seconds(c_start)}"
        data-duration="{_format_seconds(c_dur)}"
        data-track-index="{CAPTION_TRACK_INDEX}"
        style="z-index:{CAPTION_Z_INDEX};">{html.escape(c_text, quote=False)}</div>"""
                )

        if timing.audio_path:
            body_parts.append(
                f"""      <audio
        class="clip"
        id="audio-scene-{scene_id}"
        data-start="{start}"
        data-duration="{audio_duration}"
        data-track-index="{track}"
        src="{rel_audio}"></audio>"""
            )
            track += 1

        # Phase 2: inject crossfade transition AFTER each scene except the last.
        # Overlaps the end of this scene and start of the next — never shifts data-start.
        if timing_idx < n_scenes - 1:
            next_timing = scene_timings[timing_idx + 1]
            tr_spec = _pick_transition(energy, timing_idx, n_scenes)
            tr_dur = tr_spec["dur"]
            scene_end = timing.start_time_seconds + max(
                timing.actual_video_duration_seconds,
                timing.actual_audio_duration_seconds,
            )
            tr_start = max(0.0, scene_end - tr_dur / 2)
            tr_track = _TRANSITION_TRACK_BASE + timing_idx
            body_parts.append(_transition_clip(
                timing_idx, tr_start, tr_dur, tr_bg, tr_track,
                tr_spec["ease_in"], tr_spec["ease_out"],
            ))

    title = html.escape(script_title or "Generated Video", quote=False)
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <style>
    html, body {{
      margin: 0;
      width: 1920px;
      height: 1080px;
      overflow: hidden;
      background: {pal_bg};
      font-family: Arial, Helvetica, sans-serif;
    }}
    .lower-third {{
      position: absolute;
      left: 0;
      right: 0;
      bottom: 48px;
      margin: 0 auto;
      max-width: 1100px;
      padding: 14px 28px;
      border-radius: 8px;
      background: rgba(0, 0, 0, 0.8);
      color: #fff;
      font-size: 28px;
      line-height: 1.3;
      text-align: center;
      box-sizing: border-box;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }}
  </style>
</head>
<body>
  <div
    id="composition"
    data-composition-id="main"
    data-start="0"
    data-duration="{_format_seconds(total_duration)}"
    data-width="1920"
    data-height="1080"
    style="position:relative;width:1920px;height:1080px;background:{pal_bg};overflow:hidden;">
{chr(10).join(body_parts)}
  </div>
  <!-- Same GSAP URL the generated scenes use, so the compiler dedupes to one load. -->
  <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
  <script>
    (function () {{
      window.__timelines = window.__timelines || {{}};
      // Master timeline stays empty: scene sub-timelines are auto-nested by
      // the HyperFrames runtime (keyed by data-composition-id), and clip
      // visibility windows are compiled from data-start/data-duration.
      window.__timelines["main"] = gsap.timeline({{ paused: true }});
    }})();
  </script>
</body>
</html>
"""
    output_path.write_text(html_content, encoding="utf-8")
    return str(output_path)


def _build_composition_prompt(
    script_title: str,
    scene_timings: List[SceneTimingRecord],
    image_paths: Dict[int, List[str]],
    job_id: str = "",
) -> str:
    """Kept for older tests; composition is generated deterministically now."""
    total_duration = max(
        (
            timing.start_time_seconds
            + max(timing.actual_video_duration_seconds, timing.actual_audio_duration_seconds)
        )
        for timing in scene_timings
    ) if scene_timings else 0.001
    return (
        f"Deterministic HyperFrames composition for {script_title}; "
        f"root data-composition-id='main' data-width='1920' data-height='1080' "
        f"data-duration='{_format_seconds(total_duration)}'; "
        "media elements include id, data-start, data-duration, and data-track-index."
    )


def _extract_html(llm_response: str) -> str:
    if not llm_response:
        return ""

    doctype_match = re.search(r"<!DOCTYPE\s+html[^>]*>", llm_response, re.IGNORECASE)
    if doctype_match:
        start_idx = doctype_match.start()
        html_end_match = re.search(r"</html>", llm_response[start_idx:], re.IGNORECASE)
        if html_end_match:
            end_idx = start_idx + html_end_match.end()
            return llm_response[start_idx:end_idx]

    html_match = re.search(r"<html[^>]*>", llm_response, re.IGNORECASE)
    if html_match:
        start_idx = html_match.start()
        html_end_match = re.search(r"</html>", llm_response[start_idx:], re.IGNORECASE)
        if html_end_match:
            end_idx = start_idx + html_end_match.end()
            return llm_response[start_idx:end_idx]

    return ""
