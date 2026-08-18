"""Tests for the topic-analysis normalizer (services/script-writer/app/analyzer.py).

Never trusts LLM numbers: clamps durations, sanitizes presets, guarantees a
duration question and 3-5 total questions, and provides a degraded fallback.

Loaded under a unique package name (`sw_app`) to avoid the bare-`app` collision.
"""

import importlib
import importlib.util
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def _load_analyzer():
    if "sw_app" not in sys.modules:
        app_dir = os.path.join(PROJECT_ROOT, "services", "script-writer", "app")
        spec = importlib.util.spec_from_file_location(
            "sw_app", os.path.join(app_dir, "__init__.py"),
            submodule_search_locations=[app_dir],
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules["sw_app"] = mod
        spec.loader.exec_module(mod)
    return importlib.import_module("sw_app.analyzer")


analyzer = _load_analyzer()
normalize_analysis = analyzer.normalize_analysis
default_analysis = analyzer.default_analysis


def test_clamps_garbage_numbers_and_synthesizes_duration_question():
    raw = {
        "recommended_duration_seconds": 5000,   # above max recommended (1800)
        "max_duration_seconds": 100,            # below recommended -> coerced up
        "duration_presets": ["x", 99999, 60, 300],  # junk + out-of-range
        "is_study_material": True,
        "questions": [
            {"id": "audience", "question": "Who?", "header": "Aud",
             "options": [{"label": "A", "description": "a"}, {"label": "B", "description": "b"}]},
        ],
    }
    t = normalize_analysis(raw, "Learn Django")
    assert 120 <= t.recommended_duration_seconds <= 1800
    assert t.max_duration_seconds >= t.recommended_duration_seconds
    assert all(120 <= p <= t.max_duration_seconds for p in t.duration_presets)
    assert t.questions[0].id == "duration"        # synthesized + moved to front
    assert 3 <= len(t.questions) <= 5             # padded to >= 3
    assert t.degraded is False


def test_existing_duration_question_rebuilt_from_presets():
    raw = {
        "recommended_duration_seconds": 300,
        "max_duration_seconds": 1200,
        "duration_presets": [180, 300, 600],
        "questions": [
            {"id": "duration", "question": "len?", "header": "Len",
             "options": [{"label": "bogus", "description": ""}]},
            {"id": "style", "question": "style?", "header": "Style",
             "options": [{"label": "X", "description": "x"}, {"label": "Y", "description": "y"}]},
        ],
    }
    t = normalize_analysis(raw, "topic")
    dur = next(q for q in t.questions if q.id == "duration")
    labels = [o.label for o in dur.options]
    assert any("min" in l for l in labels)        # rebuilt from presets, not 'bogus'


def test_caps_questions_to_five():
    raw = {
        "recommended_duration_seconds": 300, "max_duration_seconds": 600,
        "duration_presets": [180, 300, 600],
        "questions": [
            {"id": f"q{i}", "question": f"q{i}?", "header": f"H{i}",
             "options": [{"label": "A", "description": ""}, {"label": "B", "description": ""}]}
            for i in range(8)
        ],
    }
    t = normalize_analysis(raw, "topic")
    assert len(t.questions) == 5


def test_default_analysis_is_degraded_and_usable():
    d = default_analysis("anything")
    assert d.degraded is True
    assert 3 <= len(d.questions) <= 5
    assert d.questions[0].id == "duration"
    assert d.recommended_duration_seconds <= d.max_duration_seconds
