"""Unit tests for LLM composer module."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

from services.compositor.app.llm_composer import (
    compose_html,
    _build_composition_prompt,
    _extract_html,
)
from services.compositor.app.duration_prober import AssemblyError
from shared.schemas.common import SceneTimingRecord


def test_extract_html_with_doctype():
    """Test HTML extraction when DOCTYPE is present."""
    response = """
    Here is your HTML:
    <!DOCTYPE html>
    <html>
    <head><title>Test</title></head>
    <body><h1>Hello</h1></body>
    </html>
    Some trailing text
    """
    result = _extract_html(response)
    assert result.startswith("<!DOCTYPE html>")
    assert result.endswith("</html>")
    assert "<h1>Hello</h1>" in result


def test_extract_html_without_doctype():
    """Test HTML extraction when only <html> tag is present."""
    response = """
    Here is your HTML:
    <html>
    <head><title>Test</title></head>
    <body><h1>Hello</h1></body>
    </html>
    Some trailing text
    """
    result = _extract_html(response)
    assert result.startswith("<html>")
    assert result.endswith("</html>")
    assert "<h1>Hello</h1>" in result


def test_extract_html_no_html():
    """Test HTML extraction returns empty string when no HTML found."""
    response = "This is just plain text with no HTML tags"
    result = _extract_html(response)
    assert result == ""


def test_extract_html_empty_response():
    """Test HTML extraction with empty response."""
    result = _extract_html("")
    assert result == ""


def test_build_composition_prompt():
    """Test prompt building includes all required elements."""
    script_title = "Test Video"
    scene_timings = [
        SceneTimingRecord(
            scene_id=1,
            render_path="/workspace/temp/job1/renders/scene_1.mp4",
            audio_path="/workspace/temp/job1/audio/scene_1.wav",
            actual_video_duration_seconds=5.5,
            actual_audio_duration_seconds=6.0,
            start_time_seconds=0.0,
        ),
        SceneTimingRecord(
            scene_id=2,
            render_path="/workspace/temp/job1/renders/scene_2.mp4",
            audio_path="/workspace/temp/job1/audio/scene_2.wav",
            actual_video_duration_seconds=4.0,
            actual_audio_duration_seconds=4.5,
            start_time_seconds=6.0,
        ),
    ]
    image_paths = {
        1: ["/workspace/temp/job1/images/scene_1/img_0.jpg"],
        2: [],
    }
    
    prompt = _build_composition_prompt(script_title, scene_timings, image_paths)
    
    # Check canvas specs
    assert "1920px" in prompt
    assert "1080px" in prompt
    assert "#0f0f0f" in prompt
    
    # Check title
    assert "Test Video" in prompt
    
    # Check scene data
    assert "scene_id: 1" in prompt
    assert "scene_id: 2" in prompt
    assert "start_time_seconds: 0.0" in prompt
    assert "start_time_seconds: 6.0" in prompt
    assert "actual_video_duration_seconds: 5.5" in prompt
    assert "actual_audio_duration_seconds: 6.0" in prompt
    
    # Check layout instructions
    assert "1280px" in prompt  # video panel width
    assert "720px" in prompt   # video panel height
    assert "600px" in prompt   # image width
    assert "400px" in prompt   # image height
    assert "120 characters" in prompt  # lower-third truncation
    
    # Check image paths
    assert "/workspace/temp/job1/images/scene_1/img_0.jpg" in prompt
    assert "(none available)" in prompt  # for scene 2


@patch("services.compositor.app.llm_composer.get_llm_client")
def test_compose_html_success(mock_get_client, tmp_path):
    """Test successful HTML composition."""
    # Mock NVIDIA NIM client response
    mock_client = Mock()
    mock_get_client.return_value = mock_client
    
    mock_response = Mock()
    mock_response.choices = [Mock()]
    mock_response.choices[0].message.content = """
    <!DOCTYPE html>
    <html>
    <head><title>Composition</title></head>
    <body><h1>Test</h1></body>
    </html>
    """
    mock_client.chat.completions.create.return_value = mock_response
    
    # Call compose_html
    scene_timings = [
        SceneTimingRecord(
            scene_id=1,
            render_path="/workspace/temp/job1/renders/scene_1.mp4",
            audio_path="/workspace/temp/job1/audio/scene_1.wav",
            actual_video_duration_seconds=5.0,
            actual_audio_duration_seconds=5.0,
            start_time_seconds=0.0,
        ),
    ]
    
    with patch("services.compositor.app.llm_composer.settings") as mock_settings:
        mock_settings.WORKSPACE_DIR = str(tmp_path)
        mock_settings.COMPOSITOR_LLM_MODEL = "minimaxai/minimax-m2.5"
        
        result = compose_html("Test Title", scene_timings, {}, "job1")
    
    # Verify NIM client was called
    assert mock_client.chat.completions.create.called
    
    # Verify file was written
    output_file = tmp_path / "temp" / "job1" / "composition.html"
    assert output_file.exists()
    html_content = output_file.read_text()
    assert "<!DOCTYPE html>" in html_content


@patch("services.compositor.app.llm_composer.get_llm_client")
def test_compose_html_retry_on_no_html(mock_get_client, tmp_path):
    """Test that compose_html retries when no HTML is found."""
    mock_client = Mock()
    mock_get_client.return_value = mock_client
    
    # First two calls return no HTML, third call returns valid HTML
    mock_response_no_html = Mock()
    mock_response_no_html.choices = [Mock()]
    mock_response_no_html.choices[0].message.content = "No HTML here"
    
    mock_response_valid = Mock()
    mock_response_valid.choices = [Mock()]
    mock_response_valid.choices[0].message.content = """
    <!DOCTYPE html>
    <html><body><h1>Success</h1></body></html>
    """
    
    mock_client.chat.completions.create.side_effect = [
        mock_response_no_html,
        mock_response_no_html,
        mock_response_valid,
    ]
    
    scene_timings = [
        SceneTimingRecord(
            scene_id=1,
            render_path="/workspace/temp/job1/renders/scene_1.mp4",
            audio_path="/workspace/temp/job1/audio/scene_1.wav",
            actual_video_duration_seconds=5.0,
            actual_audio_duration_seconds=5.0,
            start_time_seconds=0.0,
        ),
    ]
    
    with patch("services.compositor.app.llm_composer.settings") as mock_settings:
        mock_settings.WORKSPACE_DIR = str(tmp_path)
        mock_settings.COMPOSITOR_LLM_MODEL = "minimaxai/minimax-m2.5"
        
        result = compose_html("Test Title", scene_timings, {}, "job1")
    
    # Verify it was called 3 times
    assert mock_client.chat.completions.create.call_count == 3


@patch("services.compositor.app.llm_composer.get_llm_client")
def test_compose_html_raises_after_max_retries(mock_get_client):
    """Test that compose_html raises AssemblyError after 3 failed attempts."""
    mock_client = Mock()
    mock_get_client.return_value = mock_client
    
    # All calls return no HTML
    mock_response = Mock()
    mock_response.choices = [Mock()]
    mock_response.choices[0].message.content = "No HTML here"
    
    mock_client.chat.completions.create.return_value = mock_response
    
    scene_timings = [
        SceneTimingRecord(
            scene_id=1,
            render_path="/workspace/temp/job1/renders/scene_1.mp4",
            audio_path="/workspace/temp/job1/audio/scene_1.wav",
            actual_video_duration_seconds=5.0,
            actual_audio_duration_seconds=5.0,
            start_time_seconds=0.0,
        ),
    ]
    
    with patch("services.compositor.app.llm_composer.settings") as mock_settings:
        mock_settings.WORKSPACE_DIR = "/workspace"
        mock_settings.COMPOSITOR_LLM_MODEL = "minimaxai/minimax-m2.5"
        
        with pytest.raises(AssemblyError) as exc_info:
            compose_html("Test Title", scene_timings, {}, "job1")
        
        assert "3 attempts" in str(exc_info.value)
    
    # Verify it was called 3 times
    assert mock_client.chat.completions.create.call_count == 3
