"""Adaptive writer/reviewer council for script generation.

Lives entirely inside the script-writer service — the orchestrator graph is
unchanged (one HTTP call to /generate). Two modes:

  * single  — one writer + one reviewer pass (every job).
  * council — curriculum planner -> N parallel section writers -> merge ->
              reviewer pass. Engaged for study-material topics or targets > 10 min.

A duration-budget audit (+ optional one repair pass) runs when a target length
is known, so the assembled video lands within tolerance.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional, Tuple

from shared.config import settings
from shared.log import get_logger
from shared.schemas.common import ScriptResponse

from . import budget

logger = get_logger(__name__)


# ── Shared authoring rules (kept in sync with the legacy single prompt) ──────
_SCENE_RULES = """\
## Scene Types — choose based on what the scene ACTUALLY needs:

**"hyperframes"** — primarily text/UI: title card, intro, outro, summary,
bullet-point explanation, concept overview, animated text, typography.

**"manim"** — a visual diagram or mathematical animation: plotting a function,
drawing a geometric construction, animating a formula, visualizing a network/
matrix/data structure. Any scene where shapes/curves/math objects move.

## Rules:
- narration_text must be natural and conversational (TTS-friendly).
- visual_description must be specific:
  - hyperframes: layout, text content, colors, GSAP animations
  - manim: exact objects, formulas, and animation sequence
- Manim scenes MUST be 2D (flat graphs, diagrams, formulas). NEVER 3D surfaces,
  terrain, or rotating cameras — describe a 2D cross-section/contour instead.
- One focused visualization per Manim scene (<=6 animation beats). Split denser
  ideas across scenes.
"""

_SCENE_JSON = """\
Each scene object:
{
  "scene_id": 1,
  "title": "Short Scene Title (4-6 words)",
  "content_type": "hyperframes",
  "narration_text": "...",
  "visual_description": "...",
  "estimated_duration_seconds": 8
}"""


def _budget_block(brief: Optional[Dict[str, Any]]) -> str:
    if not brief or not brief.get("target_duration_seconds"):
        return (
            "- estimated_duration_seconds should reflect spoken narration time "
            "(~2.2 words/second, so a 2-sentence narration ~= 8-12 seconds).\n"
        )
    target = brief["target_duration_seconds"]
    audience = brief.get("audience_level") or "general"
    focus = ", ".join(brief.get("focus_areas") or []) or "the most important parts"
    style = brief.get("visual_style") or "balanced"
    pacing = brief.get("pacing") or "steady"
    return f"""\
