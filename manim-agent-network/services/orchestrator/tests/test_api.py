import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, MagicMock, AsyncMock
import os

# Set dummy env vars for test
os.environ["WORKSPACE_DIR"] = "./test_workspace"
os.environ["GEMINI_API_KEY"] = "dummy_api_key_for_testing"

from services.orchestrator.app.main import app
from shared.database.core import init_db

@pytest.fixture(autouse=True)
async def setup_db():
    await init_db()

@pytest.mark.asyncio
async def test_generate_endpoint_success():
    # Mock the ainvoke of app_graph to prevent it from actually running HTTP requests
    with patch("services.orchestrator.app.main.app_graph.ainvoke", new_callable=AsyncMock) as mock_ainvoke:
        mock_ainvoke.return_value = {
            "job_id": "dummy",
            "topic": "Test Topic",
            "status": "completed",
            "overall_error": None,
            "state": {}
        }

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.post("/generate", json={"topic": "Test Topic"})

        assert response.status_code == 200
        data = response.json()
        assert "job_id" in data
        assert data["message"] == "Generation started."

        # Check if job was created
        job_id = data["job_id"]
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
             job_res = await ac.get(f"/job/{job_id}")

        assert job_res.status_code == 200
        job_data = job_res.json()
        assert job_data["topic"] == "Test Topic"
        assert job_data["status"] in ["starting", "pending", "completed"]

@pytest.mark.asyncio
async def test_generate_endpoint_validation_error():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Missing required field 'topic'
        response = await ac.post("/generate", json={"wrong_field": "Test"})

    assert response.status_code == 422 # Unprocessable Entity
