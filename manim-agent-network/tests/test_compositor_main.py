"""Unit tests for compositor main FastAPI application."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

from fastapi.testclient import TestClient

from services.compositor.app.main import app
from services.compositor.app.duration_prober import AssemblyError
from shared.schemas.common import ScenePlan, SceneTimingRecord


client = TestClient(app)


def test_health_endpoint():
    """Test health check endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "service": "compositor"}


@patch("services.compositor.app.main.run_proc")
@patch("services.compositor.app.main.validate_composition")
@patch("services.compositor.app.main.compose_html")
@patch("services.compositor.app.main.compute_scene_timings")
def test_assemble_success(
    mock_compute_timings,
    mock_compose_html,
    mock_validate,
    mock_subprocess,
    tmp_path
):
    """Test successful assembly pipeline."""
    # Mock compute_scene_timings
    mock_compute_timings.return_value = [
        SceneTimingRecord(
            scene_id=1,
            render_path="/workspace/temp/job1/renders/scene_1.mp4",
            audio_path="/workspace/temp/job1/audio/scene_1.wav",
            actual_video_duration_seconds=5.0,
            actual_audio_duration_seconds=5.0,
            start_time_seconds=0.0,
        ),
    ]
    
    # Mock compose_html
    html_path = str(tmp_path / "composition.html")
    mock_compose_html.return_value = html_path
    
    # Mock validate_composition (no-op)
    mock_validate.return_value = None
    
    # Mock subprocess.run (hyperframes render)
    mock_result = Mock()
    mock_result.returncode = 0
    mock_result.stdout = "Render successful"
    mock_result.stderr = ""
    mock_subprocess.return_value = mock_result
    
    # Create output file
    output_path = tmp_path / "outputs" / "job1_final.mp4"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(b"fake video data")
    
    # Prepare request
    request_data = {
        "job_id": "job1",
        "render_paths": {1: "/workspace/temp/job1/renders/scene_1.mp4"},
        "audio_paths": {1: "/workspace/temp/job1/audio/scene_1.wav"},
        "scene_plans": [
            {
                "scene_id": 1,
                "narration_text": "Test narration",
                "visual_description": "Test visual",
                "estimated_duration_seconds": 5,
            }
        ],
        "image_paths": {1: ["/workspace/temp/job1/images/scene_1/img_0.jpg"]},
        "script_title": "Test Video",
    }
    
    with patch("services.compositor.app.main.settings") as mock_settings:
        mock_settings.WORKSPACE_DIR = str(tmp_path)
        mock_settings.COMPOSITOR_CHUNK_THRESHOLD_SECONDS = 480  # single-render branch
        
        response = client.post("/assemble", json=request_data)
    
    assert response.status_code == 200
    result = response.json()
    assert "final_output_path" in result
    assert str(tmp_path / "outputs" / "job1_final.mp4") in result["final_output_path"]


@patch("services.compositor.app.main.compute_scene_timings")
def test_assemble_duration_probe_failure(mock_compute_timings):
    """Test assembly fails when duration probing fails."""
    # Mock compute_scene_timings to raise AssemblyError
    mock_compute_timings.side_effect = AssemblyError("ffprobe failed for /path/to/file")
    
    request_data = {
        "job_id": "job1",
        "render_paths": {1: "/workspace/temp/job1/renders/scene_1.mp4"},
        "audio_paths": {1: "/workspace/temp/job1/audio/scene_1.wav"},
        "scene_plans": [
            {
                "scene_id": 1,
                "narration_text": "Test narration",
                "visual_description": "Test visual",
                "estimated_duration_seconds": 5,
            }
        ],
        "image_paths": {},
        "script_title": "Test Video",
    }
    
    response = client.post("/assemble", json=request_data)
    
    assert response.status_code == 500
    assert "ffprobe failed" in response.json()["detail"]


