"""Authoring rules consumed by the code-generator LLM as system-prompt prefixes.

Rules are sourced from the official HyperFrames + Manim CE skill repos and
exposed to the LLM via `loader.load(name)`. Edit the `.md` files to update
authoring guidance — no Python change needed.
"""

from .loader import load

__all__ = ["load"]
