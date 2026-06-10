"""Deterministic HyperFrames HTML composition for the compositor service."""

from __future__ import annotations

import html
import re
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


def _inline_hyperframes_scene(html_path: str, scene_id: int) -> str:
    """Read a HyperFrames scene HTML file and return the body's content,
    rewritten so its root composition id and timeline registration key are
    namespaced to the scene_id (so multiple scenes coexist in one master DOM).
    """
    raw = Path(html_path).read_text(encoding="utf-8")

    # Extract <head>...</head> so we can pull <style> and <script> tags out.
    head_styles: List[str] = []
    head_scripts: List[str] = []
    head_match = re.search(r"<head[^>]*>(.*?)</head>", raw, re.IGNORECASE | re.DOTALL)
    if head_match:
        head_inner = head_match.group(1)
        head_styles = re.findall(
            r"<style[^>]*>.*?</style>", head_inner, re.IGNORECASE | re.DOTALL
        )
        head_scripts = re.findall(
            r"<script\b[^>]*>.*?</script>", head_inner, re.IGNORECASE | re.DOTALL
        )

    # Extract body inner HTML using a tolerant regex.
    body_inner = ""
    body_match = re.search(
        r"<body[^>]*>(.*?)</body>", raw, re.IGNORECASE | re.DOTALL
    )
    if body_match:
        body_inner = body_match.group(1)
    else:
        # Fallback: extract first <div id="composition" ...>...</div>
        div_match = re.search(
            r'<div\s+[^>]*id\s*=\s*["\']composition["\'][^>]*>.*?</div>',
            raw,
            re.IGNORECASE | re.DOTALL,
        )
        if div_match:
            body_inner = div_match.group(0)
        else:
            body_inner = raw

    # Strip stray DOCTYPE / html / head / body tags (defensive).
    body_inner = re.sub(r"<!DOCTYPE[^>]*>", "", body_inner, flags=re.IGNORECASE)
    body_inner = re.sub(r"</?html[^>]*>", "", body_inner, flags=re.IGNORECASE)
    body_inner = re.sub(
        r"<head[^>]*>.*?</head>", "", body_inner, flags=re.IGNORECASE | re.DOTALL
    )
    body_inner = re.sub(r"</?body[^>]*>", "", body_inner, flags=re.IGNORECASE)

    # Rewrite root composition id.
    new_id = f"composition-scene-{scene_id}"
    body_inner = body_inner.replace('id="composition"', f'id="{new_id}"')
    body_inner = body_inner.replace("id='composition'", f"id='{new_id}'")

    # Rewrite window.__timelines["scene-N"] keys to the canonical scene id.
    canonical_key = f'"scene-{scene_id}"'
    canonical_key_single = f"'scene-{scene_id}'"

    def _rewrite_timeline_double(match: "re.Match[str]") -> str:
        n = match.group(1)
        if n == str(scene_id):
            return match.group(0)
        return f'window.__timelines[{canonical_key}]'

    def _rewrite_timeline_single(match: "re.Match[str]") -> str:
        n = match.group(1)
        if n == str(scene_id):
            return match.group(0)
        return f"window.__timelines[{canonical_key_single}]"

    body_inner = re.sub(
        r'window\.__timelines\[\s*"scene-(\d+)"\s*\]',
        _rewrite_timeline_double,
        body_inner,
    )
    body_inner = re.sub(
        r"window\.__timelines\[\s*'scene-(\d+)'\s*\]",
        _rewrite_timeline_single,
        body_inner,
    )

    # Bare ["scene-N"] patterns (defensive).
    def _rewrite_bare_double(match: "re.Match[str]") -> str:
        n = match.group(1)
        if n == str(scene_id):
            return match.group(0)
        return f'[{canonical_key}]'

    def _rewrite_bare_single(match: "re.Match[str]") -> str:
        n = match.group(1)
        if n == str(scene_id):
            return match.group(0)
        return f"[{canonical_key_single}]"

    body_inner = re.sub(r'\[\s*"scene-(\d+)"\s*\]', _rewrite_bare_double, body_inner)
    body_inner = re.sub(r"\[\s*'scene-(\d+)'\s*\]", _rewrite_bare_single, body_inner)

    # Compose: head <style> tags BEFORE body content; head <script> tags AFTER.
    parts: List[str] = []
    parts.extend(head_styles)
    parts.append(body_inner)
    parts.extend(head_scripts)
    return "\n".join(parts)


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
            try:
                inlined = _inline_hyperframes_scene(timing.render_path, scene_id)
                body_parts.append(
                    f"""      <div class="clip scene-visual scene-host" id="host-scene-{scene_id}"
        data-start="{start}" data-duration="{slot_duration}"
        data-track-index="{track}"
        style="position:absolute;left:0;top:0;width:1920px;height:1080px;z-index:{track};background:#ffffff;overflow:hidden;">
{inlined}
      </div>"""
                )
            except (OSError, UnicodeDecodeError) as exc:
                logger.warning(
                    "Failed to inline HyperFrames scene %s from %s: %s; "
                    "falling back to iframe embedding.",
                    scene_id,
                    timing.render_path,
                    exc,
                )
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
