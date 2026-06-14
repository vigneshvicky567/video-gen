"""Regression tests for H3: caption safe-zone check must honor positional buff.

Manim CE's ``to_edge(edge, buff=...)`` / ``to_corner(corner, buff=...)`` accept
buff as the SECOND POSITIONAL arg. The AST check previously read buff only from
node.keywords, so idiomatic ``.to_edge(DOWN, 1.5)`` / ``.to_corner(DR, 2.0)``
left buff_kw=None and was wrongly flagged — failing valid scenes and burning the
orchestrator retry budget.

Flagging policy under test:
  - no buff supplied (keyword or positional) -> FLAG
  - resolved numeric buff < 1.2            -> FLAG
  - resolved numeric buff >= 1.2           -> OK
"""

import importlib.util
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (
    os.path.join(_REPO_ROOT, "services", "validator"),
    os.path.join(_REPO_ROOT, "services", "code-generator"),
    _REPO_ROOT,
):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _preflight():
    path = os.path.join(_REPO_ROOT, "services", "validator", "app", "main.py")
    spec = importlib.util.spec_from_file_location("_validator_main", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._preflight_ast_checks


_HEAD = "from manim import *\nclass S(Scene):\n    def construct(self):\n        "


def _src(call):
    return _HEAD + call + "\n"


def _flagged(call):
    ok, err = _preflight()(_src(call), scene_id=1)
    is_caption = "caption safe-zone" in err
    # The snippet must be otherwise clean so only the caption rule can fail it.
    assert ok or is_caption, f"unexpected non-caption failure: {err}"
    return is_caption


# ── positional buff (the regression) — must NOT be flagged ───────────────────
def test_positional_buff_to_edge_not_flagged():
    assert not _flagged("Text('hi').to_edge(DOWN, 1.5)")


def test_positional_buff_to_corner_not_flagged():
    assert not _flagged("Text('hi').to_corner(DR, 2.0)")


# ── keyword buff — must NOT be flagged ───────────────────────────────────────
def test_keyword_buff_not_flagged():
    assert not _flagged("Text('hi').to_edge(DOWN, buff=1.5)")


# ── small buff (< 1.2) — must be flagged, positional and keyword ─────────────
def test_small_positional_buff_flagged():
    assert _flagged("Text('hi').to_edge(DOWN, 0.5)")


def test_small_keyword_buff_flagged():
    assert _flagged("Text('hi').to_corner(DL, buff=0.3)")


# ── missing buff entirely — must be flagged ──────────────────────────────────
def test_missing_buff_flagged():
    assert _flagged("Text('hi').to_edge(DOWN)")
