import pytest
import os
import shutil
import asyncio

WORKSPACE_DIR = "/app/workspace/tests"

@pytest.fixture(autouse=True)
def setup_test_workspace():
    # Setup isolated workspace for tests
    os.makedirs(WORKSPACE_DIR, exist_ok=True)
    yield
    # Cleanup after tests
    if os.path.exists(WORKSPACE_DIR):
        shutil.rmtree(WORKSPACE_DIR)

@pytest.fixture
def mock_gemini(mocker):
    # Mock google-generativeai responses
    mock_model = mocker.patch('google.generativeai.GenerativeModel')
    mock_instance = mock_model.return_value

    # Setup default mock response
    mock_response = mocker.MagicMock()
    mock_response.text = '{"scenes": [{"scene_id": "scene_1", "description": "Test", "narration": "Test"}]}'
    mock_instance.generate_content.return_value = mock_response

    return mock_instance

@pytest.fixture
def mock_subprocess(mocker):
    # Mock asyncio.create_subprocess_exec to write dummy files
    async def mock_create_subprocess_exec(*args, **kwargs):
        process = mocker.MagicMock()
        process.returncode = 0

        async def communicate():
            # Extract output path from args
            output_path = None
            if "manim" in args:
                try:
                    idx = args.index("-o")
                    filename = args[idx+1]
                    media_dir_idx = args.index("--media_dir")
                    media_dir = args[media_dir_idx+1]
                    # Structure is media/videos/scene/720p30/output.mp4
                    output_path = os.path.join(media_dir, "videos", "scene", "720p30", filename)
                except ValueError:
                    pass
            elif "ffmpeg" in args:
                output_path = args[-1]

            if output_path:
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                with open(output_path, "w") as f:
                    f.write("dummy video data")

            return b"dummy stdout", b"dummy stderr"

        process.communicate = communicate
        return process

    return mocker.patch('asyncio.create_subprocess_exec', new=mock_create_subprocess_exec)
