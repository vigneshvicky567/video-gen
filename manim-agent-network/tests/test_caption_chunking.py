"""Tests for caption chunking + window allocation in compose_html
(services/compositor/app/llm_composer.py)."""

import os
import re
import sys
from html import unescape
from unittest.mock import patch

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from shared.schemas.common import SceneTimingRecord
from services.compositor.app import llm_composer
from services.compositor.app.llm_composer import (
    chunk_narration, allocate_caption_windows, compose_html, CAPTION_TRACK_INDEX,
)


# ── chunk_narration ──────────────────────────────────────────────────────────
def test_chunk_empty_and_whitespace():
    assert chunk_narration("") == []
    assert chunk_narration("   \n  ") == []


def test_chunk_short_text_single_chunk():
    t = "A short sentence."
    assert chunk_narration(t) == [t]


def test_chunk_lossless_word_boundary():
    t = ("Gradient descent finds the minimum of a loss function. It takes small "
         "steps downhill, proportional to the slope, until it converges.")
    chunks = chunk_narration(t)
    assert " ".join(chunks) == " ".join(t.split())
    for c in chunks:
        assert len(c) <= 90 or " " not in c


def test_chunk_single_long_word_unsplit():
    big = "x" * 200
    assert chunk_narration(big) == [big]


# ── allocate_caption_windows ─────────────────────────────────────────────────
def test_windows_chain_exactly():
    chunks = ["one two", "three four five", "six"]
    w = allocate_caption_windows(chunks, audio_duration=12.0, slot=12.0, scene_start=5.0)
    assert abs(w[0][0] - 5.0) < 1e-9
    for a, b in zip(w, w[1:]):
        assert abs((a[0] + a[1]) - b[0]) < 1e-6
    assert abs((w[-1][0] + w[-1][1]) - 17.0) < 1e-6   # clamped to start + window
    assert all(d > 0 for _, d, _ in w)


def test_windows_no_audio_uses_slot():
    chunks = ["alpha", "beta"]
    w = allocate_caption_windows(chunks, audio_duration=0.0, slot=8.0, scene_start=0.0)
    assert abs((w[-1][0] + w[-1][1]) - 8.0) < 1e-6


def test_windows_clamped_to_slot_when_audio_exceeds():
    chunks = ["alpha", "beta", "gamma"]
    w = allocate_caption_windows(chunks, audio_duration=20.0, slot=10.0, scene_start=2.0)
    assert (w[-1][0] + w[-1][1]) <= 2.0 + 10.0 + 1e-6


# ── compose_html integration ─────────────────────────────────────────────────
def _timing(scene_id, start, vid, aud, render_path, audio_path):
    return SceneTimingRecord(
        scene_id=scene_id, render_path=render_path, audio_path=audio_path,
        actual_video_duration_seconds=vid, actual_audio_duration_seconds=aud,
        start_time_seconds=start,
    )


def test_compose_html_chunked_captions(tmp_path):
    narration = ("Neural networks learn by adjusting weights. Each layer transforms "
                 "the input a little. Errors flow backward to correct the weights. "
                 "Over many steps the network improves its predictions steadily.")
    job_id = "captiontest"
    comp = tmp_path / "temp" / job_id
    comp.mkdir(parents=True)
    (comp / "scene1.mp4").write_bytes(b"\x00")
    (comp / "scene1.wav").write_bytes(b"\x00")

    timings = [_timing(1, 0.0, 10.0, 12.0, str(comp / "scene1.mp4"), str(comp / "scene1.wav"))]
    scene_plans = [{"scene_id": 1, "narration_text": narration, "content_type": "manim"}]

    fake = type("S", (), {"WORKSPACE_DIR": str(tmp_path)})()
    with patch.object(llm_composer, "settings", fake):
        html_path = compose_html("Title", timings, {}, job_id, scene_plans)
    html = open(html_path, encoding="utf-8").read()

    cap_divs = re.findall(
        r'<div\s+class="clip lower-third"[^>]*data-start="([\d.]+)"[^>]*data-duration="([\d.]+)"[^>]*data-track-index="(\d+)"[^>]*>(.*?)</div>',
        html, re.DOTALL,
    )
    assert len(cap_divs) >= 2, "expected multiple caption chunks"
    # all captions on the reserved track
    assert all(int(t) == CAPTION_TRACK_INDEX for _, _, t, _ in cap_divs)
    # sequential, non-overlapping
    for (s1, d1, _, _), (s2, _, _, _) in zip(cap_divs, cap_divs[1:]):
        assert float(s1) + float(d1) <= float(s2) + 1e-3
    # full narration reconstructable, no 120-char cut
    joined = " ".join(unescape(txt).strip() for _, _, _, txt in cap_divs)
    assert joined == " ".join(narration.split())
    assert len(narration) > 120  # the old truncation would have dropped text


def test_compose_html_non_caption_clips_never_on_caption_track(tmp_path):
    job_id = "tracktest"
    comp = tmp_path / "temp" / job_id
    comp.mkdir(parents=True)
    (comp / "s1.mp4").write_bytes(b"\x00")
    (comp / "s1.wav").write_bytes(b"\x00")
    timings = [_timing(1, 0.0, 6.0, 6.0, str(comp / "s1.mp4"), str(comp / "s1.wav"))]
    scene_plans = [{"scene_id": 1, "narration_text": "Hello there world.", "content_type": "manim"}]

    fake = type("S", (), {"WORKSPACE_DIR": str(tmp_path)})()
    with patch.object(llm_composer, "settings", fake):
        html_path = compose_html("T", timings, {}, job_id, scene_plans)
    html = open(html_path, encoding="utf-8").read()

    # <video> and <audio> elements must not use track 0
    for tag in ("video", "audio"):
        for m in re.finditer(rf"<{tag}\b[^>]*data-track-index=\"(\d+)\"", html, re.DOTALL):
            assert int(m.group(1)) != CAPTION_TRACK_INDEX
