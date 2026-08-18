"""Regression for F45: rounding drift used to make the FINAL caption window
negative, silently dropping the last caption of a scene. It must now clamp to
a minimal positive duration instead of vanishing."""

import importlib
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_COMP = os.path.join(PROJECT_ROOT, "services", "compositor")
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def _load_composer():
    saved = {k: sys.modules[k] for k in list(sys.modules) if k == "app" or k.startswith("app.")}
    for k in saved:
        del sys.modules[k]
    sys.path.insert(0, _COMP)
    try:
        return importlib.import_module("app.llm_composer")
    finally:
        sys.path.remove(_COMP)
        for k in [k for k in sys.modules if k == "app" or k.startswith("app.")]:
            del sys.modules[k]
        sys.modules.update(saved)


composer = _load_composer()


def test_windows_chain_exactly():
    out = composer.allocate_caption_windows(
        ["one two three", "four five", "six"], audio_duration=6.0, slot=6.0,
        scene_start=10.0)
    assert len(out) == 3
    for (s1, d1, _), (s2, _, _) in zip(out, out[1:]):
        assert round(s1 + d1, 3) == s2
    # last window ends exactly at scene_start + audio_duration
    s, d, _ = out[-1]
    assert round(s + d, 3) == 16.0


def test_final_window_never_dropped_on_drift():
    # Many similar-weight chunks force per-chunk rounding; the last chunk's
    # remainder can round to <= 0. It must be emitted with a positive duration.
    chunks = [f"word{i}" for i in range(7)]
    out = composer.allocate_caption_windows(chunks, audio_duration=0.02,
                                            slot=0.02, scene_start=0.0)
    assert len(out) >= 1
    assert all(d > 0 for _, d, _ in out)
    # the final chunk's text is present — not silently vanished
    assert out[-1][2] == chunks[len(out) - 1]
