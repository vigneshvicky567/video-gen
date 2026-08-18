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
from . import markdown_script as mds

logger = get_logger(__name__)


# ── Shared authoring rules ────────────────────────────────────────────────────
# Distilled from what makes the best educational video work: 3Blue1Brown's
# visual pedagogy (concrete-before-abstract, motion that carries meaning),
# Kurzgesagt's narrative structure (hook -> tension -> resolution), and Mayer's
# multimedia-learning principles (complementarity, signaling, coherence).

_STORY_RULES = """\
## Story arc (the video is a STORY, not a list of facts):
- Scene 1 must pose a concrete question, paradox, or stake — NEVER "in this
  video we will learn about X" and NEVER a definition. Make the viewer feel
  the question. ("Why can you scramble an egg but never unscramble it?")
- Concrete before abstract: show a specific example, number, or scenario
  BEFORE any general definition or formula. A term may only be introduced
  after the viewer has seen the problem it solves.
- Structure as And-But-Therefore: setup, then a genuine complication ("but"),
  then its consequence ("therefore"). At least one real tension turn must
  appear by the one-third mark — no and-and-and fact chains.
- Every scene after the first must open from the previous scene's result
  ("So light bends — but then why...?"). If two scenes could swap order
  without breaking anything, the arc is broken: rewrite.
- ONE new idea per scene. Two new things in the narration = split the scene.
- One central metaphor per video, maximum. Every scene either extends it or
  uses literal visuals — never introduce a second competing metaphor.
- Translate every large/small number into a tangible comparison ("that's 40
  Olympic pools"). Raw magnitudes alone are forbidden.
- Never re-walk an example the viewer has already seen. Later scenes build on
  its RESULT ("remember, the street's best was eleven...") instead of
  repeating the walk step by step.
- The final scene must REFRAME the opening question with the earned insight —
  never "in conclusion, we learned...". Make the last line quotable.
"""

_NARRATION_RULES = """\
## Narration (written for the EAR — it must sound like a gifted teacher
## talking to one person, never like a textbook or a bullet list):
- Conversational second person: "you", "we", contractions, direct questions.
- WORDS DRIVE TIME: write the narration first, then set the scene duration to
  round(word_count / 2.2). Never set a duration the words can't fill — every
  missing word is dead silence in the finished video.
- FLOW: full spoken sentences by default, linked by consequence or contrast
  ("which means...", "so here's the catch...", "but notice what happened...").
  A sentence fragment is a spice: at most ONE per scene, only for emphasis.
  NEVER write telegraphic chains ("Take 7. Max 11. Shift.") — if narration
  reads like a ledger or a code trace, rewrite it as reasoning.
- RHYTHM: vary sentence length between ~8 and ~22 words; never three
  same-shaped sentences in a row. Read it aloud in your head — if you would
  not say it to a friend at a whiteboard, rewrite it.
- DEPTH: for every new idea give (1) the thing, (2) why it's true or works,
  (3) why the viewer should care — inside the same scene. Never state a fact
  and move on. "What—why—so what" is the unit of teaching, not the sentence.
- One concrete analogy or mental picture per major concept, drawn from
  everyday life ("like choosing between two job offers where..."). Extend the
  video's ONE central metaphor; never introduce a competing one.
- Worked examples are narrated as THINKING, not tracing: state the decision
  and its reason ("Nine, plus the two we banked two houses back — eleven.
  That beats the seven we'd keep by skipping."), never a bare number ledger.
- Narration must NOT read the on-screen text aloud. On-screen text carries
  keywords/labels/numbers; narration carries the reasoning and the "so what".
  Never narrate what the viewer plainly sees ("here we see a blue circle").
- Ask a genuine question aloud roughly every 3-4 scenes and ANSWER it within
  two scenes; let the VISUAL carry the answer while narration explains why.
- Vivid physical verbs ("the electron slams into", not "interacts with").
- Speak symbols as words: "d-p of i minus one", "big O of n" — never bracket
  or operator notation inside narration text.
- Banned: "basically", "essentially", "as we can see", "it's important to
  note", "let's dive in", clipped bullet-like fragments, unexplained symbols.
"""

_GROUNDING_RULES = """\
## Accuracy (educational content — credibility is the product):
- Prefer well-established facts. NEVER invent specific statistics, dates,
  quotes, study results, or formulas you are not certain of.
- Keep uncertain claims qualitative ("most", "roughly", "around") instead of
  fabricating precision. If a number is essential and you are unsure, use a
  famously-known one or restructure the point without it.
"""

