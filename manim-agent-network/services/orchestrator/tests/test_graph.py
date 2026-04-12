import pytest
from services.orchestrator.app.core.graph import validation_router
from shared.models.agent_state import LangGraphState

def test_validation_router_success():
    state = {
        "script": {"scenes": [{"scene_id": 1}]},
        "render_paths": {1: "/path/to/video.mp4"},
        "retry_counts": {},
        "overall_error": None
    }

    result = validation_router(state)
    assert result == "voiceover_node"

def test_validation_router_needs_retry():
    state = {
        "script": {"scenes": [{"scene_id": 1}, {"scene_id": 2}]},
        "render_paths": {1: "/path/to/video1.mp4"}, # Scene 2 failed/missing
        "retry_counts": {2: 1}, # Retried once
        "overall_error": None
    }

    result = validation_router(state)
    assert result == "code_generator_node"

def test_validation_router_max_retries_reached():
    state = {
        "script": {"scenes": [{"scene_id": 1}]},
        "render_paths": {}, # Scene 1 failed
        "retry_counts": {1: 3}, # Reached max retries
        "overall_error": None
    }

    result = validation_router(state)
    assert result == "failed"

def test_validation_router_overall_error():
    state = {
        "script": {"scenes": [{"scene_id": 1}]},
        "render_paths": {},
        "retry_counts": {},
        "overall_error": "Some critical API failure"
    }

    result = validation_router(state)
    assert result == "failed"
