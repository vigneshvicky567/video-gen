"""LLM-based HyperFrames HTML composition for the compositor service.

This module provides functionality to:
1. Build a detailed prompt with scene timing, image paths, and layout instructions
2. Call OpenAI API to generate HyperFrames HTML composition
3. Extract and validate HTML from LLM response
4. Write composition to disk
"""

import os
import re
from pathlib import Path
from typing import Dict, List

from openai import OpenAI

from shared.config import settings
from shared.llm_client import get_llm_client
from shared.schemas.common import SceneTimingRecord
from .duration_prober import AssemblyError


def truncate_lower_third(text: str) -> str:
    """Truncate narration text to 120 characters for lower-third display.
    
    Args:
        text: The narration text to truncate
        
    Returns:
        Text truncated to at most 120 characters
    """
    return text[:120]


def compose_html(
    script_title: str,
    scene_timings: List[SceneTimingRecord],
    image_paths: Dict[int, List[str]],
    job_id: str,
) -> str:
    """Generate HyperFrames HTML composition using LLM.
    
    Args:
        script_title: Title of the script for the title card
        scene_timings: List of SceneTimingRecord with timing and path information
        image_paths: Mapping of scene_id to list of image file paths
        job_id: Job identifier for output path
        
    Returns:
        Absolute path to the generated composition.html file
        
    Raises:
        AssemblyError: If LLM fails to produce valid HTML after 3 attempts
    """
    client = get_llm_client()
    
    # Build the prompt with all scene information
    prompt = _build_composition_prompt(script_title, scene_timings, image_paths)
    
    # Try up to 3 times (1 initial + 2 retries)
    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=settings.COMPOSITOR_LLM_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert at creating HyperFrames HTML compositions for video rendering. You produce valid, well-structured HTML documents that conform to the HyperFrames specification."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.7,
            )
            
            html_content = _extract_html(response.choices[0].message.content)
            
            if html_content:
                # Write to disk
                output_path = Path(settings.WORKSPACE_DIR) / "temp" / job_id / "composition.html"
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(html_content)
                return str(output_path)
                
        except Exception as e:
            if attempt == 2:  # Last attempt
                raise AssemblyError(f"LLM composition failed after 3 attempts: {e}")
            # Continue to next attempt
            continue
    
    # If we get here, no valid HTML was found in any attempt
    raise AssemblyError("LLM failed to produce valid HTML after 3 attempts")


def _is_hyperframes_scene(render_path: str) -> bool:
    """Check if a render path is a HyperFrames HTML file.
    
    Args:
        render_path: Path to the rendered content
        
    Returns:
        True if the path is an HTML file (HyperFrames), False if MP4 (Manim)
    """
    return render_path.lower().endswith(".html")