## Duration budget (HARD REQUIREMENT)
Total video length: {target}s. The sum of estimated_duration_seconds across ALL
scenes MUST be {target}s plus or minus 10%.
Narration is spoken at 2.2 words/second: a scene with estimated_duration_seconds
= D must contain about D x 2.2 narration words. Do not under- or over-write.
Audience: {audience}. Emphasize: {focus}. Style/pacing: {style} / {pacing}.
"""


async def _call_json(client, system: str, user: str, *, temperature: float, max_tokens: int) -> Any:
    response = await client.chat.completions.acreate(
        model=settings.SCRIPT_WRITER_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
        response_format={"type": "json_object"},
        max_tokens=max_tokens,
    )
    # The shared NIM client returns content=None on filtered/refused/tool-only
    # responses; json.loads(None) raises TypeError. Fail loud-but-typed so
    # callers can degrade instead of 500-ing the whole /generate request.
    content = response.choices[0].message.content
    if not content:
        raise ValueError("empty LLM response (filtered/refused/tool-only content)")
    return json.loads(content)


# ── Invariants ───────────────────────────────────────────────────────────────
def _renumber_and_enforce_invariants(scenes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Re-number scene_id 1..N and enforce structural rules.

    MUST run before the script leaves this service: afterward scene_id is an
    immutable dict key across code/render/audio paths and the HyperFrames
    "scene-{id}" contract.
    """
    cleaned: List[Dict[str, Any]] = []
    for s in scenes:
        if not isinstance(s, dict):
            continue
        if not str(s.get("narration_text", "")).strip():
            continue  # drop empty-narration scenes
        ct = s.get("content_type")
        if ct not in ("hyperframes", "manim"):
            ct = "hyperframes"
        try:
            est = int(s.get("estimated_duration_seconds", 0) or 0)
        except (TypeError, ValueError):
            est = 0
        cleaned.append({
            "title": (s.get("title") or "")[:80],
            "content_type": ct,
            "narration_text": s["narration_text"],
            "visual_description": s.get("visual_description", ""),
            "estimated_duration_seconds": max(3, est),
        })

    # Cap scene count: merge shortest adjacent same-type scenes until under cap.
    cap = settings.SCRIPT_MAX_SCENES
    while len(cleaned) > cap:
        best_i, best_sum = None, None
        for i in range(len(cleaned) - 1):
            if cleaned[i]["content_type"] == cleaned[i + 1]["content_type"]:
                pair = cleaned[i]["estimated_duration_seconds"] + cleaned[i + 1]["estimated_duration_seconds"]
                if best_sum is None or pair < best_sum:
                    best_i, best_sum = i, pair
        if best_i is None:
            del cleaned[-2]  # no same-type neighbor; drop second-to-last
            continue
        a, b = cleaned[best_i], cleaned[best_i + 1]
        a["narration_text"] = f"{a['narration_text']} {b['narration_text']}".strip()
        a["estimated_duration_seconds"] += b["estimated_duration_seconds"]
        del cleaned[best_i + 1]

    if not cleaned:  # degenerate guard
        cleaned = [{
            "title": "Overview", "content_type": "hyperframes",
            "narration_text": "Overview.", "visual_description": "Title card.",
            "estimated_duration_seconds": 6,
        }]

    # First + last scene must be hyperframes (intro / outro).
    cleaned[0]["content_type"] = "hyperframes"
    cleaned[-1]["content_type"] = "hyperframes"

    for i, s in enumerate(cleaned, start=1):
        s["scene_id"] = i
    return cleaned


# ── Writers ──────────────────────────────────────────────────────────────────
async def _single_writer(topic: str, brief: Optional[Dict[str, Any]], client) -> Tuple[str, List[Dict[str, Any]]]:
    prompt = f"""\
You are an expert technical director for educational video production.

Create a script for a video about: **{topic}**

Decide how many scenes the topic needs (a simple concept might need 3, a complex
one 7+). Use as many as it takes to explain the topic clearly — do not pad.

{_SCENE_RULES}
- Scene 1 MUST be "hyperframes" (title/intro). Last scene MUST be "hyperframes" (summary/outro).
{_budget_block(brief)}
Return ONLY valid JSON: {{"title": "...", "scenes": [ {_SCENE_JSON} ]}}
"""
    try:
        data = await _call_json(
            client,
            "You are an expert technical director. Always respond with valid JSON only.",
            prompt, temperature=0.7, max_tokens=8000,
        )
    except Exception as e:  # noqa: BLE001 — empty/invalid LLM response must not 500 /generate
        logger.warning("Single writer failed; degrading to minimal script", extra={"topic": topic, "error": str(e)})
        return topic, []
    return str(data.get("title") or topic), list(data.get("scenes") or [])


async def _planner(topic: str, brief: Dict[str, Any], client) -> Dict[str, Any]:
    target = brief["target_duration_seconds"]
    audience = brief.get("audience_level") or "general"
    focus = ", ".join(brief.get("focus_areas") or []) or "comprehensive coverage"
    prompt = f"""\
You are a curriculum designer planning a {target}-second educational video about:
**{topic}**

Audience: {audience}. Emphasize: {focus}.

Break it into 3-8 sections that together tell a complete story. Distribute the
{target}s across sections (the section time_budget_seconds MUST sum to {target}s
plus or minus 5%). For each section give a scene_count_hint roughly equal to
time_budget_seconds / 25 (long-form scenes run 15-35s each). Across all sections
the total scenes must not exceed {settings.SCRIPT_MAX_SCENES}.

Return ONLY valid JSON:
{{
  "title": "Overall video title",
  "sections": [
    {{"section_id": 1, "title": "...", "goal": "what this section teaches",
      "time_budget_seconds": 120, "scene_count_hint": 5}}
  ]
}}
"""
    try:
        return await _call_json(
            client,
            "You are a curriculum designer. Always respond with valid JSON only.",
            prompt, temperature=0.5, max_tokens=3000,
        )
    except Exception as e:  # noqa: BLE001 — planner failure degrades to single-writer, never 500
        logger.warning("Planner failed; degrading to single-writer", extra={"topic": topic, "error": str(e)})
        return {}


