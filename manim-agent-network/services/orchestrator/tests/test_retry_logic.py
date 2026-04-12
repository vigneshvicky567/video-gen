import pytest
from services.orchestrator.app.core.graph import validator_node
from shared.models.agent_state import LangGraphState
from unittest.mock import patch, AsyncMock
import os

# Set dummy env vars for test
os.environ["WORKSPACE_DIR"] = "./test_workspace"
os.environ["GEMINI_API_KEY"] = "dummy_api_key_for_testing"

@pytest.mark.asyncio
async def test_validator_node_failure_increments_retry():
    state: LangGraphState = {
        "job_id": "test_job",
        "topic": "test",
        "status": "code_generation",
        "script": None,
        "code_paths": {1: "/path/to/code.py"},
        "render_paths": {},
        "audio_paths": {},
        "retry_counts": {1: 1}, # Initially 1 retry
        "error_logs": {},
        "previous_code_paths": {},
        "final_output_path": None,
        "overall_error": None
    }

    # Mock the _post call to simulate a validation failure from the validator service
    with patch("services.orchestrator.app.core.graph._post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = {
            "success": False,
            "scene_id": 1,
            "error_log": "SyntaxError: invalid syntax",
            "render_path": None
        }

        new_state = await validator_node(state)

        # Verify state updates
        assert new_state["status"] == "validation"
        assert new_state["retry_counts"][1] == 2 # Incremented
        assert new_state["error_logs"][1] == "SyntaxError: invalid syntax"
        assert 1 not in new_state["render_paths"]
