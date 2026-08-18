"""Read prompt-rule markdown files once and cache them in-process.

The rules files (`hf_rules.md`, `manim_rules.md`) are loaded eagerly at module
import to fail-fast if the file is missing, then cached. The LLM call path
must not do file IO.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent


@lru_cache(maxsize=8)
def load(name: str) -> str:
    """Load a rules file by stem (e.g. ``"hf_rules"``, ``"manim_rules"``).

    Raises ``FileNotFoundError`` if the file is missing — fail loud so the
    container won't start with stale prompts.
    """
    path = _PROMPTS_DIR / f"{name}.md"
    return path.read_text(encoding="utf-8")
