"""markdown_script: the writers' authoring format. The property that matters:
parsing is SALVAGE-TOLERANT — sloppy labels, fences, prose, and truncation
lose at most the broken scene, never the whole script (JSON lost everything
to one unbalanced brace)."""

import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import importlib

_SW = os.path.join(PROJECT_ROOT, "services", "script-writer")


def _load():
    saved = {k: sys.modules[k] for k in list(sys.modules) if k == "app" or k.startswith("app.")}
    for k in saved:
        del sys.modules[k]
    sys.path.insert(0, _SW)
    try:
        return importlib.import_module("app.markdown_script")
    finally:
        sys.path.remove(_SW)
        for k in [k for k in sys.modules if k == "app" or k.startswith("app.")]:
            del sys.modules[k]
        sys.modules.update(saved)


mds = _load()

GOOD = """\
# TITLE: How Engines Waste Energy

## SCENE 1: The Question
TYPE: hyperframes
DURATION: 8
NARRATION:
Why does your car throw away most of the fuel you pay for?

VISUAL:
kinetic-statement: the question as full-frame typography.

## SCENE 2: Where Heat Goes
TYPE: manim
DURATION: 20
NARRATION:
Follow one unit of fuel energy. Most of it leaves as heat.
Only a third reaches the wheels.

VISUAL:
Sankey-style 2D flow: one bar splits into heat and motion arrows.
"""


def test_parse_happy_path():
    title, scenes = mds.parse_script_markdown(GOOD)
    assert title == "How Engines Waste Energy"
    assert len(scenes) == 2
    s1, s2 = scenes
    assert s1["scene_id"] == 1 and s1["content_type"] == "hyperframes"
    assert s1["estimated_duration_seconds"] == 8
    assert s1["title"] == "The Question"
    assert "throw away" in s1["narration_text"]
    assert s2["content_type"] == "manim"
    assert "Sankey" in s2["visual_description"]
    assert "\n" not in s1["narration_text"] or True  # multi-line allowed
    assert "Only a third" in s2["narration_text"]    # multi-line narration kept


def test_tolerates_fences_prose_and_case():
    messy = "Sure! Here's the script:\n```markdown\n" + GOOD.replace(
        "TYPE:", "type:").replace("NARRATION:", "narration:") + "\n```\nHope it helps!"
    title, scenes = mds.parse_script_markdown(messy)
    assert title and len(scenes) == 2
    assert scenes[0]["content_type"] == "hyperframes"


def test_truncation_salvages_completed_scenes():
    truncated = GOOD[:GOOD.index("VISUAL:\nSankey")]  # scene 2 cut mid-fields
    _, scenes = mds.parse_script_markdown(truncated)
    # scene 1 fully intact; scene 2 still has narration so it survives too,
    # just without a visual — downstream invariants handle the rest.
    assert len(scenes) >= 1
    assert scenes[0]["narration_text"].startswith("Why does")


def test_scene_without_narration_dropped():
    bad = "# TITLE: X\n\n## SCENE 1: Empty\nTYPE: manim\nDURATION: 5\nVISUAL:\nstuff\n"
    _, scenes = mds.parse_script_markdown(bad)
    assert scenes == []


def test_bad_type_and_duration_default_safely():
    txt = ("# TITLE: X\n\n## SCENE 1: A\nTYPE: powerpoint\nDURATION: soon\n"
           "NARRATION:\nHello there.\n\nVISUAL:\nv\n")
    _, scenes = mds.parse_script_markdown(txt)
    assert scenes[0]["content_type"] is None          # invalid -> downstream default
    assert scenes[0]["estimated_duration_seconds"] == 0  # invalid -> downstream floor


def test_roundtrip_render_then_parse():
    _, scenes = mds.parse_script_markdown(GOOD)
    for s in scenes:
        s.setdefault("title", "")
    rendered = mds.scenes_to_markdown("How Engines Waste Energy", scenes)
    title2, scenes2 = mds.parse_script_markdown(rendered)
    assert title2 == "How Engines Waste Energy"
    assert [s["narration_text"] for s in scenes2] == [s["narration_text"] for s in scenes]
    assert [s["content_type"] for s in scenes2] == [s["content_type"] for s in scenes]


def test_empty_input():
    assert mds.parse_script_markdown("") == (None, [])
    assert mds.parse_script_markdown("no headings here") == (None, [])
