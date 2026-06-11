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


def truncate_lower_third(text: str) -> str:
    return text[:120]


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


def compose_html(
    script_title: str,
    scene_timings: List[SceneTimingRecord],
    image_paths: Dict[int, List[str]],
    job_id: str,
    scene_plans: Optional[List[Any]] = None,
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

    body_parts: List[str] = []
    track = 1
    for timing in scene_timings:
        scene_id = timing.scene_id
        start = _format_seconds(timing.start_time_seconds)
        video_duration = _format_seconds(timing.actual_video_duration_seconds)
        audio_duration = _format_seconds(timing.actual_audio_duration_seconds)
        slot_duration = _format_seconds(
            max(timing.actual_video_duration_seconds, timing.actual_audio_duration_seconds)
        )
        rel_render = html.escape(_relative_to_composition(timing.render_path, comp_dir), quote=True)
        rel_audio = html.escape(_relative_to_composition(timing.audio_path, comp_dir), quote=True)
        narration = html.escape(
            truncate_lower_third(narration_by_scene.get(scene_id, "")),
            quote=False,
        )

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
        style="position:absolute;left:0;top:0;width:1920px;height:1080px;z-index:{track};background:#0a0f1c;overflow:hidden;"></div>"""
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
        style="position:absolute;left:0;top:0;width:1920px;height:1080px;object-fit:contain;background:#ffffff;z-index:{track};"
        muted
        playsinline></video>"""
            )
        track += 1

        if narration:
            # Caption holds for the narration; without audio, for the slot.
            caption_duration = audio_duration if timing.audio_path else slot_duration
            body_parts.append(
                f"""      <div
        class="clip lower-third"
        id="lower-scene-{scene_id}"
        data-start="{start}"
        data-duration="{caption_duration}"
        data-track-index="{track}"
        style="z-index:{track};">{narration}</div>"""
            )
            track += 1

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
      background: #ffffff;
      font-family: Arial, Helvetica, sans-serif;
    }}
    .lower-third {{
      position: absolute;
      left: 0;
      right: 0;
      bottom: 56px;
      margin: 0 auto;
      max-width: 1320px;
      padding: 18px 32px;
      border-radius: 8px;
      background: rgba(0, 0, 0, 0.76);
      color: #fff;
      font-size: 30px;
      line-height: 1.25;
      text-align: center;
      box-sizing: border-box;
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
    style="position:relative;width:1920px;height:1080px;background:#ffffff;overflow:hidden;">
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
