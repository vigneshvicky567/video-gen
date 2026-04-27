"""Duration probing and scene timing computation for the compositor service.

This module provides functionality to:
1. Probe media file durations using ffprobe
2. Compute scene start times by accumulating actual durations
"""

import json
import subprocess
from typing import Dict, List

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
) -> List[SceneTimingRecord]:
    """Probe all files and compute start_time_seconds by accumulation.
    
    Args:
        render_paths: Mapping of scene_id to video file path
        audio_paths: Mapping of scene_id to audio file path
        
    Returns:
        List of SceneTimingRecord objects with computed start times
        
    Raises:
        AssemblyError: If any file cannot be probed
    """
    records = []
    accumulated = 0.0
    
    for scene_id in sorted(render_paths.keys()):
        video_dur = probe_duration(render_paths[scene_id])
        audio_dur = probe_duration(audio_paths[scene_id])
        
        records.append(SceneTimingRecord(
            scene_id=scene_id,
            render_path=render_paths[scene_id],
            audio_path=audio_paths[scene_id],
            actual_video_duration_seconds=video_dur,
            actual_audio_duration_seconds=audio_dur,
            start_time_seconds=round(accumulated, 3),
        ))
        
        accumulated += max(video_dur, audio_dur)
    
    return records
