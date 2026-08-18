"""Film QA: ffmpeg output parsing + defect-range -> scene mapping."""

import asyncio

from services.compositor.app import film_qa
from shared.schemas.common import SceneTimingRecord


def _t(sid, start, vid, aud, audio_path="a.wav"):
    return SceneTimingRecord(
        scene_id=sid, render_path="r.mp4", audio_path=audio_path,
        actual_video_duration_seconds=vid, actual_audio_duration_seconds=aud,
        start_time_seconds=start,
    )


def test_pair_closes_unclosed_range_at_duration():
    assert film_qa._pair([1.0, 8.0], [3.0], 10.0) == [(1.0, 3.0), (8.0, 10.0)]
    assert film_qa._pair([], [], 10.0) == []


def test_regexes_parse_real_ffmpeg_stderr():
    out = (
        "[blackdetect @ 0x1] black_start:3.2 black_end:6.4 black_duration:3.2\n"
        "[freezedetect @ 0x2] lavfi.freezedetect.freeze_start: 10.5\n"
        "[freezedetect @ 0x2] lavfi.freezedetect.freeze_duration: 9.0\n"
        "[freezedetect @ 0x2] lavfi.freezedetect.freeze_end: 19.5\n"
        "[silencedetect @ 0x3] silence_start: 20.1\n"
        "[silencedetect @ 0x3] silence_end: 29.8 | silence_duration: 9.7\n"
    )
    assert film_qa._RE_BLACK.findall(out) == [("3.2", "6.4")]
    assert [float(x) for x in film_qa._RE_FREEZE_START.findall(out)] == [10.5]
    assert [float(x) for x in film_qa._RE_FREEZE_END.findall(out)] == [19.5]
    assert [float(x) for x in film_qa._RE_SILENCE_START.findall(out)] == [20.1]
    assert [float(x) for x in film_qa._RE_SILENCE_END.findall(out)] == [29.8]


def test_run_film_qa_maps_ranges_to_scenes(monkeypatch):
    # Scene 1 (0-10s) fine; scene 2 (10-20s) fully black+frozen; scene 3
    # (20-30s) narrated but silent. No vision model -> deterministic critiques.
    monkeypatch.setattr(film_qa.settings, "IMAGE_EVAL_MODEL", "")
    monkeypatch.setattr(film_qa, "_detect_ranges", lambda path: {
        "black": [(10.0, 20.0)],
        "freeze": [(10.0, 20.0)],
        "silence": [(20.0, 30.0)],
        "has_audio": True,
        "duration": 30.0,
    })
    timings = [_t(1, 0.0, 10, 10), _t(2, 10.0, 10, 10), _t(3, 20.0, 10, 10)]
    plans = [{"scene_id": i, "narration_text": "n", "visual_description": "v"}
             for i in (1, 2, 3)]
    flagged, film_issues = asyncio.run(film_qa.run_film_qa("f.mp4", timings, plans))
    assert sorted(flagged) == [2, 3]
    assert "black" in flagged[2] and "static" in flagged[2]
    assert "inaudible" in flagged[3]
    assert film_issues == []


def test_run_film_qa_flags_missing_audio_stream_as_film_issue(monkeypatch):
    monkeypatch.setattr(film_qa.settings, "IMAGE_EVAL_MODEL", "")
    monkeypatch.setattr(film_qa, "_detect_ranges", lambda path: {
        "black": [], "freeze": [], "silence": [],
        "has_audio": False, "duration": 10.0,
    })
    flagged, film_issues = asyncio.run(
        film_qa.run_film_qa("f.mp4", [_t(1, 0.0, 10, 10)], []))
    assert flagged == {}
    assert len(film_issues) == 1 and "NO audio stream" in film_issues[0]


def test_run_film_qa_never_raises_on_scan_failure(monkeypatch):
    def _boom(path):
        raise RuntimeError("ffmpeg exploded")
    monkeypatch.setattr(film_qa, "_detect_ranges", _boom)
    flagged, film_issues = asyncio.run(
        film_qa.run_film_qa("f.mp4", [_t(1, 0.0, 10, 10)], []))
    assert flagged == {} and film_issues == []
