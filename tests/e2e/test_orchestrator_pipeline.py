import pytest
import asyncio
from services.orchestrator.main import workflow
from services.shared.models import PipelineState
import httpx
from unittest.mock import AsyncMock

@pytest.fixture
def mock_all_services(respx_mock):
    # Mock script_writer
    respx_mock.post("http://script_writer:8001/generate_script").mock(
        return_value=httpx.Response(200, json={
            "scenes": [
                {"scene_id": "scene_1", "description": "desc 1", "narration": "nar 1"}
            ]
        })
    )

    # Mock manim_generator
    respx_mock.post("http://manim_generator:8002/generate_code").mock(
        return_value=httpx.Response(200, json={
            "script_path": "/app/workspace/tests/scene_1/scene.py"
        })
    )

    # Mock validator
    respx_mock.post("http://validator:8003/validate_code").mock(
        return_value=httpx.Response(200, json={
            "success": True,
            "video_path": "/app/workspace/tests/scene_1/media/videos/scene/720p30/output.mp4"
        })
    )

    # Mock voiceover
    respx_mock.post("http://voiceover:8004/generate_audio").mock(
        return_value=httpx.Response(200, json={
            "audio_path": "/app/workspace/tests/scene_1/voiceover.mp3"
        })
    )

    # Mock assembler
    respx_mock.post("http://assembler:8005/assemble").mock(
        return_value=httpx.Response(200, json={
            "final_video_path": "/app/workspace/tests/final_output.mp4"
        })
    )

    # Mock quality_review
    respx_mock.post("http://quality_review:8006/review").mock(
        return_value=httpx.Response(200, json={
            "is_valid": True,
            "duration": 5.0,
            "issues": []
        })
    )

@pytest.mark.asyncio
async def test_end_to_end_pipeline(mock_all_services, mocker):
    # We mock the postgres checkpointer to just use in-memory for testing the core logic
    initial_state = PipelineState(user_prompt="Explain limits")

    # We use the uncompiled graph or a memory checkpointer
    app = workflow.compile()

    final_state = await app.ainvoke(initial_state)

    assert final_state["status"] == "completed"
    assert len(final_state["scenes"]) == 1
    assert final_state["scenes"][0].status == "validated"
    assert final_state["final_video_path"] == "/app/workspace/tests/final_output.mp4"
    assert len(final_state["global_errors"]) == 0
