"""Markdown authoring format for script-writer LLM output.

WHY not JSON for the writers: narration is long prose, and JSON forces it into
escaped single-line strings — models audibly write stiffer text inside JSON,
and one truncated/unbalanced brace loses the ENTIRE script. Markdown lets the
model write in its natural register, and this parser is salvage-tolerant: a
reply truncated mid-scene still yields every completed scene.

Structured, machine-judged stages (planner, reviewer) stay JSON — their output
is verdicts/numbers, not prose.

Format (what the LLM is instructed to emit):

    # TITLE: How Engines Waste Energy

    ## SCENE 1: The Question
    TYPE: hyperframes
    DURATION: 8
    NARRATION:
    Why does your car throw away most of the fuel you pay for?

    VISUAL:
    kinetic-statement: the question as full-frame typography...

    ## SCENE 2: ...
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

# Prompt block the writers embed verbatim.
FORMAT_SPEC = """\
Write the script in EXACTLY this Markdown format — no JSON, no code fences,
no commentary before or after:

# TITLE: <video title>

## SCENE 1: <short scene title, 4-6 words>
TYPE: <hyperframes | manim>
DURATION: <integer seconds>
NARRATION:
<the spoken narration — natural prose, multiple sentences allowed>

VISUAL:
<the shot spec — archetype for hyperframes, objects+motion for manim>

## SCENE 2: ...
(repeat for every scene; number scenes sequentially)"""

# Same spec without the title line — section writers author a fragment.
FORMAT_SPEC_SCENES_ONLY = FORMAT_SPEC.replace("# TITLE: <video title>\n\n", "")

_TITLE_RE = re.compile(r"^#\s*TITLE\s*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
_SCENE_HEAD_RE = re.compile(r"^##\s*SCENE\s+(\d+)\s*(?::\s*(.*?))?\s*$",
                            re.IGNORECASE | re.MULTILINE)
_FIELD_LABELS = ("TYPE", "DURATION", "NARRATION", "VISUAL")
_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*$", re.MULTILINE)


def _field_block(chunk: str, label: str) -> str:
    """Value of `label:` inside a scene chunk, running until the next label."""
    m = re.search(rf"^\s*{label}\s*:[ \t]*", chunk, re.IGNORECASE | re.MULTILINE)
    if not m:
        return ""
    rest = chunk[m.end():]
    others = [l for l in _FIELD_LABELS if l != label]
    nxt = re.search(rf"^\s*(?:{'|'.join(others)})\s*:", rest,
                    re.IGNORECASE | re.MULTILINE)
    return (rest[:nxt.start()] if nxt else rest).strip()


def parse_script_markdown(text: str) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """Parse (title, scenes) from a Markdown script reply.

    Tolerant by design: fences stripped, labels case-insensitive, missing
    fields default (renumber/invariants downstream fix types and durations),
    prose before the first heading ignored. A scene missing its NARRATION is
    dropped (nothing to speak); everything parseable survives.
    """
    t = _FENCE_RE.sub("", text or "").strip()
    if not t:
        return None, []

    title_m = _TITLE_RE.search(t)
    title = title_m.group(1).strip() if title_m else None

    heads = list(_SCENE_HEAD_RE.finditer(t))
    scenes: List[Dict[str, Any]] = []
    for i, head in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(t)
        chunk = t[head.end():end]

        narration = _field_block(chunk, "NARRATION")
        if not narration:
            continue  # nothing to speak — unusable scene

        ctype = _field_block(chunk, "TYPE").split()[0].lower() if _field_block(chunk, "TYPE") else ""
        dur_raw = _field_block(chunk, "DURATION")
        dur_m = re.search(r"\d+", dur_raw or "")

        scenes.append({
            "scene_id": int(head.group(1)),
            "title": (head.group(2) or "").strip(),
            "content_type": ctype if ctype in ("hyperframes", "manim") else None,
            "narration_text": narration,
            "visual_description": _field_block(chunk, "VISUAL"),
            "estimated_duration_seconds": int(dur_m.group()) if dur_m else 0,
        })
    return title, scenes


def scenes_to_markdown(title: Optional[str], scenes: List[Dict[str, Any]]) -> str:
    """Render existing scenes back to the authoring format — used to show the
    current script inside fix/repair prompts in the same shape the model must
    reply in (models edit far more reliably when input and output formats match)."""
    out: List[str] = []
    if title:
        out.append(f"# TITLE: {title}\n")
    for s in scenes:
        out.append(f"## SCENE {s.get('scene_id', '?')}: {s.get('title') or ''}".rstrip())
        out.append(f"TYPE: {s.get('content_type') or 'hyperframes'}")
        out.append(f"DURATION: {s.get('estimated_duration_seconds') or 0}")
        out.append("NARRATION:")
        out.append(str(s.get("narration_text") or "").strip())
        out.append("")
        out.append("VISUAL:")
        out.append(str(s.get("visual_description") or "").strip())
        out.append("")
    return "\n".join(out).strip() + "\n"
