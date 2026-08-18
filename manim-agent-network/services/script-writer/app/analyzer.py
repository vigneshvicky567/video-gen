"""Topic analysis for the pre-submit questionnaire.

Stateless: takes a raw topic, returns a TopicAnalysis (feasibility statement +
recommended/max duration + 3-5 selectable questions). One LLM call; any failure
falls back to a static default so the questionnaire modal always renders.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from shared.config import settings
from shared.log import get_logger
from shared.schemas.common import (
    AnalyzeQuestion,
    QuestionOption,
    TopicAnalysis,
)

logger = get_logger(__name__)

# Hard bounds — never trust LLM numbers.
_MIN_RECOMMENDED = 120
# Study-material scope needs room: a course/tutorial clamped to the 120s generic
# floor would still route to the heavy full-council path and come out thin and
# over-sectioned. Give it a matching minimum recommended length.
_STUDY_MIN_RECOMMENDED = 600
_MAX_RECOMMENDED = 1800
_MAX_DURATION_CEILING = 2400  # matches GenerationBrief target_duration_seconds le=2400

# An "AI decides" choice is prepended to every single-select, non-duration
# question so it is the DEFAULT and the creator can defer the fork to the model
# instead of being forced to pick. The frontend maps a selection of this exact
# label to "no answer" (omitted from the brief), so the writer decides freely.
AI_DECIDE_LABEL = "Decide for me"


def _inject_ai_decide(questions: "List[AnalyzeQuestion]") -> "List[AnalyzeQuestion]":
    """Prepend an 'AI decides' option to each single-select, non-duration
    question. Multi-select questions already mean 'AI decides' when left empty,
    so they're untouched. Idempotent — skips a question that already has it."""
    out: List[AnalyzeQuestion] = []
    for q in questions:
        if q.id == "duration" or q.multi_select or not q.options:
            out.append(q)
            continue
        if any(o.label.strip().lower() == AI_DECIDE_LABEL.lower() for o in q.options):
            out.append(q)
            continue
        ai = QuestionOption(label=AI_DECIDE_LABEL, description="let the model pick what fits this topic")
        out.append(q.model_copy(update={"options": [ai] + list(q.options)}))
    return out


def build_analyze_prompt(topic: str) -> str:
    return f"""You are a senior video producer running intake for ONE specific explainer video. Design a SHORT, SHARP questionnaire: every question must resolve a real fork that changes how THIS video gets made. Terse strings, no padding.

Topic (this may be a long, messy, or pasted brief — read it, don't echo it):
\"\"\"{topic}\"\"\"

STEP 1 — TITLE. Write `title`: a clean, plain-English title of what was actually asked, <= 90 characters, at most two short lines. If the topic is a long or rambling brief, ABSTRACT it down to the core subject — never copy the raw text, never include instructions, code, or timestamps. Example: a 600-word brief about a goalkeeper's World Cup heroics -> "Vozinha's World Cup Shutout vs Spain".

STEP 2 — QUESTIONS. Decide what is genuinely UNDECIDED. A great question resolves a fork that sends the script in a visibly different direction. A dumb question asks what a sensible default already settles, or what the topic already states.

Every non-duration question MUST pass ALL THREE tests:
1. Decision-changing — two different answers yield visibly different scripts.
2. Not inferable — the topic text doesn't already imply the answer.
3. One-tap — 2-4 concrete options a non-expert picks instantly.

Pick only the forks that matter for THIS topic (never ask all). Good axes:
- Angle / framing (history vs how-it-works vs why-it-matters)
- Depth vs breadth
- Concrete-examples-first vs theory-first
- What to deliberately EXCLUDE / assumed prior knowledge
- Which sub-system or case study to center on
- Tone (rigorous vs playful) — only when the topic truly supports both

OPTION QUALITY:
- Each option is a distinct DIRECTION, not a synonym of another. If two options would yield the same script, cut one.
- Labels 1-4 words, concrete and self-explanatory. Descriptions: empty string "".
- NEVER add a "no preference", "either", "doesn't matter", "decide for me", or "let the AI decide" option — the system appends that automatically. Adding your own is a duplicate.

ANTI-PATTERNS — never ask as rote filler:
- "Who is the audience?" UNLESS the topic genuinely splits (skip if it says "for beginners", "ELI5", "for experts", etc.).
- Generic "what to focus on?" with vague options.
- Anything the recommended default already answers.
- Two questions resolving the same fork.

GOOD vs DUMB (topic "How RSA encryption works"):
- DUMB: "Who is this for? [Beginner / Advanced]"  ← topic implies a curious general audience.
- GREAT: "Show the math or keep it intuitive? [Walk the modular arithmetic / Intuition + analogies only / Light math, mostly intuition]"  ← changes every scene.

Reserved ids — use these EXACT ids ONLY when that axis is the real fork, so answers map cleanly: "audience" (audience level), "focus" (multi-select sub-areas), "style" (visual style), "pacing". For any other axis, invent a short snake_case id (e.g. "math_depth", "angle").

Return ONLY valid JSON, exactly this shape:
{{
  "title": "Clean <=90-char plain-English title of what was asked.",
  "feasibility_summary": "ONE sentence stating the sensible scope WITH a min-max minute range and a recommendation.",
  "recommended_duration_seconds": 300,
  "max_duration_seconds": 1200,
  "is_study_material": false,
  "topic_classification": "concept-explainer | course/tutorial | overview | walkthrough",
  "duration_presets": [180, 300, 600, 900],
  "questions": [
    {{"id": "duration", "question": "How long should the video be?", "header": "Target length", "options": [{{"label": "5 min", "description": ""}}, {{"label": "10 min", "description": ""}}], "multi_select": false, "allows_custom": true}},
    {{"id": "<topic-specific>", "question": "<a fork that matters for THIS topic>", "header": "<2-3 words>", "options": [{{"label": "<concrete>", "description": ""}}], "multi_select": false, "allows_custom": true}}
  ]
}}

Rules (tight):
- duration question FIRST, always (id "duration"). 3-4 questions total INCLUDING duration — design the other 2-3 for this topic.
- Option labels 1-4 words; descriptions empty "".
- is_study_material = true ONLY for skill-learning courses ("learn X", "master Y"); false for single concepts.
- study material -> recommend 600-1500s; single concept -> 180-420s. max >= recommended.
- duration_presets: 3-4 ascending seconds, all <= max.
"""


