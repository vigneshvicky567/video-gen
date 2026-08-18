"""Pure helpers for splitting a composition into renderable chunks.

The HyperFrames CLI has no time-window flags, so a long composition is rendered
as several shorter compositions (built from scene-subsets with rebased start
times) and joined with ffmpeg concat. These functions are side-effect free and
unit-testable; main.py owns the actual HTML regeneration and rendering.
"""

from __future__ import annotations

from typing import List

from shared.schemas.common import SceneTimingRecord


def slot_seconds(t: SceneTimingRecord) -> float:
    """A scene occupies max(video, audio) — same rule as duration_prober."""
    return max(t.actual_video_duration_seconds, t.actual_audio_duration_seconds)


def partition_timings(
    timings: List[SceneTimingRecord],
    max_scenes: int,
    max_seconds: float,
) -> List[List[SceneTimingRecord]]:
    """Greedy, order-preserving partition. Close a chunk once it reaches
    max_scenes scenes OR max_seconds of content. Chunk boundaries fall exactly
    on scene-slot boundaries (timings are contiguous), so no clip is split.
    """
    chunks: List[List[SceneTimingRecord]] = []
    cur: List[SceneTimingRecord] = []
    cur_s = 0.0
    for t in timings:
        if cur and (len(cur) >= max_scenes or cur_s >= max_seconds):
            chunks.append(cur)
            cur, cur_s = [], 0.0
        cur.append(t)
        cur_s += slot_seconds(t)
    if cur:
        chunks.append(cur)
    return chunks


def rebase_chunk(chunk: List[SceneTimingRecord]) -> List[SceneTimingRecord]:
    """Shift a chunk's scene start times so the first scene starts at 0,
    so each chunk renders as a standalone composition.
    """
    if not chunk:
        return []
    offset = chunk[0].start_time_seconds
    return [
        t.model_copy(update={"start_time_seconds": round(t.start_time_seconds - offset, 3)})
        for t in chunk
    ]
