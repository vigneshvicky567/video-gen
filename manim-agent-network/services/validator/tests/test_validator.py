import pytest
import os
import shutil
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock

# Mock env before config
os.environ["WORKSPACE_DIR"] = "./test_workspace"
from shared.config import settings
settings.WORKSPACE_DIR = "./test_workspace"

from services.validator.app.main import app

@pytest.fixture(autouse=True)
def mock_subprocess_exec_validator():
    # Deep patch asyncio.create_subprocess_exec
    async def fake_create_subprocess_exec(*args, **kwargs):
        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate.return_value = (b"stdout dummy", b"stderr dummy")

        # Determine if it's the manim render command
        if args and args[0] == "manim" and "render" in args:
            # Extract output dir and scene name to touch a fake file
            media_dir_idx = args.index("--media_dir") + 1
            output_dir = args[media_dir_idx]
            scene_name = args[-1]

            # Recreate expected structure: output_dir/videos/filename/1080p60/SceneName.mp4
            # the validator uses glob: output_dir/videos/*/*/SceneName.mp4
            fake_video_dir = os.path.join(output_dir, "videos", "fake_file", "1080p60")
            os.makedirs(fake_video_dir, exist_ok=True)
            fake_video_path = os.path.join(fake_video_dir, f"{scene_name}.mp4")
            with open(fake_video_path, "w") as f:
                f.write("dummy video data")

        return mock_process

    with patch("asyncio.create_subprocess_exec", side_effect=fake_create_subprocess_exec) as m:
        yield m

@pytest.mark.asyncio
async def test_validator_endpoint_success():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        req_data = {
            "job_id": "job_123",
            "scene_id": 1,
            "code_path": "/workspace/dummy.py"
        }
        response = await ac.post("/validate", json=req_data)

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["scene_id"] == 1
    assert "render_path" in data
    assert data["render_path"].endswith("Scene1.mp4")

@pytest.mark.asyncio
async def test_validator_endpoint_timeout():
    # Deep patch to simulate timeout
    import asyncio
    async def fake_create_subprocess_exec_timeout(*args, **kwargs):
        mock_process = AsyncMock()
        mock_process.communicate.side_effect = asyncio.TimeoutError
        return mock_process

    with patch("asyncio.create_subprocess_exec", side_effect=fake_create_subprocess_exec_timeout):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            req_data = {
                "job_id": "job_123",
                "scene_id": 1,
                "code_path": "/workspace/dummy.py"
            }
            response = await ac.post("/validate", json=req_data)

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "timed out" in data["error_log"]
