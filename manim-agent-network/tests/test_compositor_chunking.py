"""Tests for compositor chunk partitioning + rebasing (services/compositor/app/chunking.py)."""

import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from hypothesis import given, settings
from hypothesis import strategies as st

from shared.schemas.common import SceneTimingRecord
from services.compositor.app.chunking import partition_timings, rebase_chunk, slot_seconds


def _rec(i, dur, start):
    return SceneTimingRecord(
        scene_id=i, render_path=f"s{i}.mp4", audio_path="",
        actual_video_duration_seconds=dur, actual_audio_duration_seconds=dur,
        start_time_seconds=start,
    )


def _contiguous(n, dur):
    ts, acc = [], 0.0
    for i in range(1, n + 1):
        ts.append(_rec(i, dur, acc))
        acc += dur
    return ts


def test_partition_order_and_membership():
    ts = _contiguous(20, 45)
    parts = partition_timings(ts, max_scenes=8, max_seconds=300)
    flat = [t.scene_id for c in parts for t in c]
    assert flat == list(range(1, 21))            # order preserved, none lost/duplicated


def test_partition_respects_scene_cap():
    ts = _contiguous(20, 5)                       # tiny durations -> only scene cap bites
    parts = partition_timings(ts, max_scenes=8, max_seconds=10_000)
    assert all(len(c) <= 8 for c in parts)
    assert max(len(c) for c in parts) == 8


def test_partition_respects_seconds_cap():
    ts = _contiguous(20, 100)                      # 100s each -> closes well under 8 scenes
    parts = partition_timings(ts, max_scenes=8, max_seconds=300)
    # each chunk (except possibly the last) holds < 8 scenes because 3*100 >= 300
    assert all(len(c) <= 4 for c in parts)


def test_rebase_first_start_zero():
    ts = _contiguous(10, 30)
    parts = partition_timings(ts, max_scenes=4, max_seconds=10_000)
    for c in parts:
        rb = rebase_chunk(c)
        assert abs(rb[0].start_time_seconds) < 1e-9
        # internal gaps preserved
        for a, b in zip(rb, rb[1:]):
            assert b.start_time_seconds > a.start_time_seconds


@given(
    st.lists(st.floats(min_value=1.0, max_value=120.0), min_size=1, max_size=60),
    st.integers(min_value=1, max_value=12),
    st.floats(min_value=10.0, max_value=600.0),
)
@settings(max_examples=80)
def test_partition_total_membership_property(durs, max_scenes, max_seconds):
    ts, acc = [], 0.0
    for i, d in enumerate(durs, start=1):
        ts.append(_rec(i, d, acc))
        acc += d
    parts = partition_timings(ts, max_scenes, max_seconds)
    flat = [t.scene_id for c in parts for t in c]
    assert flat == [t.scene_id for t in ts]        # exactly-once, in order
    assert all(len(c) <= max_scenes for c in parts)