def _clamp(value: Any, lo: int, hi: int, default: int) -> int:
    try:
        v = int(round(float(value)))
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def _coerce_question(raw: Any) -> AnalyzeQuestion | None:
    if not isinstance(raw, dict):
        return None
    options: List[QuestionOption] = []
    for opt in raw.get("options", []) or []:
        if isinstance(opt, dict) and opt.get("label"):
            options.append(
                QuestionOption(
                    label=str(opt["label"])[:60],
                    description=str(opt.get("description", ""))[:160],
                )
            )
        elif isinstance(opt, str) and opt:
            options.append(QuestionOption(label=opt[:60]))
    qid = str(raw.get("id") or "").strip() or "q"
    question = str(raw.get("question") or "").strip()
    header = str(raw.get("header") or qid.title())[:24]
    if not question or len(options) < 2:
        return None
    return AnalyzeQuestion(
        id=qid,
        question=question,
        header=header,
        options=options[:4],
        multi_select=bool(raw.get("multi_select", False)),
        allows_custom=bool(raw.get("allows_custom", True)),
    )


def _duration_question(presets: List[int], recommended: int) -> AnalyzeQuestion:
    opts: List[QuestionOption] = []
    for sec in presets:
        mins = sec / 60.0
        label = f"{int(mins)} min" if abs(mins - round(mins)) < 0.05 else f"{mins:.1f} min"
        desc = "Recommended" if sec == recommended else ""
        opts.append(QuestionOption(label=label, description=desc))
    return AnalyzeQuestion(
        id="duration",
        question="How long should the video be?",
        header="Target length",
        options=opts[:4] if len(opts) >= 2 else opts + [QuestionOption(label="Custom")],
        multi_select=False,
        allows_custom=True,
    )


def _clean_summary(text: str, max_chars: int = 240) -> str:
    """Models sometimes dump chain-of-thought into feasibility_summary. Keep the
    leading sentence(s) up to a hard char cap so the modal banner stays tight."""
    text = " ".join((text or "").split())
    if not text:
        return ""
    out = ""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        candidate = (out + " " + sentence).strip() if out else sentence
        if len(candidate) > max_chars:
            break
        out = candidate
    if not out:                      # first sentence already over the cap
        out = text[:max_chars].rstrip()
    return out


def _make_title(raw_title: Any, topic: str, max_chars: int = 90) -> str:
    """Clean the LLM-supplied title; fall back to an abstract of the topic.
    Never echoes a long raw prompt verbatim — caps at max_chars on a word
    boundary so a giant pasted brief becomes a short, displayable title."""
    t = " ".join(str(raw_title or "").split())
    if not t:                        # no/blank LLM title -> abstract from topic
        collapsed = " ".join((topic or "").split())
        first = re.split(r"(?<=[.!?])\s+", collapsed)[0] if collapsed else ""
        t = first or collapsed
    if len(t) > max_chars:
        t = t[:max_chars].rsplit(" ", 1)[0].rstrip(" ,;:-") + "…"
    return t or "Untitled"


