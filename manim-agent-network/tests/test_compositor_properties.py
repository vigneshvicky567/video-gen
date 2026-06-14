"""
Property-based tests for the manim-hyperframes-compositor feature.

Tests validate universal correctness properties using Hypothesis.

Properties covered:
  1. SceneTimingRecord start-time accumulation
  2. start_time_seconds is always non-negative
  3. HTML round-trip structural equivalence
  4. Magic byte validation accepts only JPEG and PNG
  5. Image fetcher response covers all requested scenes
  6. Pexels Authorization header carries the configured API key
  7. Caption chunking is lossless and windows never overlap or exceed the slot
"""

from __future__ import annotations

import asyncio
import sys
import os
from typing import Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Path setup — allow imports from the project root
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------
from shared.schemas.common import SceneTimingRecord, ScenePlan
from services.compositor.app.duration_prober import compute_scene_timings
from services.compositor.app.html_validator import CompositionValidator
from services.compositor.app.llm_composer import chunk_narration, allocate_caption_windows

# image-fetcher uses a hyphenated directory name which Python can't import
# directly. Add its parent to sys.path so `app` resolves correctly.
_IMAGE_FETCHER_ROOT = os.path.join(PROJECT_ROOT, "services", "image-fetcher")
if _IMAGE_FETCHER_ROOT not in sys.path:
    sys.path.insert(0, _IMAGE_FETCHER_ROOT)

from app.main import is_valid_image, fetch_images_for_scene  # noqa: E402
from app.pexels_client import search_pexels  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    """Run a coroutine synchronously (used in sync Hypothesis tests)."""
    return asyncio.run(coro)


