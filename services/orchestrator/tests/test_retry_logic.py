import pytest
import asyncio
from services.shared.models import PipelineState, SceneData
from services.orchestrator.main import node_validate, node_generate_code, SERVICES
import httpx

@pytest.mark.asyncio
async def test_retry_logic_hard_limit(respx_mock):
    # Setup state with a scene that has already failed 3 times
    scene = SceneData(
        scene_id="scene_retry",
        description="test",
        narration="test",
        script_path="/app/workspace/tests/scene_retry/scene.py",
        status="validation_failed",
        retry_count=3,
        errors=["failed 1", "failed 2", "failed 3"]
    )

    state = PipelineState(
        user_prompt="test",
        scenes=[scene],
        status="validation_failed"
    )

    # We test the routing function
    from services.orchestrator.main import route_after_validate
    from langgraph.graph import END

    # After validate, if a scene is validation_failed and retry_count >= 3, it should route to END
    route = route_after_validate(state)
    assert route == END
    assert "Max retries exceeded" in state.global_errors[-1]

@pytest.mark.asyncio
async def test_retry_logic_increment(respx_mock):
    scene = SceneData(
        scene_id="scene_retry",
        description="test",
        narration="test",
        script_path="/app/workspace/tests/scene_retry/scene.py",
        status="code_generated",
        retry_count=0
    )

    state = PipelineState(
        user_prompt="test",
        scenes=[scene],
        status="code_generation_complete"
    )

    # Mock the validator to fail
    respx_mock.post(f"{SERVICES['validator']}/validate_code").mock(
        return_value=httpx.Response(200, json={"success": False, "error_log": "SyntaxError", "video_path": None})
    )

    new_state = await node_validate(state)

    assert new_state.status == "validation_failed"
    assert new_state.scenes[0].status == "validation_failed"
    assert new_state.scenes[0].retry_count == 1
    assert "SyntaxError" in new_state.scenes[0].errors[-1]

    # Test routing logic
    from services.orchestrator.main import route_after_validate
    route = route_after_validate(new_state)
    assert route == "generate_code" # Self-healing loop
