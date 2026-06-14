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
    return {
        "target_seconds": target_s,
        "estimated_seconds": round(total, 1),
        "deviation_pct": round(dev * 100, 1),
        "within_tolerance": abs(dev) <= tol,
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
    """
    total = sum(scene_slot_seconds(s) for s in scenes) or 1.0
    scale = target_s / total
    out = []
    for s in scenes:
        new_slot = max(4.0, scene_slot_seconds(s) * scale)  # 4s floor per scene
        out.append({
            "scene_id": s.get("scene_id"),
            "duration_budget_s": int(round(new_slot)),
            "word_budget": max(8, int(round(new_slot * WPS))),
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
