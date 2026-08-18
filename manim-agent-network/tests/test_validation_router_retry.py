"""Table-driven tests for the pipeline's control plane: validation_router +
_scene_retryable. These branches route every scene retry/degrade/fail decision
and were previously untested (audit F130/F104/F270)."""

import importlib
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_ORCH = os.path.join(PROJECT_ROOT, "services", "orchestrator")
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def _load_graph():
    saved = {k: sys.modules[k] for k in list(sys.modules) if k == "app" or k.startswith("app.")}
    for k in saved:
        del sys.modules[k]
    sys.path.insert(0, _ORCH)
    try:
        return importlib.import_module("app.core.graph")
    finally:
        sys.path.remove(_ORCH)
        for k in [k for k in sys.modules if k == "app" or k.startswith("app.")]:
            del sys.modules[k]
        sys.modules.update(saved)


graph = _load_graph()
from shared.config import settings  # noqa: E402


def _state(**over):
    base = {
        "job_id": "j", "topic": "t", "status": "validation",
        "script": {"title": "T", "scenes": [
            {"scene_id": 1, "narration_text": "a", "visual_description": "v",
             "estimated_duration_seconds": 5, "content_type": "manim"},
            {"scene_id": 2, "narration_text": "b", "visual_description": "v",
             "estimated_duration_seconds": 5, "content_type": "hyperframes"},
        ]},
        "render_paths": {}, "retry_counts": {}, "infra_retry_counts": {},
        "error_logs": {}, "overall_error": None,
    }
    base.update(over)
    return base


def test_all_rendered_routes_to_assembler():
    s = _state(render_paths={1: "/a.mp4", 2: "/b.html"})
    assert graph.validation_router(s) == "assembler_node"


def test_missing_scene_with_budget_routes_to_codegen():
    s = _state(render_paths={1: "/a.mp4"})
    assert graph.validation_router(s) == "code_generator_node"


def test_exhausted_content_budget_with_partial_renders_degrades_to_assembler():
    s = _state(render_paths={1: "/a.mp4"},
               retry_counts={2: settings.MAX_SCENE_RETRIES})
    assert graph.validation_router(s) == "assembler_node"


def test_exhausted_budget_with_nothing_rendered_fails():
    s = _state(retry_counts={1: settings.MAX_SCENE_RETRIES,
                             2: settings.MAX_SCENE_RETRIES})
    assert graph.validation_router(s) == "failed"


def test_exhausted_infra_budget_is_not_retryable():
    s = _state(render_paths={1: "/a.mp4"},
               infra_retry_counts={2: settings.MAX_INFRA_RETRIES})
    # infra budget spent, content budget untouched -> scene is NOT retryable,
    # and with one scene rendered the job degrades instead of looping forever.
    assert not graph._scene_retryable(s, 2)
    assert graph.validation_router(s) == "assembler_node"


def test_overall_error_routes_to_failed():
    s = _state(overall_error="boom")
    assert graph.validation_router(s) == "failed"


def test_missing_script_routes_to_failed_not_typeerror():
    s = _state(script=None)
    assert graph.validation_router(s) == "failed"
    s2 = _state(script={"title": "T", "scenes": []})
    assert graph.validation_router(s2) == "failed"


def test_scene_retryable_predicate_matches_both_budgets():
    s = _state()
    assert graph._scene_retryable(s, 1)
    s = _state(retry_counts={1: settings.MAX_SCENE_RETRIES})
    assert not graph._scene_retryable(s, 1)
    s = _state(infra_retry_counts={1: settings.MAX_INFRA_RETRIES})
    assert not graph._scene_retryable(s, 1)
    s = _state(retry_counts={1: settings.MAX_SCENE_RETRIES - 1},
               infra_retry_counts={1: settings.MAX_INFRA_RETRIES - 1})
    assert graph._scene_retryable(s, 1)
