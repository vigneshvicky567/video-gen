import pytest
import os
import shutil
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock

# Mock env before config
os.environ["WORKSPACE_DIR"] = "./test_workspace"
os.environ["GEMINI_API_KEY"] = "dummy_api_key_for_testing"
from shared.config import settings
settings.WORKSPACE_DIR = "./test_workspace"
settings.GEMINI_API_KEY = "dummy_api_key_for_testing"

@pytest.fixture(scope="session", autouse=True)
def setup_workspace():
    # Ensure test workspace exists
    os.makedirs(settings.WORKSPACE_DIR, exist_ok=True)
    yield
    # Cleanup after session
    shutil.rmtree(settings.WORKSPACE_DIR, ignore_errors=True)

@pytest.fixture(autouse=True)
def mock_gemini():
    with patch("google.genai.Client") as MockClient:
        mock_client_instance = MockClient.return_value
        mock_response = MagicMock()

        # Mock parsed response assuming it's for code generation
        class MockParsed:
            python_code = "from manim import *\nclass Scene1(Scene):\n    def construct(self):\n        pass"
        mock_response.parsed = MockParsed()
        mock_response.text = '{"python_code": "from manim import *\\nclass Scene1(Scene):\\n    def construct(self):\\n        pass"}'

        mock_client_instance.models.generate_content.return_value = mock_response
        yield mock_client_instance

@pytest.fixture(autouse=True)
def mock_subprocess_exec():
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