async def _section_writer(topic: str, brief: Dict[str, Any], section: Dict[str, Any], client) -> List[Dict[str, Any]]:
    budget_s = section.get("time_budget_seconds", 120)
    hint = section.get("scene_count_hint", max(2, int(budget_s / 25)))
    prompt = f"""\
You are writing ONE section of a larger video about **{topic}**.

Section: "{section.get('title')}" — goal: {section.get('goal')}
Time budget: {budget_s}s across about {hint} scenes.
Per-scene narration word budget = estimated_duration_seconds x 2.2.
The scene estimated_duration_seconds in THIS section must sum to about {budget_s}s.

{_SCENE_RULES}
- Do NOT write a title card or outro — those belong to other sections.
- Use local scene_id starting at 1 (they will be renumbered globally).

Return ONLY valid JSON: {{"scenes": [ {_SCENE_JSON} ]}}
"""
    data = await _call_json(
        client,
        "You are an expert technical director. Always respond with valid JSON only.",
        prompt, temperature=0.7, max_tokens=6000,
    )
    return list(data.get("scenes") or [])


async def _full_council(topic: str, brief: Dict[str, Any], client) -> Tuple[str, List[Dict[str, Any]]]:
    plan = await _planner(topic, brief, client)
    title = str(plan.get("title") or topic)
    sections = [s for s in (plan.get("sections") or []) if isinstance(s, dict)]
    if not sections:
        return await _single_writer(topic, brief, client)

    sem = asyncio.Semaphore(settings.COUNCIL_MAX_PARALLEL_WRITERS)

    async def _write(sec):
        async with sem:
            try:
                return await _section_writer(topic, brief, sec, client)
            except Exception as e:  # noqa: BLE001 — one bad section shouldn't kill the script
                logger.warning("Section writer failed", extra={"section": sec.get("title"), "error": str(e)})
                return []

    results = await asyncio.gather(*(_write(s) for s in sections))

    intro = {
        "title": title[:60], "content_type": "hyperframes",
        "narration_text": f"Welcome. In this video we'll explore {topic}.",
        "visual_description": f"Title card: '{title}' on a clean background, fade in.",
        "estimated_duration_seconds": 7,
    }
    outro = {
        "title": "Summary", "content_type": "hyperframes",
        "narration_text": "That's the big picture. Review the key ideas and try them yourself.",
        "visual_description": "Summary card recapping the main sections, fade out.",
        "estimated_duration_seconds": 8,
    }
    scenes: List[Dict[str, Any]] = [intro]
    for section_scenes in results:
        scenes.extend(section_scenes)
    scenes.append(outro)
    return title, scenes


