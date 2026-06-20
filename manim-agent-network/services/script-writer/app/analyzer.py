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
_MAX_RECOMMENDED = 1800
_MAX_DURATION_CEILING = 2400  # matches GenerationBrief target_duration_seconds le=2400


def build_analyze_prompt(topic: str) -> str:
    return f"""You are a senior video producer running intake for ONE specific video. Design a short, SHARP questionnaire: every question's answer must change how THIS video gets made. Be terse — short strings, no padding.

Topic: **{topic}**

First decide what is genuinely UNDECIDED about this topic. A great question resolves a real fork that sends the script in a different direction. A dumb question asks what a sensible default already answers, or what the topic text already tells you.

Every non-duration question MUST pass all three tests:
1. Decision-changing — two different answers yield visibly different scripts.
2. Not inferable — the topic text doesn't already imply the answer.
3. One-tap — 2-4 concrete options a non-expert picks instantly.

Choose the forks that actually matter for THIS topic. Good axes to draw from (pick what fits — never ask all):
- Angle / framing (history vs how-it-works vs why-it-matters)
- Depth-vs-breadth tradeoff
- Concrete-examples-first vs theory-first
- What to deliberately EXCLUDE / assumed prior knowledge
- Which sub-system or case study to center on
- Tone (rigorous vs playful) when the topic genuinely supports both

ANTI-PATTERNS — never ask as rote filler:
- "Who is the audience?" UNLESS the topic truly splits (skip if topic already says "for beginners", "ELI5", "for experts", etc.).
- Generic "what to focus on?" with vague options.
- Anything the recommended default already answers.
- Two questions resolving the same fork.

GOOD vs DUMB (topic "How RSA encryption works"):
- DUMB: "Who is this for? [Beginner / Advanced]"  ← topic implies a curious general audience.
- GREAT: "Show the math or keep it intuitive? [Walk the modular arithmetic / Intuition + analogies only / Light math, mostly intuition]"  ← genuinely changes every scene.

Reserved ids — use these EXACT ids when (and only when) that axis is the real fork, so answers map cleanly: "audience" (audience level), "focus" (multi-select sub-areas), "style" (visual style), "pacing". For any other axis, invent a short snake_case id (e.g. "math_depth", "angle").

Return ONLY valid JSON, exactly this shape:
{{
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

Rules (keep it tight):
- duration question FIRST, always (id "duration"). 3-4 questions total INCLUDING duration — design the other 2-3 for this topic.
- Option labels: 1-4 words, concrete. Descriptions: empty string "" (omit prose).
- is_study_material = true only for skill-learning courses ("learn X", "master Y"); false for single concepts.
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


def normalize_analysis(raw: Dict[str, Any], topic: str) -> TopicAnalysis:
    """Apply programmatic clamps and structural guarantees to LLM output."""
    recommended = _clamp(
        raw.get("recommended_duration_seconds"), _MIN_RECOMMENDED, _MAX_RECOMMENDED, 300
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
        feasibility_summary=_clean_summary(raw.get("feasibility_summary"))
        or f"This topic sensibly supports a {presets[0] // 60}-{max_dur // 60} minute video.",
        recommended_duration_seconds=recommended,
        max_duration_seconds=max_dur,
        duration_presets=presets,
        is_study_material=bool(raw.get("is_study_material", False)),
        topic_classification=str(raw.get("topic_classification") or "concept-explainer")[:40],
        questions=questions,
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
        feasibility_summary=(
            "This topic sensibly supports a 3-20 minute video; about 5 minutes is a "
            "solid default. (Automatic analysis was unavailable — pick what fits.)"
        ),
        recommended_duration_seconds=recommended,
        max_duration_seconds=max_dur,
        duration_presets=presets,
        is_study_material=False,
        topic_classification="concept-explainer",
        questions=_default_questions(recommended, max_dur, presets),
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
