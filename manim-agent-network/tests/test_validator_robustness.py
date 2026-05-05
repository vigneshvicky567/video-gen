"""Tests for validator robustness fixes.

Covers:
- Adaptive timeout computation
- AST preflight catches deprecated APIs
- Self-test source actually triggers preflight
- Sanitizer rewrites ShowCreation
"""
import sys
import os

# Ensure services dirs are importable when tests run from repo root.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO_ROOT, "services", "validator"))
sys.path.insert(0, os.path.join(_REPO_ROOT, "services", "code-generator"))
sys.path.insert(0, _REPO_ROOT)


def _import_validator_helpers():
    """Import validator main module without triggering FastAPI startup."""
    from app.main import _compute_timeout, _preflight_ast_checks, _SELF_TEST_BAD_SOURCE
    return _compute_timeout, _preflight_ast_checks, _SELF_TEST_BAD_SOURCE


def test_compute_timeout_floor():
    _compute_timeout, _, _ = _import_validator_helpers()
    assert _compute_timeout("") == 90
    assert _compute_timeout("x = 1\n") == 90


def test_compute_timeout_per_play():
    _compute_timeout, _, _ = _import_validator_helpers()
    src = "from manim import *\n" + "self.play(x)\n" * 5
    # 90 + 20 * 5 = 190
    assert _compute_timeout(src) == 190


def test_compute_timeout_cap():
    _compute_timeout, _, _ = _import_validator_helpers()
    src = "from manim import *\n" + "self.play(x)\n" * 100
    assert _compute_timeout(src) == 600


def test_compute_timeout_syntax_error_returns_floor():
    _compute_timeout, _, _ = _import_validator_helpers()
    assert _compute_timeout("def broken(:\n") == 90


def test_preflight_catches_show_creation():
    _, _preflight, _ = _import_validator_helpers()
    src = "from manim import *\nclass S(Scene):\n    def construct(self):\n        ShowCreation(x)\n"
    ok, err = _preflight(src, scene_id=1)
    assert ok is False
    assert "ShowCreation" in err


def test_preflight_catches_legacy_import():
    _, _preflight, _ = _import_validator_helpers()
    src = "from manimlib import *\n"
    ok, err = _preflight(src, scene_id=1)
    assert ok is False
    assert "manimlib" in err


def test_self_test_source_is_actually_bad():
    _, _preflight, sample = _import_validator_helpers()
    ok, _ = _preflight(sample, scene_id=0)
    assert ok is False, "Self-test source must be flagged or service startup gate is broken"


def test_sanitizer_rewrites_show_creation():
    # Need to import via the package path; sanitizer module in code-generator/app
    sys.path.insert(0, os.path.join(_REPO_ROOT, "services", "code-generator", "app"))
    from sanitizer import sanitize_manim_code
    src = "from manim import *\nclass S(Scene):\n    def construct(self):\n        self.play(ShowCreation(Circle()))\n"
    out, warnings = sanitize_manim_code(src, scene_id=0)
    assert "ShowCreation" not in out
    assert "Create" in out
    assert any("ShowCreation" in w for w in warnings)