def _build_composition_prompt(
    script_title: str,
    scene_timings: List[SceneTimingRecord],
    image_paths: Dict[int, List[str]],
) -> str:
    """Build the detailed prompt for LLM composition.
    
    Args:
        script_title: Title of the script
        scene_timings: List of scene timing records
        image_paths: Mapping of scene_id to image paths
        
    Returns:
        Complete prompt string for the LLM
    """
    prompt_parts = [
        "Generate a HyperFrames HTML composition document for a video with the following specifications:\n",
        "\n## CRITICAL HyperFrames Rules (MUST FOLLOW)",
        "1. ALL timed elements MUST have: class='clip', data-start, data-duration, data-track-index",
        "2. Video elements MUST be muted (use separate <audio> for sound)",
        "3. Register all timelines on window.__timelines for the renderer to find them",
        "4. NO Math.random() - use seeded PRNG if you need pseudo-random values",
        "5. ALL elements need entrance animations - nothing should appear without animation",
        "6. Add transitions between scenes - avoid jump cuts",
        "\n## Canvas Specifications",
        "- Width: 1920px",
        "- Height: 1080px",
        "- Background color: #0f0f0f",
        "\n## Script Title",
        f"Title: {script_title}",
        "\n## Motion & Easing Vocabulary (use these keywords for best results)",
        "- smooth → power2.out (natural deceleration)",
        "- snappy → power4.out (quick and decisive)",
        "- bouncy → back.out (overshoots then settles)",
        "- springy → elastic.out (oscillates into place)",
        "- dramatic → expo.out (fast start, long glide)",
        "- dreamy → sine.inOut (slow, symmetrical)",
        "- Timing: fast (0.2s) = energy, medium (0.4s) = professional, slow (0.6s) = luxury",
        "\n## Caption Tones",
        "- Hype → heavy fonts, scale-pop animation, 72-96px",
        "- Corporate → clean sans-serif, fade+slide, 56-72px",
        "- Tutorial → monospace, typewriter, 48-64px",
        "- Storytelling → serif, slow fade, 44-56px",
        "- Social → rounded/playful, bounce, 56-80px",
        "\n## Layout Instructions",
        "You MUST create an HTML document with the following structure:",
        "\n### Title Card (scene_id=0, synthetic)",
        "- Display at start=0, duration=3 seconds",
        "- Use <h1> tag with class='clip'",
        "- Set data-start='0', data-duration='3', data-track-index='0'",
        "- Apply GSAP fadeIn animation (use smooth easing)",
        f"- Text content: {script_title}",
        "\n### Per Scene Layout",
        "For each scene below, create the following elements:",
        "\n## IMPORTANT: Content Type Detection",
        "- If render_path ends with .mp4 → Use <video> tag (Manim-rendered scene)",
        "- If render_path ends with .html → Use <iframe> tag (HyperFrames-rendered scene)",
        "\n1. **Manim Video Panel (left side, for .mp4 files)**:",
        "   - <video> tag with class='clip'",
        "   - MUST include: muted attribute (audio goes in separate <audio> element)",
        "   - Position: absolute, left:0, top:180px",
        "   - Size: width:1280px, height:720px",
        "   - data-start: scene's start_time_seconds",
        "   - data-duration: scene's actual_video_duration_seconds",
        "   - data-track-index: N*4+1 (where N is scene_id)",
        "   - src: scene's render_path (only for .mp4 files)",
        "   - Add entrance animation (fadeIn or slideIn with smooth easing)",
        "\n2. **HyperFrames Content Panel (for .html files)**:",
        "   - <iframe> tag with class='clip'",
        "   - Position: absolute, left:0, top:0",
        "   - Size: width:1920px, height:1080px",
        "   - data-start: scene's start_time_seconds",
        "   - data-duration: scene's actual_video_duration_seconds",
        "   - data-track-index: N*4+1",
        "   - src: scene's render_path (only for .html files)",
        "   - frameborder: 0, allowfullscreen",
        "   - Add entrance animation",
        "\n3. **Context Image (right side, only if image available and scene is Manim)**:",
        "   - <img> tag with class='clip'",
        "   - Position: absolute, left:1300px, top:180px",
        "   - Size: width:600px, height:400px",
        "   - data-start: scene's start_time_seconds",
        "   - data-duration: max(actual_video_duration_seconds, actual_audio_duration_seconds)",
        "   - data-track-index: N*4+2",
        "   - src: first image path from image_paths[scene_id]",
        "   - Add entrance animation (fadeIn with medium timing)",
        "\n4. **Lower Third (bottom bar)**:",
        "   - <div> tag with class='clip lower-third'",
        "   - data-start: scene's start_time_seconds",
        "   - data-duration: min(5, max(actual_video_duration_seconds, actual_audio_duration_seconds))",
        "   - data-track-index: N*4+3",
        "   - Text content: scene's narration_text truncated to 120 characters",
        "   - Style: position at bottom of canvas with dark background",
        "   - Add entrance animation (slideUp with smooth easing)",
        "\n5. **Audio Track**:",
        "   - <audio> tag with class='clip'",
        "   - data-start: scene's start_time_seconds",
        "   - data-duration: scene's actual_audio_duration_seconds",
        "   - data-track-index: N*4+4",
        "   - src: scene's audio_path",
        "\n## Scene Transitions",
        "Add transitions between scenes:",
        "- Calm energy → blur crossfade",
        "- Medium energy → push slide",
        "- High energy → zoom through or glitch",
        "\n## Timeline Registration",
        "Register all GSAP timelines on window.__timelines array:",
        "window.__timelines = window.__timelines || [];",
        "window.__timelines.push(timeline);",
        "\n## Scene Data",
    ]
    
    # Add each scene's data
    for timing in scene_timings:
        scene_id = timing.scene_id
        slot_dur = max(timing.actual_video_duration_seconds, timing.actual_audio_duration_seconds)
        images = image_paths.get(scene_id, [])
        
        # Detect content type
        content_type = "HyperFrames" if _is_hyperframes_scene(timing.render_path) else "Manim"
        
        prompt_parts.extend([
            f"\n### Scene {scene_id} ({content_type})",
            f"- scene_id: {scene_id}",
            f"- content_type: {content_type} (render_path ends with {'html' if _is_hyperframes_scene(timing.render_path) else 'mp4'})",
            f"- start_time_seconds: {timing.start_time_seconds}",
            f"- actual_video_duration_seconds: {timing.actual_video_duration_seconds}",
            f"- actual_audio_duration_seconds: {timing.actual_audio_duration_seconds}",
            f"- slot_duration (max of video/audio): {slot_dur}",
            f"- render_path: {timing.render_path}",
            f"- audio_path: {timing.audio_path}",
        ])
        
        if images:
            prompt_parts.append(f"- image_paths: {images}")
        else:
            prompt_parts.append("- image_paths: (none available)")
    
    prompt_parts.extend([
        "\n## Output Requirements",
        "1. Generate a complete, valid HTML5 document",
        "2. Start with <!DOCTYPE html>",
        "3. Include ALL required HyperFrames attributes: class='clip', data-start, data-duration, data-track-index",
        "4. Use inline styles for positioning as specified above",
        "5. Include basic CSS for .lower-third styling (dark background, white text, padding)",
        "6. For .mp4 render_path → use <video> tag with muted attribute",
        "7. For .html render_path → use <iframe> tag to embed the HyperFrames scene",
        "8. Ensure all file paths are used exactly as provided",
        "9. Truncate narration text to exactly 120 characters for lower-third elements",
        "10. Only include image elements for scenes that have image_paths available",
        "11. Add entrance animations to EVERY element (fadeIn, slideIn, etc.)",
        "12. Register all GSAP timelines on window.__timelines",
        "13. Use separate <audio> elements for sound (video elements must be muted)",
        "14. Add scene transitions to avoid jump cuts",
        "\n## Anti-Patterns to AVOID",
        "- DO NOT use React/Vue components - plain HTML only",
        "- DO NOT request 4K or 60fps unless specified (defaults are 1920x1080, 30fps)",
        "- DO NOT use Math.random() - breaks determinism",
        "- DO NOT skip entrance animations",
        "- DO NOT skip scene transitions",
        "\nGenerate the complete HTML document now:",
    ])
    
    return "\n".join(prompt_parts)


def _extract_html(llm_response: str) -> str:
    """Extract HTML document from LLM response.
    
    Looks for <!DOCTYPE html> or <html tag and extracts the complete document.
    
    Args:
        llm_response: Raw response text from LLM
        
    Returns:
        Extracted HTML string, or empty string if no valid HTML found
    """
    if not llm_response:
        return ""
    
    # Look for DOCTYPE declaration
    doctype_match = re.search(r'<!DOCTYPE\s+html[^>]*>', llm_response, re.IGNORECASE)
    if doctype_match:
        # Extract from DOCTYPE to end of </html>
        start_idx = doctype_match.start()
        html_end_match = re.search(r'</html>', llm_response[start_idx:], re.IGNORECASE)
        if html_end_match:
            end_idx = start_idx + html_end_match.end()
            return llm_response[start_idx:end_idx]
    
    # Fallback: look for <html tag
    html_match = re.search(r'<html[^>]*>', llm_response, re.IGNORECASE)
    if html_match:
        start_idx = html_match.start()
        html_end_match = re.search(r'</html>', llm_response[start_idx:], re.IGNORECASE)
        if html_end_match:
            end_idx = start_idx + html_end_match.end()
            return llm_response[start_idx:end_idx]
    
    return ""
