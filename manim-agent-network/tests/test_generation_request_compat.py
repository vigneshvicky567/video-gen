"""GenerationRequest / GenerationBrief backward-compatibility tests."""

import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest
from pydantic import ValidationError

from shared.schemas.common import GenerationRequest, GenerationBrief


def test_legacy_topic_only_still_valid():
    req = GenerationRequest(topic="binary search")
    assert req.topic == "binary search"
    assert req.brief is None


def test_request_with_brief():
    req = GenerationRequest(topic="Learn Django", brief={
        "target_duration_seconds": 720,
        "max_duration_seconds": 1800,
        "is_study_material": True,
        "focus_areas": ["Models", "Views"],
    })
    assert req.brief.target_duration_seconds == 720
    assert req.brief.is_study_material is True
    assert req.brief.focus_areas == ["Models", "Views"]


def test_brief_bounds_enforced():
    with pytest.raises(ValidationError):
        GenerationBrief(target_duration_seconds=10)      # below 60
    with pytest.raises(ValidationError):
        GenerationBrief(target_duration_seconds=9999)    # above 2400


def test_target_clamp_to_max_helper():
    # Mirrors the fail-soft clamp in orchestrator start_generation.
    brief = {"target_duration_seconds": 1800, "max_duration_seconds": 600}
    brief["target_duration_seconds"] = min(brief["target_duration_seconds"], brief["max_duration_seconds"])
    assert brief["target_duration_seconds"] == 600