_SCENE_RULES = """\
## Scene Types — choose based on what the scene ACTUALLY needs:

**"manim"** — anything that MOVES with meaning: plotting a function, geometric
construction, morphing one formula into another, arrows/flows in a network,
step-by-step visual proofs, data structures changing. Prefer manim for the
explanatory core of the video — motion that SHOWS the idea beats text that
states it.

**"hyperframes"** — motion-graphics slides: title/hook card, big-number stat,
split-screen comparison, annotated diagram over an image, timeline,
process-flow, kinetic one-line statement, summary/outro.

## visual_description contract (this is a SHOT SPEC, be director-specific):
- manim scenes: name the exact objects (axes, curve, dots, arrows, MathTex),
  the ANIMATION SEQUENCE (what appears/transforms/moves, in what order), and
  what each motion MEANS ("the rectangle count doubles to show convergence").
  Motion must carry meaning — no decorative spinning/bouncing. One focal
  point at a time; state what gets dimmed or removed when focus shifts.
  Assign each key entity ONE color and reuse it consistently across scenes.
- hyperframes scenes: NAME THE LAYOUT ARCHETYPE, then its content. Archetypes:
  big-stat (one huge number + unit + one-line comparison), split-compare
  (two panels, differences highlighted), annotated-diagram (central figure,
  labels appear as narration names each part), timeline (events pop along a
  spine), process-flow (3-5 nodes lighting up in sequence), kinetic-statement
  (one <=12-word sentence as full-frame typography, key word emphasized),
  chart-reveal (axes first, data animates in), before-after.
  BANNED as a layout: centered title + bullet list. If you're about to write
  bullets, pick an archetype instead.
- On-screen text <=12 words at any hero moment; labels <=7 words.
- Note continuity: which element/color/position carries over from the
  previous scene, so consecutive scenes cut together like one film.

## Hard constraints:
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


# Reserved question ids already folded into the typed brief fields above; the
# rest are topic-specific questions the analyzer designed for THIS video, whose
# answers would otherwise be collected and ignored.
_RESERVED_QIDS = {"duration", "audience", "focus", "style", "visual_style", "pacing"}


def _answers_block(brief: Optional[Dict[str, Any]]) -> str:
    """Surface the creator's topic-specific questionnaire answers to the writer."""
    if not brief:
        return ""
    lines: List[str] = []
    for ans in brief.get("answers") or []:
        if not isinstance(ans, dict):
            continue
        qid = str(ans.get("question_id") or "").strip()
        if not qid or qid in _RESERVED_QIDS:
            continue
        picks = ", ".join(s for s in (ans.get("selected") or []) if s)
        custom = str(ans.get("custom_text") or "").strip()
        detail = " — ".join(p for p in (picks, custom) if p)
        if detail:
            lines.append(f"- {qid.replace('_', ' ')}: {detail}")
    if not lines:
        return ""
    return "Creator's specific choices for this video (honor these):\n" + "\n".join(lines) + "\n"


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
    total_words = int(target * settings.SCRIPT_WORDS_PER_SECOND)
    return f"""\
## Duration budget (HARD REQUIREMENT — words are the currency)
Total video length: {target}s. Narration is spoken at 2.2 words/second, so the
whole script needs about {total_words} narration words TOTAL. Work like this:
1. Distribute the ~{total_words} words across your scenes (a scene teaching a
   hard idea gets more, a transition gets fewer).
2. Write each scene's narration to its share — actually count the words.
3. Set each scene's estimated_duration_seconds = round(its word count / 2.2).
   Never set it any other way.
Done right, durations automatically sum to ~{target}s. A script whose words sum
far below {total_words} means minutes of dead silence in the finished video —
that is a failed script.
Audience: {audience}. Emphasize: {focus}. Style/pacing: {style} / {pacing}.
{_answers_block(brief)}"""


def _writer_models() -> List[str]:
    """Primary model plus ordered fallbacks (deduplicated, order-preserving)."""
    models = [settings.SCRIPT_WRITER_MODEL]
    models += [m.strip() for m in settings.SCRIPT_WRITER_FALLBACK_MODELS.split(",") if m.strip()]
    seen: set = set()
    return [m for m in models if not (m in seen or seen.add(m))]