def _build_html(n_video: int, n_audio: int, n_img: int) -> str:
    """Build a minimal synthetic HTML string with the given element counts."""
    parts = ["<html><body>"]
    for i in range(n_video):
        parts.append(f'<video src="/tmp/v{i}.mp4"></video>')
    for i in range(n_audio):
        parts.append(f'<audio src="/tmp/a{i}.wav"></audio>')
    for i in range(n_img):
        parts.append(f'<img src="/tmp/i{i}.jpg">')
    parts.append("</body></html>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Property 1 + 2: SceneTimingRecord start-time accumulation
# ---------------------------------------------------------------------------

@given(
    st.lists(
        st.tuples(
            st.floats(min_value=0.1, max_value=60.0, allow_nan=False),
            st.floats(min_value=0.1, max_value=60.0, allow_nan=False),
        ),
        min_size=1,
        max_size=20,
    )
)
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_scene_timing_accumulation(pairs):
    """
    Property 1: start_time_seconds for scene N equals the sum of
    max(video_dur, audio_dur) for all preceding scenes.

    Property 2: start_time_seconds is always non-negative.

    Validates: Requirements 1.4, 1.6, 7.5
    """
    render_paths = {i: f"/fake/video_{i}.mp4" for i in range(len(pairs))}
    audio_paths = {i: f"/fake/audio_{i}.wav" for i in range(len(pairs))}

    # Provide durations via a side_effect list so probe_duration returns
    # video_dur then audio_dur for each scene in sorted order.
    side_effects = []
    for video_dur, audio_dur in pairs:
        side_effects.append(video_dur)
        side_effects.append(audio_dur)

    with patch(
        "services.compositor.app.duration_prober.probe_duration",
        side_effect=side_effects,
    ):
        records = compute_scene_timings(render_paths, audio_paths)

    assert len(records) == len(pairs)

    # Property 1: accumulated start times match expected values
    # compute_scene_timings rounds start_time_seconds to 3 decimal places,
    # so allow tolerance of 0.001 (one rounding unit).
    expected_start = 0.0
    for idx, (record, (video_dur, audio_dur)) in enumerate(zip(records, pairs)):
        assert abs(record.start_time_seconds - round(expected_start, 3)) < 0.001, (
            f"Scene {idx}: expected start≈{round(expected_start, 3)}, got {record.start_time_seconds}"
        )
        expected_start += max(video_dur, audio_dur)

    # Property 2: all start times are non-negative
    for record in records:
        assert record.start_time_seconds >= 0.0, (
            f"start_time_seconds must be non-negative, got {record.start_time_seconds}"
        )


# ---------------------------------------------------------------------------
# Property 3: HTML round-trip structural equivalence
# ---------------------------------------------------------------------------

@given(
    st.integers(min_value=0, max_value=5),
    st.integers(min_value=0, max_value=5),
    st.integers(min_value=0, max_value=5),
)
@settings(max_examples=100)
def test_html_roundtrip_structural_equivalence(n_video, n_audio, n_img):
    """
    Property 3: Parsing an HTML document with CompositionValidator, serialising
    the counts, and parsing again yields identical element counts.

    Validates: Requirements 8.5
    """
    html = _build_html(n_video, n_audio, n_img)

    # First parse
    v1 = CompositionValidator()
    v1.feed(html)
    counts1 = dict(v1.counts)

    # Rebuild HTML from counts and re-parse
    html2 = _build_html(counts1["video"], counts1["audio"], counts1["img"])
    v2 = CompositionValidator()
    v2.feed(html2)
    counts2 = dict(v2.counts)

    assert counts1 == counts2, (
        f"Round-trip counts mismatch: first={counts1}, second={counts2}"
    )
    assert counts1["video"] == n_video
    assert counts1["audio"] == n_audio
    assert counts1["img"] == n_img


# ---------------------------------------------------------------------------
# Property 4: Magic byte validation accepts only JPEG and PNG
# ---------------------------------------------------------------------------

JPEG_MAGIC = bytes([0xFF, 0xD8, 0xFF])
PNG_MAGIC = bytes([0x89, 0x50, 0x4E, 0x47])


@given(st.binary(min_size=0, max_size=64))
@settings(max_examples=200)
def test_magic_byte_validation(data: bytes):
    """
    Property 4: is_valid_image returns True iff the data starts with
    JPEG magic bytes (FF D8 FF) or PNG magic bytes (89 50 4E 47).

    Validates: Requirements 2.7
    """
    result = is_valid_image(data)

    is_jpeg = len(data) >= 3 and data[:3] == JPEG_MAGIC
    is_png = len(data) >= 4 and data[:4] == PNG_MAGIC
    expected = is_jpeg or is_png

    assert result == expected, (
        f"is_valid_image({data[:8].hex()!r}) returned {result}, expected {expected}"
    )


# ---------------------------------------------------------------------------
# Property 5: Image fetcher response covers all requested scenes
# ---------------------------------------------------------------------------

@given(
    st.lists(
        st.builds(
            ScenePlan,
            scene_id=st.integers(min_value=1, max_value=100),
            narration_text=st.text(min_size=1, max_size=200),
            visual_description=st.text(min_size=1, max_size=200),
            estimated_duration_seconds=st.integers(min_value=1, max_value=30),
        ),
        min_size=1,
        max_size=10,
        unique_by=lambda s: s.scene_id,
    )
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_image_fetcher_covers_all_scenes(scenes: List[ScenePlan]):
    """
    Property 5: The image fetcher returns a key for every scene_id in the
    input, even when both Pexels and Wikimedia return empty lists.

    Validates: Requirements 2.5, 2.6
    """
    async def _run_fetch():
        image_paths: Dict[int, List[str]] = {}
        with (
            patch(
                "app.main.search_pexels",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "app.main.search_wikimedia",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "app.main.extract_keywords",
                return_value=["keyword"],
            ),
        ):
            for scene in scenes:
                paths = await fetch_images_for_scene(
                    scene_id=scene.scene_id,
                    narration_text=scene.narration_text,
                    visual_description=scene.visual_description,
                    job_id="test-job",
                )
                image_paths[scene.scene_id] = paths
        return image_paths

    result = _run(_run_fetch())

    for scene in scenes:
        assert scene.scene_id in result, (
            f"scene_id {scene.scene_id} missing from image_paths result"
        )
        assert isinstance(result[scene.scene_id], list), (
            f"image_paths[{scene.scene_id}] must be a list"
        )


# ---------------------------------------------------------------------------
# Property 6: Pexels Authorization header carries the configured API key
# ---------------------------------------------------------------------------

@given(
    st.text(
        min_size=1,
        max_size=64,
        alphabet=st.characters(whitelist_categories=("L", "N")),
    )
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_pexels_authorization_header(api_key: str):
    """
    Property 6: The Authorization header sent to Pexels equals the
    configured PEXELS_API_KEY exactly.

    Validates: Requirements 6.6
    """
    captured_headers: List[dict] = []

    async def _run_search():
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"photos": []}

        async def _mock_get(url, params=None, headers=None, **kwargs):
            captured_headers.append(dict(headers or {}))
            return mock_response

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = _mock_get

        with (
            patch("app.pexels_client.settings") as mock_settings,
            patch("app.pexels_client.httpx.AsyncClient", return_value=mock_client),
        ):
            mock_settings.PEXELS_API_KEY = api_key
            await search_pexels(["test"])

    _run(_run_search())

    assert len(captured_headers) == 1, "Expected exactly one HTTP request to Pexels"
    assert captured_headers[0].get("Authorization") == api_key, (
        f"Authorization header {captured_headers[0].get('Authorization')!r} "
        f"does not match api_key {api_key!r}"
    )


# ---------------------------------------------------------------------------
# Property 7: Lower-third narration text is truncated to 120 characters
# ---------------------------------------------------------------------------

@given(st.text(min_size=0, max_size=500))
@settings(max_examples=100)
def test_chunk_narration_lossless_and_bounded(text: str):
    """
    Property 7 (chunked captions): chunk_narration never loses words and each
    chunk is within the size budget (or is a single unsplittable word).
    """
    chunks = chunk_narration(text)
    assert " ".join(chunks) == " ".join(text.split()), "narration text was lost in chunking"
    for c in chunks:
        assert len(c) <= 90 or " " not in c, f"chunk exceeds 90 chars and is splittable: {c!r}"


@given(
    st.lists(st.text(min_size=1, max_size=40), min_size=1, max_size=8),
    st.floats(min_value=0.5, max_value=60.0),
    st.floats(min_value=0.5, max_value=60.0),
    st.floats(min_value=0.0, max_value=120.0),
)
@settings(max_examples=100)
def test_caption_windows_chain_and_clamp(chunks, audio, slot, start):
    """Caption windows chain exactly (no overlap) and never exceed the slot."""
    wins = allocate_caption_windows(chunks, audio, slot, start)
    for a, b in zip(wins, wins[1:]):
        assert abs((a[0] + a[1]) - b[0]) < 1e-6, "windows do not chain (overlap/gap)"
    if wins:
        assert all(d > 0 for _, d, _ in wins), "non-positive caption duration"
        # the real neighbor boundary is the 3-decimal rounded accumulated start,
        # so compare against that (not the unrounded float)
        assert (wins[-1][0] + wins[-1][1]) <= round(start + slot, 3) + 1e-9, "caption past scene slot"