@patch("services.compositor.app.main.run_proc")
@patch("services.compositor.app.main.validate_composition")
@patch("services.compositor.app.main.compose_html")
@patch("services.compositor.app.main.compute_scene_timings")
def test_assemble_hyperframes_render_failure(
    mock_compute_timings,
    mock_compose_html,
    mock_validate,
    mock_subprocess,
    tmp_path
):
    """Test assembly fails when HyperFrames render fails."""
    # Mock compute_scene_timings
    mock_compute_timings.return_value = [
        SceneTimingRecord(
            scene_id=1,
            render_path="/workspace/temp/job1/renders/scene_1.mp4",
            audio_path="/workspace/temp/job1/audio/scene_1.wav",
            actual_video_duration_seconds=5.0,
            actual_audio_duration_seconds=5.0,
            start_time_seconds=0.0,
        ),
    ]
    
    # Mock compose_html
    html_path = str(tmp_path / "composition.html")
    mock_compose_html.return_value = html_path
    
    # Mock validate_composition
    mock_validate.return_value = None
    
    # Mock subprocess.run to return non-zero exit code
    mock_result = Mock()
    mock_result.returncode = 1
    mock_result.stdout = "Render output"
    mock_result.stderr = "Render error"
    mock_subprocess.return_value = mock_result
    
    request_data = {
        "job_id": "job1",
        "render_paths": {1: "/workspace/temp/job1/renders/scene_1.mp4"},
        "audio_paths": {1: "/workspace/temp/job1/audio/scene_1.wav"},
        "scene_plans": [
            {
                "scene_id": 1,
                "narration_text": "Test narration",
                "visual_description": "Test visual",
                "estimated_duration_seconds": 5,
            }
        ],
        "image_paths": {},
        "script_title": "Test Video",
    }
    
    with patch("services.compositor.app.main.settings") as mock_settings:
        mock_settings.WORKSPACE_DIR = str(tmp_path)
        mock_settings.COMPOSITOR_CHUNK_THRESHOLD_SECONDS = 480  # single-render branch
        
        response = client.post("/assemble", json=request_data)
    
    assert response.status_code == 500
    assert "HyperFrames render failed" in response.json()["detail"]


@patch("services.compositor.app.main.run_proc")
@patch("services.compositor.app.main.validate_composition")
@patch("services.compositor.app.main.compose_html")
@patch("services.compositor.app.main.compute_scene_timings")
def test_assemble_output_file_missing(
    mock_compute_timings,
    mock_compose_html,
    mock_validate,
    mock_subprocess,
    tmp_path
):
    """Test assembly fails when output file doesn't exist after render."""
    # Mock compute_scene_timings
    mock_compute_timings.return_value = [
        SceneTimingRecord(
            scene_id=1,
            render_path="/workspace/temp/job1/renders/scene_1.mp4",
            audio_path="/workspace/temp/job1/audio/scene_1.wav",
            actual_video_duration_seconds=5.0,
            actual_audio_duration_seconds=5.0,
            start_time_seconds=0.0,
        ),
    ]
    
    # Mock compose_html
    html_path = str(tmp_path / "composition.html")
    mock_compose_html.return_value = html_path
    
    # Mock validate_composition
    mock_validate.return_value = None
    
    # Mock subprocess.run (successful)
    mock_result = Mock()
    mock_result.returncode = 0
    mock_result.stdout = "Render successful"
    mock_result.stderr = ""
    mock_subprocess.return_value = mock_result
    
    request_data = {
        "job_id": "job1",
        "render_paths": {1: "/workspace/temp/job1/renders/scene_1.mp4"},
        "audio_paths": {1: "/workspace/temp/job1/audio/scene_1.wav"},
        "scene_plans": [
            {
                "scene_id": 1,
                "narration_text": "Test narration",
                "visual_description": "Test visual",
                "estimated_duration_seconds": 5,
            }
        ],
        "image_paths": {},
        "script_title": "Test Video",
    }
    
    with patch("services.compositor.app.main.settings") as mock_settings:
        mock_settings.WORKSPACE_DIR = str(tmp_path)
        mock_settings.COMPOSITOR_CHUNK_THRESHOLD_SECONDS = 480  # single-render branch
        
        # Don't create the output file - it should fail
        response = client.post("/assemble", json=request_data)
    
    assert response.status_code == 500
    assert "Output file missing after render" in response.json()["detail"]
