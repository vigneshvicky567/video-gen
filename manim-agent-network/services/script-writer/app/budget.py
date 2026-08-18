"""Pure duration-budget math for the script council.

No LLM, no IO — unit-testable on the host. Mirrors how the compositor slots
scenes (slot = max(video, audio)) so the audit reflects the real assembled
length, not just the LLM's estimated_duration_seconds.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List

from shared.config import settings

WPS = settings.SCRIPT_WORDS_PER_SECOND  # 2.2 words/second


def word_count(text: str) -> int:
    return len((text or "").split())


def narration_seconds(text: str) -> float:
    return word_count(text) / WPS


def scene_slot_seconds(scene: Dict[str, Any]) -> float:
    """Compositor slots a scene at max(video, audio); audio ~ narration length.
    duration_prober.py:116 uses the same max(), so a word-heavy scene can't hide
    under a small estimated_duration_seconds.
    """
    est = float(scene.get("estimated_duration_seconds", 0) or 0)
    return max(est, narration_seconds(scene.get("narration_text", "")))


def audit(scenes: List[Dict[str, Any]], target_s: int,
          tol: float = settings.SCRIPT_DURATION_TOLERANCE) -> Dict[str, Any]:
    total = sum(scene_slot_seconds(s) for s in scenes)
    dev = (total - target_s) / target_s if target_s else 0.0
    # Coverage: how much of the assembled runtime actually carries narration.
    # Slots can hit the target while narration lags far behind (the model
    # inflates estimated_duration_seconds); every uncovered second is dead air
    # in the final video, so low coverage must fail the audit even when the
    # total slot time is within tolerance.
    narration_total = sum(narration_seconds(s.get("narration_text", "")) for s in scenes)
    coverage = (narration_total / total) if total else 0.0
    return {
        "target_seconds": target_s,
        "estimated_seconds": round(total, 1),
        "narration_seconds": round(narration_total, 1),
        "narration_coverage": round(coverage, 2),
        "deviation_pct": round(dev * 100, 1),
        "within_tolerance": abs(dev) <= tol
        and coverage >= settings.SCRIPT_MIN_NARRATION_COVERAGE,
        "per_scene": [
            {
                "scene_id": s.get("scene_id"),
                "words": word_count(s.get("narration_text", "")),
                "est_s": s.get("estimated_duration_seconds"),
                "narration_s": round(narration_seconds(s.get("narration_text", "")), 1),
            }
            for s in scenes
        ],
    }


def repair_budgets(scenes: List[Dict[str, Any]], target_s: int) -> List[Dict[str, Any]]:
    """Per-scene corrected budgets for the repair prompt — scale every scene by
    target/total so their proportions are preserved.

    ONE currency only: target_words. The repair prompt rewrites narration to hit
    target_words and derives estimated_duration_seconds = round(words / WPS), so
    duration and word count can't contradict each other. (An 8-word / 4s floor
    keeps every scene above the compositor's minimum slot.)
    """
    total = sum(scene_slot_seconds(s) for s in scenes) or 1.0
    scale = target_s / total
    out = []
    for s in scenes:
        new_slot = max(4.0, scene_slot_seconds(s) * scale)  # 4s floor per scene
        out.append({
            "scene_id": s.get("scene_id"),
            "target_words": max(8, int(round(new_slot * WPS))),
        })
    return out


def clamp_durations(scenes: List[Dict[str, Any]]) -> None:
    """estimated_duration_seconds must never undercut narration time; the
    compositor slots on max(video, audio) and would silently overshoot otherwise.
    Mutates in place.
    """
    for s in scenes:
        est = int(s.get("estimated_duration_seconds", 0) or 0)
        s["estimated_duration_seconds"] = max(est, math.ceil(narration_seconds(s.get("narration_text", ""))))