async def _acreate_with_fallback(client, **kwargs: Any):
    """Try the primary writer model, then each fallback in order.

    A dead model id (NIM function removed from the account — observed live with
    kimi-k2.6 returning 404 on every key) used to fail the whole script stage;
    with fallbacks the job degrades to the next-best writer instead.
    """
    last_exc: Exception | None = None
    for model in _writer_models():
        try:
            return await client.chat.completions.acreate(model=model, **kwargs)
        except Exception as e:  # noqa: BLE001 — any provider failure moves to the next model
            last_exc = e
            logger.warning("Writer model failed; trying fallback",
                           extra={"model": model, "error": str(e)})
    raise last_exc if last_exc else RuntimeError("no writer models configured")


async def _call_json(client, system: str, user: str, *, temperature: float, max_tokens: int) -> Any:
    from shared.llm_client import extract_json
    response = await _acreate_with_fallback(
        client,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
        response_format={"type": "json_object"},
        max_tokens=max_tokens,
    )
    # The client raises LLMEmptyContent on refused/filtered replies; here we
    # still guard falsy content for any backend that slips through, and run
    # the reply through extract_json — neither NIM nor Anthropic hard-enforce
    # JSON mode, so fences/prose around the JSON are common.
    content = response.choices[0].message.content
    if not content:
        raise ValueError("empty LLM response (filtered/refused/tool-only content)")
    return json.loads(extract_json(content))


def _md_mode() -> bool:
    return settings.SCRIPT_OUTPUT_FORMAT.strip().lower() == "markdown"


def _writer_format_block(with_title: bool) -> str:
    """The 'return your answer like this' block for writer prompts."""
    if _md_mode():
        return mds.FORMAT_SPEC if with_title else mds.FORMAT_SPEC_SCENES_ONLY
    if with_title:
        return f'Return ONLY valid JSON: {{"title": "...", "scenes": [ {_SCENE_JSON} ]}}'
    return f'Return ONLY valid JSON: {{"scenes": [ {_SCENE_JSON} ]}}'


