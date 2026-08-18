"""Duration probing and scene timing computation for the compositor service.

This module provides functionality to:
1. Probe media file durations using ffprobe
2. Compute scene start times by accumulating actual durations
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Union

from shared.proc import run_proc, ProcTimeout
from shared.schemas.common import SceneTimingRecord

logger = logging.getLogger(__name__)

# Freeze-pad gaps below this (seconds) aren't worth a re-encode.
_PAD_EPSILON = 0.05


class AssemblyError(Exception):
    """Custom exception for assembly-related errors."""
    pass


def probe_duration(file_path: str) -> float:
    """Run ffprobe and return duration in seconds (3 decimal places).
    
    Args:
        file_path: Absolute path to the media file to probe
        
    Returns:
        Duration in seconds, rounded to 3 decimal places
        
    Raises:
        AssemblyError: If ffprobe fails or stream data is missing
    """
    # HTML files (HyperFrames scenes) have no media duration — return 0
    # The compositor will use estimated_duration_seconds from the scene plan instead
    if file_path.lower().endswith(".html"):
        return 0.0

    # Probe the CONTAINER (format) duration, not streams[0]: stream order is
    # arbitrary (video/audio/cover-art) and many MP4/WebM containers omit
    # per-stream duration entirely — it lives only in `format`. Fall back to
    # the max of per-stream durations for containers that omit format duration.
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_entries", "format=duration:stream=duration",
        file_path
    ]
    try:
        result = run_proc(cmd, timeout=120)
    except ProcTimeout:
        raise AssemblyError(f"ffprobe timed out probing {file_path}")

    if result.returncode != 0:
        raise AssemblyError(f"ffprobe failed for {file_path}: {result.stderr}")

    try:
        data = json.loads(result.stdout)
    except ValueError as e:
        raise AssemblyError(f"ffprobe emitted non-JSON for {file_path}: {e}")

    fmt_dur = (data.get("format") or {}).get("duration")
    if fmt_dur is not None:
        try:
            return round(float(fmt_dur), 3)
        except (TypeError, ValueError):
            pass
    stream_durs = []
    for s in data.get("streams") or []:
        try:
            stream_durs.append(float(s["duration"]))
        except (KeyError, TypeError, ValueError):
            continue
    if stream_durs:
        return round(max(stream_durs), 3)
    raise AssemblyError(f"ffprobe found no duration (format or streams) for {file_path}")


def compute_scene_timings(
    render_paths: Dict[int, str],
    audio_paths: Dict[int, str],
    scene_plans: List = None,
) -> List[SceneTimingRecord]:
    """Probe all files and compute start_time_seconds by accumulation.
    
    For HyperFrames HTML scenes, uses estimated_duration_seconds from scene_plans
    since HTML files have no media duration.
    
    Args:
        render_paths: Mapping of scene_id to video/html file path
        audio_paths: Mapping of scene_id to audio file path
        scene_plans: Optional list of ScenePlan objects for estimated durations
        
    Returns:
        List of SceneTimingRecord objects with computed start times
        
    Raises:
        AssemblyError: If any file cannot be probed
    """
    # Normalize keys to int — JSON serialization turns int keys into strings.
    # Tolerate a malformed key (e.g. "scene-0") by skipping it with a warning
    # instead of aborting the whole composition with a bare ValueError.
    def _coerce_int_keys(mapping: Dict, label: str) -> Dict[int, str]:
        out = {}
        for k, v in mapping.items():
            try:
                out[int(k)] = v
            except (ValueError, TypeError):
                logger.warning("Skipping non-integer %s key %r", label, k)
        return out

    render_paths = _coerce_int_keys(render_paths, "render_paths")
    audio_paths  = _coerce_int_keys(audio_paths, "audio_paths")

    # Build estimated duration lookup from scene plans
    estimated_durations = {}
    if scene_plans:
        for scene in scene_plans:
            sid = scene["scene_id"] if isinstance(scene, dict) else scene.scene_id
            dur = scene["estimated_duration_seconds"] if isinstance(scene, dict) else scene.estimated_duration_seconds
            estimated_durations[sid] = float(dur)

    records = []
    accumulated = 0.0
    
    for scene_id in sorted(render_paths.keys()):
        render_path = render_paths[scene_id]
        is_html = render_path.lower().endswith(".html")
        
        # For HTML scenes, use estimated duration; for MP4, probe with ffprobe.
        # A single unprobeable file must degrade only its own scene — falling
        # back to the planned duration — not abort the whole composition.
        if is_html:
            video_dur = estimated_durations.get(scene_id, 5.0)
        else:
            try:
                video_dur = probe_duration(render_path)
            except AssemblyError as e:
                video_dur = estimated_durations.get(scene_id, 5.0)
                logger.warning(
                    "Video probe failed for scene %s (%s); using estimated %.3fs",
                    scene_id, e, video_dur,
                )

        # A scene may legitimately have no audio (e.g. TTS skipped). Tolerate it
        # instead of crashing the whole composition with a KeyError. A present
        # but unprobeable audio file degrades to silent timing for that scene.
        audio_path = audio_paths.get(scene_id)
        if audio_path:
            try:
                audio_dur = probe_duration(audio_path)
            except AssemblyError as e:
                audio_dur = 0.0
                logger.warning(
                    "Audio probe failed for scene %s (%s); treating as silent",
                    scene_id, e,
                )
        else:
            audio_dur = 0.0

        records.append(SceneTimingRecord(
            scene_id=scene_id,
            render_path=render_path,
            audio_path=audio_path or "",
            actual_video_duration_seconds=video_dur,
            actual_audio_duration_seconds=audio_dur,
            start_time_seconds=round(accumulated, 3),
        ))
        
        accumulated += max(video_dur, audio_dur)

    return records


def freeze_pad_renders(
    scene_timings: List[SceneTimingRecord],
    pad_dir: Union[str, Path],
) -> List[SceneTimingRecord]:
    """Freeze-pad each video render whose narration audio outlasts the video.

    A scene's ``<video>`` element in the composition is given
    ``data-duration`` = the slot (max of video/audio). When the narration audio
    is longer than the rendered Manim video, the mp4 ends mid-slot and the
    ``<video>`` element goes blank for the remainder — the visual "disappears"
    before the narration finishes. HyperFrames ``.html`` scenes don't have this
    problem (their final DOM state persists), so only real video files are
    padded.

    For each affected mp4 we clone the last frame for the missing duration with
    ffmpeg ``tpad``, producing a file that is genuinely slot-long. Returns a new
    list with ``render_path`` / ``actual_video_duration_seconds`` updated for any
    padded scene. Fail-soft: on any ffmpeg error the original record is kept so
    padding can never abort a job.
    """
    pad_dir = Path(pad_dir)
    updated: List[SceneTimingRecord] = []
    for t in scene_timings:
        gap = t.actual_audio_duration_seconds - t.actual_video_duration_seconds
        if (
            t.render_path.lower().endswith(".html")
            or t.actual_video_duration_seconds <= 0
            or gap <= _PAD_EPSILON
        ):
            updated.append(t)
            continue

        pad_dir.mkdir(parents=True, exist_ok=True)
        out = pad_dir / f"scene_{t.scene_id}.mp4"
        cmd = [
            "ffmpeg", "-y", "-i", t.render_path,
            "-vf", f"tpad=stop_mode=clone:stop_duration={gap:.3f}",
            "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
            str(out),
        ]
        try:
            result = run_proc(cmd, timeout=300)
        except Exception as e:  # noqa: BLE001 — never let padding abort a job
            logger.warning("freeze-pad ffmpeg crashed for scene %s (%s); keeping original render",
                           t.scene_id, e)
            updated.append(t)
            continue

        if result.returncode != 0 or not out.exists() or out.stat().st_size == 0:
            logger.warning("freeze-pad failed for scene %s (rc=%s); keeping original render: %s",
                           t.scene_id, result.returncode, result.stderr[:300])
            updated.append(t)
            continue

        # Re-probe the padded output instead of ASSUMING tpad produced exactly
        # slot length — frame-boundary rounding can differ, and downstream
        # timings are computed from this value.
        try:
            padded_dur = probe_duration(str(out))
        except AssemblyError:
            padded_dur = round(t.actual_audio_duration_seconds, 3)
            logger.warning("freeze-pad re-probe failed for scene %s; using slot length",
                           t.scene_id)

        logger.info("freeze-padded scene %s: %.3fs video -> %.3fs (slot %.3fs)",
                    t.scene_id, t.actual_video_duration_seconds, padded_dur,
                    t.actual_audio_duration_seconds)
        updated.append(t.model_copy(update={
            "render_path": str(out),
            "actual_video_duration_seconds": padded_dur,
        }))

    return updated
