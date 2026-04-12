import pytest
import os
import json
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, MagicMock

# Mock env before config
os.environ["WORKSPACE_DIR"] = "./test_workspace"
os.environ["GEMINI_API_KEY"] = "dummy_api_key_for_testing"

# Apply mocking to the genai client instantiation before importing app
with patch('google.genai.Client') as mock_client_class:
    mock_instance = MagicMock()

    # Mock the response
    class MockParsed:
        python_code = "from manim import *\nclass Scene1(Scene):\n    def construct(self):\n        pass"

    mock_response = MagicMock()
    mock_response.parsed = MockParsed()
    mock_response.text = '{"python_code": "from manim import *\\nclass Scene1(Scene):\\n    def construct(self):\\n        pass"}'

    mock_instance.models.generate_content.return_value = mock_response
    mock_client_class.return_value = mock_instance

    from services.code_generator.app.main import app, get_client

    # Also patch get_client directly
    app.dependency_overrides[get_client] = lambda: mock_instance


@pytest.fixture(autouse=True)
def mock_genai_get_client():
    with patch('services.code_generator.app.main.get_client') as mock_get:
        mock_instance = MagicMock()

        class MockParsed:
            python_code = "from manim import *\nclass Scene1(Scene):\n    def construct(self):\n        pass"

        mock_response = MagicMock()
        mock_response.parsed = MockParsed()
        mock_response.text = '{"python_code": "from manim import *\\nclass Scene1(Scene):\\n    def construct(self):\\n        pass"}'

        mock_instance.models.generate_content.return_value = mock_response
        mock_get.return_value = mock_instance
        yield mock_get


@pytest.mark.asyncio
async def test_generate_code_endpoint_success():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        req_data = {
            "job_id": "job_abc",
            "scene": {
                "scene_id": 1,
                "narration_text": "Hello world",
                "visual_description": "A circle",
                "estimated_duration_seconds": 5
            }
        }
        response = await ac.post("/generate", json=req_data)

    assert response.status_code == 200
    data = response.json()
    assert data["scene_id"] == 1
    assert "code_path" in data
    assert os.path.exists(data["code_path"])

@pytest.mark.asyncio
async def test_generate_code_endpoint_retry():
    # Create a dummy previous code file
    temp_dir = os.path.join("./test_workspace", "temp", "job_retry")
    os.makedirs(temp_dir, exist_ok=True)
    prev_path = os.path.join(temp_dir, "prev_scene.py")
    with open(prev_path, "w") as f:
        f.write("bad code")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        req_data = {
            "job_id": "job_retry",
            "scene": {
                "scene_id": 1,
                "narration_text": "Hello world",
                "visual_description": "A circle",
                "estimated_duration_seconds": 5
            },
            "error_log": "Syntax error",
            "previous_code_path": prev_path
        }
        response = await ac.post("/generate", json=req_data)

    assert response.status_code == 200
    data = response.json()
    assert data["scene_id"] == 1
    assert "code_path" in data