async def _call_writer(client, system: str, user: str, *, temperature: float,
                       max_tokens: int) -> tuple:
    """One writer-stage LLM call. Returns (title_or_None, scenes).

    Markdown mode: plain-text completion parsed by the salvage-tolerant MD
    parser — a reply truncated mid-scene still yields every completed scene
    (JSON mode loses the whole script to one unbalanced brace). Falls back to
    JSON extraction when the model emitted JSON anyway.
    """
    if not _md_mode():
        data = await _call_json(client, system, user,
                                temperature=temperature, max_tokens=max_tokens)
        return data.get("title"), list(data.get("scenes") or [])

    response = await _acreate_with_fallback(
        client,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    content = response.choices[0].message.content or ""
    title, scenes = mds.parse_script_markdown(content)
    if scenes:
        return title, scenes
    # Model ignored the format and answered in JSON — salvage that too.
    try:
        from shared.llm_client import extract_json
        data = json.loads(extract_json(content))
        return data.get("title"), list(data.get("scenes") or [])
    except (TypeError, ValueError):
        raise ValueError("writer reply had no parseable scenes (markdown or JSON)")


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

    # Cap scene count: merge shortest adjacent scenes until under cap. Prefer a
    # same-type pair; if none exists, merge the shortest adjacent pair anyway
    # (keeping the first scene's type) — NEVER delete content: the old
    # `del cleaned[-2]` silently destroyed an arbitrary scene's narration.
    cap = settings.SCRIPT_MAX_SCENES

    def _merge_pair(i: int) -> None:
        a, b = cleaned[i], cleaned[i + 1]
        a["narration_text"] = f"{a['narration_text']} {b['narration_text']}".strip()
        if b.get("visual_description"):
            a["visual_description"] = (
                f"{a['visual_description']} Then: {b['visual_description']}".strip()
                if a.get("visual_description") else b["visual_description"]
            )
        a["estimated_duration_seconds"] += b["estimated_duration_seconds"]
        del cleaned[i + 1]

    while len(cleaned) > cap and len(cleaned) >= 2:
        best_i, best_sum = None, None
        for i in range(len(cleaned) - 1):
            if cleaned[i]["content_type"] == cleaned[i + 1]["content_type"]:
                pair = cleaned[i]["estimated_duration_seconds"] + cleaned[i + 1]["estimated_duration_seconds"]
                if best_sum is None or pair < best_sum:
                    best_i, best_sum = i, pair
        if best_i is None:
            # No same-type neighbors at all — merge the globally shortest
            # adjacent pair regardless of type.
            best_i = min(
                range(len(cleaned) - 1),
                key=lambda i: cleaned[i]["estimated_duration_seconds"]
                + cleaned[i + 1]["estimated_duration_seconds"],
            )
        _merge_pair(best_i)

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
You are an award-winning writer-director of educational videos (think
3Blue1Brown's visual clarity crossed with Kurzgesagt's storytelling).

Create a script for a video about: **{topic}**

Decide how many scenes the topic needs (a simple concept might need 3, a complex
one 7+). Use as many as it takes to explain the topic clearly — do not pad.

{_STORY_RULES}
{_NARRATION_RULES}
{_GROUNDING_RULES}
{_SCENE_RULES}
- Scene 1 MUST be "hyperframes" (the cold-open hook card — a question or stake,
  NOT a topic announcement). Last scene MUST be "hyperframes" (the takeaway that
  reframes the hook).
{_budget_block(brief)}
{_writer_format_block(with_title=True)}
"""
    try:
        title, scenes = await _call_writer(
            client,
            "You are an expert writer-director for educational video. Follow the requested output format exactly.",
            prompt, temperature=0.5, max_tokens=8000,
        )
    except Exception as e:  # noqa: BLE001 — empty/invalid LLM response must not 500 /generate
        logger.warning("Single writer failed; degrading to minimal script", extra={"topic": topic, "error": str(e)})
        return topic, []
    return str(title or topic), scenes


async def _planner(topic: str, brief: Dict[str, Any], client) -> Dict[str, Any]:
    target = brief["target_duration_seconds"]
    audience = brief.get("audience_level") or "general"
    focus = ", ".join(brief.get("focus_areas") or []) or "comprehensive coverage"
    prompt = f"""\
You are the head writer planning a {target}-second educational video about:
**{topic}**

Audience: {audience}. Emphasize: {focus}.
{_answers_block(brief)}
Design the video as ONE STORY, not a syllabus:
- Write the HOOK: the cold-open question/paradox/stake the whole video hangs on
  (a viewer-felt question, never "in this video we will...").
- Write the TAKEAWAY: the closing line that reframes the hook with the earned
  insight — quotable, not "in conclusion".
- Write a STYLE CONTRACT every writer must honor: the ONE central metaphor (or
  "none — literal visuals"), 4-8 canonical terms with the exact wording to use
  (so section writers don't drift between synonyms), and the tone in one line.
- Break the body into 3-8 sections that ESCALATE (each section's goal should
  begin from the previous one's result — and, but, therefore). Distribute the
  {target}s across sections (time_budget_seconds MUST sum to {target}s plus or
  minus 5%). scene_count_hint ~= time_budget_seconds / 25 (long-form scenes run
  15-35s). Total scenes across sections must not exceed {settings.SCRIPT_MAX_SCENES}.

Return ONLY valid JSON:
{{
  "title": "Overall video title",
  "hook": {{"narration": "the cold-open line(s), <=20 words",
            "visual": "hook card shot spec (kinetic-statement or big-stat archetype)"}},
  "takeaway": {{"narration": "the closing line(s), <=25 words",
                "visual": "takeaway card shot spec"}},
  "style_contract": {{"metaphor": "...", "terminology": ["term: exact wording", "..."],
                      "tone": "..."}},
  "sections": [
    {{"section_id": 1, "title": "...", "goal": "what this section teaches",
      "tension": "the 'but' this section introduces or resolves",
      "time_budget_seconds": 120, "scene_count_hint": 5}}
  ]
}}
"""
    try:
        return await _call_json(
            client,
            "You are a head writer for educational video. Always respond with valid JSON only.",
            prompt, temperature=0.5, max_tokens=3000,
        )
    except Exception as e:  # noqa: BLE001 — planner failure degrades to single-writer, never 500
        logger.warning("Planner failed; degrading to single-writer", extra={"topic": topic, "error": str(e)})
        return {}


async def _section_writer(topic: str, brief: Dict[str, Any], section: Dict[str, Any],
                          client, style_contract: Optional[Dict[str, Any]] = None,
                          prev_section: Optional[Dict[str, Any]] = None,
                          next_section: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    budget_s = section.get("time_budget_seconds", 120)
    hint = section.get("scene_count_hint", max(2, int(budget_s / 25)))
    contract_block = ""
    if style_contract:
        contract_block = (
            "## Style contract (ALL sections share this — do not drift):\n"
            f"{json.dumps(style_contract, ensure_ascii=False)}\n"
        )
    neighbors_block = (
        "## Where your section sits in the story:\n"
        f"- Previous section: {json.dumps({'title': prev_section.get('title'), 'goal': prev_section.get('goal')}, ensure_ascii=False) if prev_section else 'none — yours follows the cold-open hook'}\n"
        f"- Next section: {json.dumps({'title': next_section.get('title'), 'goal': next_section.get('goal')}, ensure_ascii=False) if next_section else 'none — yours leads into the takeaway'}\n"
        "- Your FIRST scene must pick up from the previous section's result; your\n"
        "  LAST scene must set up the next section's question.\n"
    )
    prompt = f"""\
You are writing ONE section of a larger video about **{topic}**.

Section: "{section.get('title')}" — goal: {section.get('goal')}
Tension it carries: {section.get('tension') or 'develop the goal with a real complication'}
Time budget: {budget_s}s across about {hint} scenes.
Per-scene narration word budget = estimated_duration_seconds x 2.2.
The scene estimated_duration_seconds in THIS section must sum to about {budget_s}s.

{contract_block}{neighbors_block}
{_STORY_RULES}
{_NARRATION_RULES}
{_GROUNDING_RULES}
{_SCENE_RULES}
- Do NOT write a title card or outro — those belong to other sections.
- Number scenes locally starting at 1 (they will be renumbered globally).

{_writer_format_block(with_title=False)}
"""
    _, scenes = await _call_writer(
        client,
        "You are an expert writer-director for educational video. Follow the requested output format exactly.",
        prompt, temperature=0.5, max_tokens=6000,
    )
    return scenes


async def _coherence_pass(topic: str, title: str, scenes: List[Dict[str, Any]],
                          style_contract: Optional[Dict[str, Any]], client) -> List[Dict[str, Any]]:
    """One cheap pass over the assembled script to stitch section seams.

    Section writers work in parallel and can't see each other's actual prose —
    only goals. This pass fixes broken transitions and terminology drift
    WITHOUT restructuring: it may only rewrite narration_text (and lightly
    adjust titles); ids, types, visuals and durations are preserved.
    """
    compact = [
        {"scene_id": s.get("scene_id"), "title": s.get("title"),
         "narration_text": s.get("narration_text", "")}
        for s in scenes
    ]
    prompt = f"""\
You are the showrunner doing the final read-through of a video script about
**{topic}** (title: "{title}"), assembled from sections written in parallel.
{f'Style contract: {json.dumps(style_contract, ensure_ascii=False)}' if style_contract else ''}

Fix ONLY these, by rewriting narration_text where needed:
1. Transitions: every scene must open from the previous scene's result (a
   connective thought, not a cold restart). Rewrite openings that restart.
2. Terminology drift: one concept must use one term everywhere.
3. Duplicate explanations across section seams: trim the second telling.
4. The first scene must pose the hook; the last must reframe it. Sharpen both.
Keep each rewritten narration within ~10% of its original word count (timing
is already budgeted). Do NOT add, remove, or reorder scenes.

Scenes (JSON): {json.dumps(compact, ensure_ascii=False)}

Return ONLY valid JSON: {{"scenes": [{{"scene_id": 1, "narration_text": "..."}}]}}
— include ONLY the scenes you actually changed.
"""
    try:
        data = await _call_json(
            client, "You are a showrunner. Always respond with valid JSON only.",
            prompt, temperature=0.4, max_tokens=8000,
        )
    except Exception as e:  # noqa: BLE001 — coherence is an enhancement, never fatal
        logger.warning("Coherence pass failed; keeping stitched script", extra={"error": str(e)})
        return scenes
    fixes = {f.get("scene_id"): f.get("narration_text")
             for f in (data.get("scenes") or []) if isinstance(f, dict)}
    changed = 0
    for s in scenes:
        fix = fixes.get(s.get("scene_id"))
        if fix and str(fix).strip():
            s["narration_text"] = str(fix).strip()
            changed += 1
    logger.info("Coherence pass applied", extra={"scenes_changed": changed})
    return scenes


async def _full_council(topic: str, brief: Dict[str, Any], client) -> Tuple[str, List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    plan = await _planner(topic, brief, client)
    title = str(plan.get("title") or topic)
    sections = [s for s in (plan.get("sections") or []) if isinstance(s, dict)]
    if not sections:
        t, s = await _single_writer(topic, brief, client)
        return t, s, None
    style_contract = plan.get("style_contract") if isinstance(plan.get("style_contract"), dict) else None

    sem = asyncio.Semaphore(settings.COUNCIL_MAX_PARALLEL_WRITERS)

    async def _write(idx: int, sec: Dict[str, Any]):
        prev_s = sections[idx - 1] if idx > 0 else None
        next_s = sections[idx + 1] if idx < len(sections) - 1 else None
        async with sem:
            # One retry per section, then a HARD failure marker. A silently
            # empty section used to ship a video with a hole in the story.
            for attempt in (1, 2):
                try:
                    got = await _section_writer(topic, brief, sec, client,
                                                style_contract, prev_s, next_s)
                    if got:
                        return got
                    logger.warning("Section writer returned no scenes",
                                   extra={"section": sec.get("title"), "attempt": attempt})
                except Exception as e:  # noqa: BLE001
                    logger.warning("Section writer failed",
                                   extra={"section": sec.get("title"),
                                          "attempt": attempt, "error": str(e)})
            return None  # hard failure marker

    results = await asyncio.gather(*(_write(i, s) for i, s in enumerate(sections)))

    if any(r is None for r in results):
        # A section is missing — a gap in the story is worse than a simpler
        # script. Fall back to one coherent single-writer pass for the WHOLE
        # video rather than shipping a hole.
        failed = [sections[i].get("title") for i, r in enumerate(results) if r is None]
        logger.error("Council sections failed after retry; falling back to single writer",
                     extra={"failed_sections": failed})
        t, s = await _single_writer(topic, brief, client)
        return t, s, style_contract

    hook = plan.get("hook") if isinstance(plan.get("hook"), dict) else {}
    takeaway = plan.get("takeaway") if isinstance(plan.get("takeaway"), dict) else {}
    intro = {
        "title": title[:60], "content_type": "hyperframes",
        "narration_text": str(hook.get("narration") or "").strip()
        or f"Here's a question worth {max(1, int(brief.get('target_duration_seconds', 300) / 60))} minutes of your time: {topic}?",
        "visual_description": str(hook.get("visual") or "").strip()
        or f"kinetic-statement: the hook question as full-frame typography, key word emphasized. Title: '{title}'.",
        "estimated_duration_seconds": 7,
    }
    outro = {
        "title": "The Takeaway", "content_type": "hyperframes",
        "narration_text": str(takeaway.get("narration") or "").strip()
        or "So that's the real answer to where we started - and why it matters.",
        "visual_description": str(takeaway.get("visual") or "").strip()
        or "kinetic-statement: the takeaway line as full-frame typography, calm exit.",
        "estimated_duration_seconds": 8,
    }
    scenes: List[Dict[str, Any]] = [intro]
    for section_scenes in results:
        scenes.extend(section_scenes)
    scenes.append(outro)
    return title, scenes, style_contract


# ── Reviewer / fix / repair ───────────────────────────────────────────────────
async def _reviewer(topic: str, brief: Optional[Dict[str, Any]], scenes: List[Dict[str, Any]], client) -> Dict[str, Any]:
    # FULL narration + visual_description — scripts are small and a reviewer
    # that sees a 200-char stub judging "narration quality" is theater.
    compact = [
        {"scene_id": s.get("scene_id"), "type": s.get("content_type"),
         "title": s.get("title"), "narration_text": s.get("narration_text", ""),
         "visual_description": s.get("visual_description", ""),
         "est_s": s.get("estimated_duration_seconds")}
        for s in scenes
    ]
    target = (brief or {}).get("target_duration_seconds")
    prompt = f"""\
You are a demanding showrunner reviewing a script for a video about **{topic}**.
{f'Target length: {target}s.' if target else ''}

Scenes (JSON): {json.dumps(compact, ensure_ascii=False)}

Score 1-5 on each dimension (5 = excellent):
- hook: does scene 1 pose a concrete question/stake (5) or announce/define the topic (1)?
- narrative_thread: does each scene open from the previous one's result, with at
  least one real and-but-therefore turn — or is it a reorderable fact list?
- one_idea_per_scene: exactly one new idea per scene, or crowded scenes?
- concreteness: specific examples/numbers before abstractions; magnitudes anchored
  to tangible comparisons?
- complementarity: do visuals SHOW what narration can't say, or does on-screen
  text just transcribe the narration?
- visual_grammar: manim shot specs with motion-that-means + hyperframes scenes
  naming real layout archetypes — or centered-title-and-bullets slideware?
- pacing: word counts ~2.2x duration, scenes 15-45s, varied sentence rhythm?
- prose_flow: does narration read as connected spoken prose a teacher would
  say aloud (consequence/contrast links, varied sentence lengths) — or
  telegraphic fragment chains and number ledgers ("Max 7. Max 11. Shift.")?
- depth: does each idea get what-it-is, why-it-works, AND why-it-matters in
  its scene — or are facts stated and abandoned?

For the WORST scenes (max 5), give a concrete, per-scene REWRITE suggestion: name
the scene_id, the specific problem, and how to rewrite that scene's narration
and/or visual (be specific enough that a writer could act on it directly — not
"make it better"). Also list coverage gaps and any scene whose content_type is
wrong (a visual/math beat marked hyperframes, or a pure-text beat marked manim).

Mark high_severity = true if ANY score <= 2, OR any issue would materially hurt
the video (a broken hook, a reorderable fact-list thread, a wrong content_type,
visuals that just transcribe narration). verdict = "revise" whenever
high_severity is true.

Return ONLY valid JSON:
{{
  "scores": {{"hook": 4, "narrative_thread": 3, "one_idea_per_scene": 4,
              "concreteness": 3, "complementarity": 4, "visual_grammar": 3,
              "pacing": 4, "prose_flow": 4, "depth": 3}},
  "coverage_issues": ["..."],
  "scene_rewrites": [{{"scene_id": 2, "problem": "...", "rewrite": "..."}}],
  "narration_issues": [{{"scene_id": 2, "fix": "..."}}],
  "visual_issues": [{{"scene_id": 4, "fix": "..."}}],
  "type_issues": [{{"scene_id": 3, "should_be": "manim"}}],
  "high_severity": false,
  "verdict": "ok" | "revise"
}}
"""
    # One retry: a reviewer that silently returns "ok" on an exception ships
    # unreviewed scripts (observed in production — meta carried no scores and
    # nobody knew). The failure must at least be loud and marked in meta.
    for attempt in (1, 2):
        try:
            return await _call_json(
                client, "You are a demanding showrunner. Always respond with valid JSON only.",
                prompt, temperature=0.3, max_tokens=3000,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("Reviewer failed", extra={"attempt": attempt, "error": str(e)})
    logger.error("Reviewer failed twice; script ships UNREVIEWED")
    return {"verdict": "ok", "reviewer_failed": True}


async def _writer_fix(topic: str, brief: Optional[Dict[str, Any]], scenes: List[Dict[str, Any]], critique: Dict[str, Any], client) -> List[Dict[str, Any]]:
    # Show the current script in the SAME format the model must reply in —
    # models edit far more reliably when input and output formats match.
    current = (mds.scenes_to_markdown(None, scenes) if _md_mode()
               else json.dumps(scenes, ensure_ascii=False))
    prompt = f"""\
Revise this video script about **{topic}** to address the reviewer's critique.
Keep what works; fix what's flagged. Preserve the overall structure and the
first/last scenes as hyperframes.

Current script:
{current}

Reviewer critique (JSON): {json.dumps(critique, ensure_ascii=False)}

{_budget_block(brief)}
{_writer_format_block(with_title=False)}
"""
    try:
        _, new_scenes = await _call_writer(
            client, "You are an expert writer-director. Follow the requested output format exactly.",
            prompt, temperature=0.6, max_tokens=8000,
        )
        return new_scenes or scenes
    except Exception as e:  # noqa: BLE001
        logger.warning("Writer-fix failed; keeping pre-fix script", extra={"error": str(e)})
        return scenes


async def _repair(topic: str, scenes: List[Dict[str, Any]], budgets: List[Dict[str, Any]], target: int, client) -> List[Dict[str, Any]]:
    current = (mds.scenes_to_markdown(None, scenes) if _md_mode()
               else json.dumps(scenes, ensure_ascii=False))
    prompt = f"""\
The script for **{topic}** is off its {target}s duration budget. Rewrite the
narration so each scene matches its per-scene word target below. Do NOT add or
remove scenes; keep scene numbering, titles, TYPE, and VISUAL unchanged. Only
adjust the narration length.

Per-scene word targets (JSON): {json.dumps(budgets, ensure_ascii=False)}

Current script:
{current}

For each scene, rewrite narration_text to about its target_words words, then set
estimated_duration_seconds = round(target_words / 2.2). Do not use any other
duration number — words and duration must agree.
Preserve the connected spoken-prose style while resizing: when trimming, cut
redundancy and repeated walks, never clip sentences into fragments; when
expanding, deepen the why-it-works and why-it-matters — never add filler.
{_writer_format_block(with_title=False)}
"""
    try:
        _, new_scenes = await _call_writer(
            client, "You are an expert writer-director. Follow the requested output format exactly.",
            prompt, temperature=0.5, max_tokens=8000,
        )
        return new_scenes or scenes
    except Exception as e:  # noqa: BLE001
        logger.warning("Duration repair failed; keeping pre-repair script", extra={"error": str(e)})
        return scenes


# ── Orchestration ──────────────────────────────────────────────────────────────
async def generate_script(topic: str, brief: Optional[Dict[str, Any]], client) -> Tuple[ScriptResponse, Dict[str, Any]]:
    target = (brief or {}).get("target_duration_seconds")
    # Enforce the analyzer's ceiling server-side — the brief may arrive with a
    # target above max_duration_seconds (older clients, hand-built requests).
    mx = (brief or {}).get("max_duration_seconds")
    if target and mx and target > mx:
        logger.warning("Clamping target duration to analyzer max",
                       extra={"target": target, "max": mx})
        target = mx
        brief = {**(brief or {}), "target_duration_seconds": target}
    is_study = bool((brief or {}).get("is_study_material"))
    full = bool(brief) and (is_study or (target or 0) > settings.COUNCIL_FULL_THRESHOLD_SECONDS)
    warnings: List[str] = []
    style_contract: Optional[Dict[str, Any]] = None

    if full:
        title, scenes, style_contract = await _full_council(topic, brief, client)
    else:
        title, scenes = await _single_writer(topic, brief, client)
    scenes = _renumber_and_enforce_invariants(scenes)

    # Coherence pass — council scripts only (section writers can't see each
    # other's prose; single-writer output is already one voice).
    if full and len(scenes) > 2:
        scenes = await _coherence_pass(topic, title, scenes, style_contract, client)

    # Reviewer pass — every job. Fix whenever the verdict says revise OR any
    # high-severity signal exists (score <= 2, an explicit high_severity flag, or
    # a wrong content_type) — a reviewer that flags a broken hook but returns
    # verdict "ok" must still trigger a rewrite.
    critique = await _reviewer(topic, brief, scenes, client)
    scores = critique.get("scores") if isinstance(critique.get("scores"), dict) else {}
    any_low_score = any(
        isinstance(v, (int, float)) and v <= 2 for v in scores.values()
    )
    high_severity = (
        str(critique.get("verdict")) == "revise"
        or bool(critique.get("high_severity"))
        or any_low_score
        or bool(critique.get("type_issues"))
    )
    if high_severity:
        scenes = await _writer_fix(topic, brief, scenes, critique, client)
        scenes = _renumber_and_enforce_invariants(scenes)

    meta: Dict[str, Any] = {"mode": "council" if full else "single", "warnings": warnings}
    if critique.get("reviewer_failed"):
        warnings.append("reviewer failed twice — script shipped unreviewed")
    if isinstance(critique.get("scores"), dict):
        meta["review_scores"] = critique["scores"]
    if style_contract:
        meta["style_contract"] = style_contract

    # Duration audit (+ one repair) when a target is known. Clamp FIRST, then
    # audit, then decide — clamp only ever raises est up to ceil(narration_s), so
    # a within-tolerance verdict taken before clamping can lie and pacing then
    # silently overshoots. Every audit below reflects post-clamp reality.
    if target:
        budget.clamp_durations(scenes)
        report = budget.audit(scenes, target)
        if not report["within_tolerance"]:
            repaired = await _repair(topic, scenes, budget.repair_budgets(scenes, target), target, client)
            repaired = _renumber_and_enforce_invariants(repaired)
            budget.clamp_durations(repaired)
            rep_report = budget.audit(repaired, target)
            if abs(rep_report["deviation_pct"]) < abs(report["deviation_pct"]):
                scenes, report = repaired, rep_report
            if not report["within_tolerance"]:
                warnings.append(f"duration off-budget by {report['deviation_pct']}% after repair")
        meta["duration_audit"] = report  # post-clamp truth

    script = ScriptResponse(title=title, scenes=scenes)
    return script, meta
