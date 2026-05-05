"""Deterministic HyperFrames HTML composition for the compositor service."""

from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from shared.config import settings
from shared.schemas.common import SceneTimingRecord


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
            body_parts.append(
                f"""      <iframe
        class="clip scene-visual"
        id="iframe-scene-{scene_id}"
        data-start="{start}"
        data-duration="{slot_duration}"
        data-track-index="{track}"
        src="{rel_render}"
        style="position:absolute;left:0;top:0;width:1920px;height:1080px;border:0;z-index:{track};"
        frameborder="0"
        allowfullscreen></iframe>"""
            )
        else:
            body_parts.append(
                f"""      <video
        class="clip scene-visual"
        id="video-scene-{scene_id}"
        data-start="{start}"
        data-duration="{video_duration}"
        data-track-index="{track}"
        src="{rel_render}"
        style="position:absolute;left:0;top:0;width:1920px;height:1080px;object-fit:cover;z-index:{track};"
        muted
        playsinline></video>"""
            )
        track += 1

        if narration:
            body_parts.append(
                f"""      <div
        class="clip lower-third"
        id="lower-scene-{scene_id}"
        data-start="{start}"
        data-duration="{audio_duration}"
        data-track-index="{track}"
        style="z-index:{track};">{narration}</div>"""
            )
            track += 1

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
      background: #0f0f0f;
      font-family: Arial, Helvetica, sans-serif;
    }}
    .lower-third {{
      position: absolute;
      left: 50%;
      bottom: 56px;
      transform: translateX(-50%);
      width: min(1320px, calc(100% - 160px));
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
    style="position:relative;width:1920px;height:1080px;background:#0f0f0f;overflow:hidden;">
{chr(10).join(body_parts)}
  </div>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.2/gsap.min.js"></script>
  <script>
    const tl = gsap.timeline({{ paused: true }});
    window.__timelines = window.__timelines || {{}};
    window.__timelines["main"] = tl;
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
