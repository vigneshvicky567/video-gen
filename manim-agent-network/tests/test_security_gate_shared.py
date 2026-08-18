"""The security gate constants are single-sourced (shared/security.py) and the
code-generator's check_manim_security actually catches the attack shapes the
validator's preflight catches — the two gates can no longer diverge (F185/F80)."""

import importlib
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_CODEGEN = os.path.join(PROJECT_ROOT, "services", "code-generator")
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from shared.security import FORBIDDEN_BUILTINS, FORBIDDEN_MODULES  # noqa: E402


def _load_sanitizer():
    saved = {k: sys.modules[k] for k in list(sys.modules) if k == "app" or k.startswith("app.")}
    for k in saved:
        del sys.modules[k]
    sys.path.insert(0, _CODEGEN)
    try:
        return importlib.import_module("app.sanitizer")
    finally:
        sys.path.remove(_CODEGEN)
        for k in [k for k in sys.modules if k == "app" or k.startswith("app.")]:
            del sys.modules[k]
        sys.modules.update(saved)


sanitizer = _load_sanitizer()


def test_sanitizer_uses_shared_constants():
    assert sanitizer.FORBIDDEN_BUILTINS is FORBIDDEN_BUILTINS
    assert sanitizer.FORBIDDEN_MODULES is FORBIDDEN_MODULES


def test_union_contains_previously_divergent_names():
    # These four were in the sanitizer but MISSING from the live validator gate.
    for name in ("vars", "getattr", "setattr", "delattr"):
        assert name in FORBIDDEN_BUILTINS, name


MALICIOUS_SOURCES = [
    "import os\nos.system('id')",
    "from subprocess import run\nrun(['id'])",
    "eval('1+1')",
    "__import__('socket')",
    "getattr(__builtins__, 'ex' + 'ec')",
    "import urllib.request",
    "open('/etc/passwd')",
]


def test_check_manim_security_catches_each_attack_shape():
    for src in MALICIOUS_SOURCES:
        violations = sanitizer.check_manim_security("from manim import *\n" + src)
        assert violations, f"gate missed: {src!r}"


def test_clean_scene_passes():
    clean = (
        "from manim import *\n"
        "config.background_color = WHITE\n"
        "class Scene1(Scene):\n"
        "    def construct(self):\n"
        "        self.play(Create(Circle()))\n"
    )
    assert sanitizer.check_manim_security(clean) == []