def normalize_analysis(raw: Dict[str, Any], topic: str) -> TopicAnalysis:
    """Apply programmatic clamps and structural guarantees to LLM output."""
    is_study = bool(raw.get("is_study_material", False))
    # Study material routes to the heavy full-council path (over-sectioned, thin
    # scenes) if it lands at the generic 120s floor. Raise the recommended/min
    # floor so the budget matches study-material scope.
    rec_floor = _STUDY_MIN_RECOMMENDED if is_study else _MIN_RECOMMENDED
    recommended = _clamp(
        raw.get("recommended_duration_seconds"), rec_floor, _MAX_RECOMMENDED, max(rec_floor, 300)
    )
    max_dur = _clamp(
        raw.get("max_duration_seconds"), recommended, _MAX_DURATION_CEILING, max(recommended, 1200)
    )
    if max_dur < recommended:
        max_dur = recommended

    # Presets: sanitize, sort, dedupe, clamp to [120, max_dur].
    presets_raw = raw.get("duration_presets") or []
    presets: List[int] = []
    for p in presets_raw:
        try:
            v = int(round(float(p)))
        except (TypeError, ValueError):
            continue
        if 120 <= v <= max_dur:
            presets.append(v)
    presets = sorted(set(presets))
    if len(presets) < 2:
        presets = sorted(set(
            v for v in [180, 300, 600, min(900, max_dur), recommended] if 120 <= v <= max_dur
        ))
    if recommended not in presets and len(presets) < 4:
        presets = sorted(set(presets + [recommended]))
    presets = presets[:4]

    # Questions: coerce, ensure a duration question exists (first), 3-5 total.
    questions: List[AnalyzeQuestion] = []
    has_duration = False
    for rq in raw.get("questions", []) or []:
        q = _coerce_question(rq)
        if q is None:
            continue
        if q.id == "duration":
            has_duration = True
            q = _duration_question(presets, recommended)  # always rebuild from clamped presets
        questions.append(q)
    if not has_duration:
        questions.insert(0, _duration_question(presets, recommended))
    else:
        # move the duration question to the front
        questions.sort(key=lambda q: 0 if q.id == "duration" else 1)
    questions = questions[:5]
    while len(questions) < 3:
        questions.append(_default_questions(recommended, max_dur, presets)[len(questions)])

    return TopicAnalysis(
        topic=topic,
        title=_make_title(raw.get("title"), topic),
        feasibility_summary=_clean_summary(raw.get("feasibility_summary"))
        or f"This topic sensibly supports a {presets[0] // 60}-{max_dur // 60} minute video.",
        recommended_duration_seconds=recommended,
        max_duration_seconds=max_dur,
        duration_presets=presets,
        is_study_material=is_study,
        topic_classification=str(raw.get("topic_classification") or "concept-explainer")[:40],
        questions=_inject_ai_decide(questions),
        degraded=False,
    )


def _default_questions(recommended: int, max_dur: int, presets: List[int]) -> List[AnalyzeQuestion]:
    return [
        _duration_question(presets, recommended),
        AnalyzeQuestion(
            id="audience",
            question="Who is this for?",
            header="Audience",
            options=[
                QuestionOption(label="Complete beginner", description="No prior background"),
                QuestionOption(label="Some experience", description="Knows the basics"),
                QuestionOption(label="Advanced", description="Wants depth fast"),
            ],
            multi_select=False,
            allows_custom=True,
        ),
        AnalyzeQuestion(
            id="style",
            question="Visual style and pacing?",
            header="Style",
            options=[
                QuestionOption(label="Diagram-heavy, steady", description="More visuals, measured pace"),
                QuestionOption(label="Text-forward, brisk", description="Slides and bullets, fast pace"),
                QuestionOption(label="Balanced", description="Mix of visuals and text"),
            ],
            multi_select=False,
            allows_custom=True,
        ),
    ]


def default_analysis(topic: str) -> TopicAnalysis:
    """Static fallback used when the LLM analysis fails (degraded=True)."""
    recommended, max_dur = 300, 1200
    presets = [180, 300, 600, 900]
    return TopicAnalysis(
        topic=topic,
        title=_make_title(None, topic),
        feasibility_summary=(
            "This topic sensibly supports a 3-20 minute video; about 5 minutes is a "
            "solid default. (Automatic analysis was unavailable — pick what fits.)"
        ),
        recommended_duration_seconds=recommended,
        max_duration_seconds=max_dur,
        duration_presets=presets,
        is_study_material=False,
        topic_classification="concept-explainer",
        questions=_inject_ai_decide(_default_questions(recommended, max_dur, presets)),
        degraded=True,
    )


async def analyze_topic(topic: str, client) -> TopicAnalysis:
    try:
        response = await client.chat.completions.acreate(
            model=settings.SCRIPT_WRITER_MODEL,
            messages=[
                {"role": "system", "content": "You are a video production strategist. Always respond with valid JSON only."},
                {"role": "user", "content": build_analyze_prompt(topic)},
            ],
            temperature=0.6,
            response_format={"type": "json_object"},
            max_tokens=1200,
        )
        content = response.choices[0].message.content
        return normalize_analysis(json.loads(content), topic)
    except Exception as e:  # noqa: BLE001 — fall back, never fail the modal
        logger.warning("Topic analysis failed, using default", extra={"error": str(e)})
        return default_analysis(topic)
