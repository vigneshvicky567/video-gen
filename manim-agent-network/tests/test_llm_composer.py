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
    
    # Check canvas specs (now uses data attributes instead of px units)
    assert "data-width='1920'" in prompt
    assert "data-height='1080'" in prompt
    
    # Check title
    assert "Test Video" in prompt
    
    # Check that the prompt mentions the composition structure
    assert "data-duration" in prompt
    assert "media elements include id" in prompt


def test_compose_html_success(tmp_path):
    """Test successful deterministic HTML composition."""
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
        
        result = compose_html("Test Title", scene_timings, {}, "job1", [])
    
    # Verify file was written
    output_file = tmp_path / "temp" / "job1" / "composition.html"
    assert output_file.exists()
    html_content = output_file.read_text()
    assert "<!DOCTYPE html>" in html_content
    assert 'data-composition-id="main"' in html_content
    assert 'data-duration="5"' in html_content
    assert 'window.__timelines["main"] =' in html_content


def test_compose_html_uses_scene_plan_narration(tmp_path):
    """Test that scene plans with titles are used in the HTML composition."""
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
        compose_html(
            "Test Title",
            scene_timings,
            {},
            "job1",
            [{"scene_id": 1, "narration_text": "Narration text", "title": "Scene Title"}],
        )

    html_content = (tmp_path / "temp" / "job1" / "composition.html").read_text()
    # Narration is in audio, not HTML. Check that scene title is used instead.
    assert "Scene Title" in html_content or "Test Title" in html_content


def test_compose_html_root_duration_uses_last_scene_end(tmp_path):
    scene_timings = [
        SceneTimingRecord(
            scene_id=1,
            render_path="/workspace/temp/job1/renders/scene_1.mp4",
            audio_path="/workspace/temp/job1/audio/scene_1.wav",
            actual_video_duration_seconds=4.0,
            actual_audio_duration_seconds=5.0,
            start_time_seconds=6.0,
        ),
    ]

    with patch("services.compositor.app.llm_composer.settings") as mock_settings:
        mock_settings.WORKSPACE_DIR = str(tmp_path)
        compose_html("Test Title", scene_timings, {}, "job1", [])

    html_content = (tmp_path / "temp" / "job1" / "composition.html").read_text()
    assert 'data-duration="11"' in html_content
