"""Tests for freeze-padding short Manim renders to their narration slot.

Bug: when narration audio outlasts the rendered Manim video, the composition's
<video> element ends mid-slot and goes blank ("manim disappears before the
narration finishes"). freeze_pad_renders clones the last frame so the file is
genuinely slot-long.

These tests drive REAL ffmpeg (synthesize a short clip, pad it, ffprobe the
result), so they are skipped where ffmpeg/ffprobe are unavailable.
"""
import shutil
import subprocess

import pytest

from services.compositor.app.duration_prober import freeze_pad_renders, probe_duration
from shared.schemas.common import SceneTimingRecord

pytestmark = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
    reason="ffmpeg/ffprobe not available",
)


def _make_clip(path, seconds, rate=30):
    cmd = [
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"testsrc=duration={seconds}:size=320x240:rate={rate}",
        "-pix_fmt", "yuv420p", str(path),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0 and path.exists(), r.stderr[:400]


def _rec(scene_id, render_path, vid_s, aud_s, audio_path="/x/a.wav"):
    return SceneTimingRecord(
        scene_id=scene_id,
        render_path=str(render_path),
        audio_path=audio_path,
        actual_video_duration_seconds=vid_s,
        actual_audio_duration_seconds=aud_s,
        start_time_seconds=0.0,
    )


def test_pads_short_video_to_audio_slot(tmp_path):
    clip = tmp_path / "scene_1.mp4"
    _make_clip(clip, seconds=2)
    probed = probe_duration(str(clip))  # ~2.0

    out = freeze_pad_renders([_rec(1, clip, probed, 5.0)], tmp_path / "padded")

    assert len(out) == 1
    rec = out[0]
    # render_path replaced with the padded file, video duration bumped to slot
    assert rec.render_path != str(clip)
    assert rec.render_path.endswith("padded/scene_1.mp4") or rec.render_path.endswith("padded\\scene_1.mp4")
    assert rec.actual_video_duration_seconds == pytest.approx(5.0, abs=0.01)
    # the file itself is now genuinely ~5s (last frame cloned for the gap)
    assert probe_duration(rec.render_path) == pytest.approx(5.0, abs=0.25)
    # audio duration + scene_id are preserved
    assert rec.actual_audio_duration_seconds == 5.0
    assert rec.scene_id == 1


def test_no_pad_when_video_outlasts_audio(tmp_path):
    clip = tmp_path / "scene_2.mp4"
    _make_clip(clip, seconds=4)
    probed = probe_duration(str(clip))

    out = freeze_pad_renders([_rec(2, clip, probed, 1.0)], tmp_path / "padded")

    # unchanged: same record, original path, no padded file produced
    assert out[0].render_path == str(clip)
    assert out[0].actual_video_duration_seconds == probed
    assert not (tmp_path / "padded").exists()


def test_no_pad_for_tiny_gap(tmp_path):
    clip = tmp_path / "scene_3.mp4"
    _make_clip(clip, seconds=2)
    probed = probe_duration(str(clip))

    # gap of 20ms < _PAD_EPSILON -> not worth a re-encode
    out = freeze_pad_renders([_rec(3, clip, probed, probed + 0.02)], tmp_path / "padded")
    assert out[0].render_path == str(clip)


def test_html_scene_never_padded(tmp_path):
    # HyperFrames .html scenes hold their final DOM state; must be left alone
    # even though audio > video.
    rec = _rec(4, "/workspace/temp/job/compositions/scene_4.html", 3.0, 9.0, audio_path="/x/a.wav")
    out = freeze_pad_renders([rec], tmp_path / "padded")
    assert out[0].render_path.endswith("scene_4.html")
    assert out[0].actual_video_duration_seconds == 3.0
    assert not (tmp_path / "padded").exists()
