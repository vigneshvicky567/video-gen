"""Tests for the script council's pure logic: duration-budget math and the
scene-invariant enforcer (services/script-writer/app/{budget,council}.py).

The script-writer dir is hyphenated and exposes a package named `app` that
collides with other services' `app`. Load it under a unique name (`sw_app`) so
its relative imports resolve without polluting sys.modules['app'].
"""

import importlib
import importlib.util
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def _load_sw():
    if "sw_app" not in sys.modules:
        app_dir = os.path.join(PROJECT_ROOT, "services", "script-writer", "app")
        spec = importlib.util.spec_from_file_location(
            "sw_app", os.path.join(app_dir, "__init__.py"),
            submodule_search_locations=[app_dir],
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules["sw_app"] = mod
        spec.loader.exec_module(mod)
    return (
        importlib.import_module("sw_app.budget"),
        importlib.import_module("sw_app.council"),
    )


budget, council = _load_sw()
_renumber_and_enforce_invariants = council._renumber_and_enforce_invariants


def _scenes(n, est, words, ctype="manim"):
    return [
        {"scene_id": i, "content_type": ctype, "visual_description": "x",
         "narration_text": "word " * words, "estimated_duration_seconds": est}
        for i in range(1, n + 1)
    ]


def test_audit_on_budget():
    # 10 scenes, est 30s, 66 words (66/2.2 = 30) -> slot 30 -> total 300
    a = budget.audit(_scenes(10, 30, 66), 300)
    assert a["estimated_seconds"] == 300.0
    assert a["within_tolerance"] is True
    assert a["deviation_pct"] == 0.0


def test_audit_off_budget():
    a = budget.audit(_scenes(10, 30, 66), 600)
    assert a["within_tolerance"] is False
    assert abs(a["deviation_pct"] + 50.0) < 0.1   # -50%


def test_repair_budgets_sum_near_target():
    rb = budget.repair_budgets(_scenes(10, 30, 66), 600)
    # ONE currency now: target_words. Reconstruct seconds via WPS and check it lands near target.
    total_s = sum(b["target_words"] for b in rb) / budget.WPS
    assert abs(total_s - 600) <= 12                 # rounding tolerance
    assert all(b["target_words"] >= 8 for b in rb)  # per-scene floor


def test_clamp_durations_respects_narration():
    sc = _scenes(1, 5, 44, ctype="hyperframes")    # 44 words -> 20s of speech
    budget.clamp_durations(sc)
    assert sc[0]["estimated_duration_seconds"] == 20


def test_renumber_contiguous_and_endpoints():
    raw = [
        {"content_type": "manim", "narration_text": "a", "visual_description": "x", "estimated_duration_seconds": 5},
        {"content_type": "manim", "narration_text": "", "visual_description": "x", "estimated_duration_seconds": 5},  # dropped
        {"content_type": "manim", "narration_text": "b", "visual_description": "x", "estimated_duration_seconds": 5},
    ]
    out = _renumber_and_enforce_invariants(raw)
    assert [s["scene_id"] for s in out] == [1, 2]
    assert out[0]["content_type"] == "hyperframes"
    assert out[-1]["content_type"] == "hyperframes"


def test_renumber_caps_scene_count(monkeypatch):
    monkeypatch.setattr(council.settings, "SCRIPT_MAX_SCENES", 5)
    out = _renumber_and_enforce_invariants(_scenes(20, 10, 10))
    assert len(out) <= 5
    assert [s["scene_id"] for s in out] == list(range(1, len(out) + 1))


def test_renumber_defaults_bad_content_type():
    raw = [{"content_type": "weird", "narration_text": "hi", "visual_description": "x", "estimated_duration_seconds": 4}]
    out = _renumber_and_enforce_invariants(raw)
    assert out[0]["content_type"] == "hyperframes"
    assert out[0]["estimated_duration_seconds"] >= 3