# ── Reviewer / fix / repair ───────────────────────────────────────────────────
async def _reviewer(topic: str, brief: Optional[Dict[str, Any]], scenes: List[Dict[str, Any]], client) -> Dict[str, Any]:
    compact = [
        {"scene_id": s.get("scene_id"), "type": s.get("content_type"),
         "title": s.get("title"), "narration": s.get("narration_text", "")[:200],
         "est_s": s.get("estimated_duration_seconds")}
        for s in scenes
    ]
    target = (brief or {}).get("target_duration_seconds")
    prompt = f"""\
You are a senior script reviewer. Critique this script for a video about **{topic}**.
{f'Target length: {target}s.' if target else ''}

Scenes (JSON): {json.dumps(compact, ensure_ascii=False)}

Check: topic coverage (gaps/redundancy), narration quality (clear, conversational,
right length), scene-type fit (manim for visuals/math, hyperframes for text), and
timing realism. Be strict but concise.

Return ONLY valid JSON:
{{
  "coverage_issues": ["..."],
  "narration_issues": [{{"scene_id": 2, "fix": "..."}}],
  "timing_issues": ["..."],
  "type_issues": [{{"scene_id": 3, "should_be": "manim"}}],
  "verdict": "ok" | "revise"
}}
"""
    try:
        return await _call_json(
            client, "You are a senior script reviewer. Always respond with valid JSON only.",
            prompt, temperature=0.3, max_tokens=2000,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("Reviewer failed; accepting script as-is", extra={"error": str(e)})
        return {"verdict": "ok"}


async def _writer_fix(topic: str, brief: Optional[Dict[str, Any]], scenes: List[Dict[str, Any]], critique: Dict[str, Any], client) -> List[Dict[str, Any]]:
    prompt = f"""\
Revise this video script about **{topic}** to address the reviewer's critique.
Keep what works; fix what's flagged. Preserve the overall structure and the
first/last scenes as hyperframes.

Current scenes (JSON): {json.dumps(scenes, ensure_ascii=False)}

Reviewer critique (JSON): {json.dumps(critique, ensure_ascii=False)}

{_budget_block(brief)}
Return ONLY valid JSON: {{"title": "...", "scenes": [ {_SCENE_JSON} ]}}
"""
    try:
        data = await _call_json(
            client, "You are an expert technical director. Always respond with valid JSON only.",
            prompt, temperature=0.6, max_tokens=8000,
        )
        new_scenes = list(data.get("scenes") or [])
        return new_scenes or scenes
    except Exception as e:  # noqa: BLE001
        logger.warning("Writer-fix failed; keeping pre-fix script", extra={"error": str(e)})
        return scenes


async def _repair(topic: str, scenes: List[Dict[str, Any]], budgets: List[Dict[str, Any]], target: int, client) -> List[Dict[str, Any]]:
    prompt = f"""\
The script for **{topic}** is off its {target}s duration budget. Rewrite the
narration so each scene matches its per-scene budget below. Do NOT add or remove
scenes; keep scene_id, title, content_type, and visual_description. Only adjust
narration_text length and estimated_duration_seconds to hit each budget.

Per-scene budgets (JSON): {json.dumps(budgets, ensure_ascii=False)}

Current scenes (JSON): {json.dumps(scenes, ensure_ascii=False)}

word_budget is the target narration word count (2.2 words/second).
Return ONLY valid JSON: {{"scenes": [ {_SCENE_JSON} ]}}
"""
    try:
        data = await _call_json(
            client, "You are an expert technical director. Always respond with valid JSON only.",
            prompt, temperature=0.5, max_tokens=8000,
        )
        new_scenes = list(data.get("scenes") or [])
        return new_scenes or scenes
    except Exception as e:  # noqa: BLE001
        logger.warning("Duration repair failed; keeping pre-repair script", extra={"error": str(e)})
        return scenes


# ── Orchestration ──────────────────────────────────────────────────────────────
async def generate_script(topic: str, brief: Optional[Dict[str, Any]], client) -> Tuple[ScriptResponse, Dict[str, Any]]:
    target = (brief or {}).get("target_duration_seconds")
    is_study = bool((brief or {}).get("is_study_material"))
    full = bool(brief) and (is_study or (target or 0) > settings.COUNCIL_FULL_THRESHOLD_SECONDS)
    warnings: List[str] = []

    if full:
        title, scenes = await _full_council(topic, brief, client)
    else:
        title, scenes = await _single_writer(topic, brief, client)
    scenes = _renumber_and_enforce_invariants(scenes)

    # Reviewer pass — every job.
    critique = await _reviewer(topic, brief, scenes, client)
    if str(critique.get("verdict")) == "revise":
        scenes = await _writer_fix(topic, brief, scenes, critique, client)
        scenes = _renumber_and_enforce_invariants(scenes)

    meta: Dict[str, Any] = {"mode": "council" if full else "single", "warnings": warnings}

    # Duration audit (+ one repair) when a target is known.
    if target:
        report = budget.audit(scenes, target)
        if not report["within_tolerance"]:
            repaired = await _repair(topic, scenes, budget.repair_budgets(scenes, target), target, client)
            repaired = _renumber_and_enforce_invariants(repaired)
            rep_report = budget.audit(repaired, target)
            if abs(rep_report["deviation_pct"]) < abs(report["deviation_pct"]):
                scenes, report = repaired, rep_report
            if not report["within_tolerance"]:
                warnings.append(f"duration off-budget by {report['deviation_pct']}% after repair")
        budget.clamp_durations(scenes)
        meta["duration_audit"] = budget.audit(scenes, target)  # post-clamp truth

    script = ScriptResponse(title=title, scenes=scenes)
    return script, meta
