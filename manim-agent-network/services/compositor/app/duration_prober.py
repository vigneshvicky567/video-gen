"""Duration probing and scene timing computation for the compositor service.

This module provides functionality to:
1. Probe media file durations using ffprobe
2. Compute scene start times by accumulating actual durations
"""

import json
import subprocess
from typing import Dict, List, Optional

from shared.schemas.common import SceneTimingRecord


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

    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        file_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        raise AssemblyError(f"ffprobe failed for {file_path}: {result.stderr}")
    
    try:
        data = json.loads(result.stdout)
        duration = float(data["streams"][0]["duration"])
        return round(duration, 3)
    except (KeyError, IndexError, ValueError) as e:
        raise AssemblyError(f"ffprobe missing stream data for {file_path}: {e}")


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
        
        # For HTML scenes, use estimated duration; for MP4, probe with ffprobe
        if is_html:
            video_dur = estimated_durations.get(scene_id, 5.0)
        else:
            video_dur = probe_duration(render_path)
        
        audio_dur = probe_duration(audio_paths[scene_id])
        
        records.append(SceneTimingRecord(
            scene_id=scene_id,
            render_path=render_path,
            audio_path=audio_paths[scene_id],
            actual_video_duration_seconds=video_dur,
            actual_audio_duration_seconds=audio_dur,
            start_time_seconds=round(accumulated, 3),
        ))
        
        accumulated += max(video_dur, audio_dur)
    
    return records
