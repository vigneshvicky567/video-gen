import pytest
from fastapi.testclient import TestClient
from services.validator.main import app
import os
import shutil

client = TestClient(app)
WORKSPACE_DIR = "/app/workspace/tests"

@pytest.fixture(autouse=True)
def override_workspace():
    # We patch WORKSPACE_DIR in main
    import services.validator.main as main
    original_workspace = main.WORKSPACE_DIR
    main.WORKSPACE_DIR = WORKSPACE_DIR
    yield
    main.WORKSPACE_DIR = original_workspace

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_validate_code_missing_script():
    payload = {
        "scene_id": "scene_test",
        "script_path": f"{WORKSPACE_DIR}/nonexistent.py"
    }
    response = client.post("/validate_code", json=payload)
    assert response.status_code == 200 # App handles this gracefully
    data = response.json()
    assert data["success"] is False
    assert "Script file not found" in data["error_log"]

def test_validate_code_success(mock_subprocess):
    # Setup dummy script
    scene_id = "scene_1"
    scene_dir = os.path.join(WORKSPACE_DIR, scene_id)
    os.makedirs(scene_dir, exist_ok=True)
    script_path = os.path.join(scene_dir, "scene.py")
    with open(script_path, "w") as f:
        f.write("dummy code")

    payload = {
        "scene_id": scene_id,
        "script_path": script_path
    }

    # client.post runs synchronously, which doesn't mix well with our async mock in a weird event loop.
    # To fix this, we import the actual async function and run it directly
    from services.validator.main import validate_code
    from services.shared.models import ValidationRequest
    import asyncio

    request = ValidationRequest(**payload)
    result = asyncio.run(validate_code(request))

    assert result.success is True
    assert "output.mp4" in result.video_path
    assert os.path.exists(result.video_path)
