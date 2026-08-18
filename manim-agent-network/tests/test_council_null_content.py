"""Regression tests for H1: council must not 500 on null/empty LLM content.

The shared NIM client returns ``message.content == None`` on content-filtered,
refused, or tool-only responses. ``json.loads(None)`` raises ``TypeError`` that
previously propagated through ``generate_script`` -> ``/generate`` -> HTTP 500.

These tests reuse the file-path loader from ``test_script_council`` so the
hyphenated ``script-writer/app`` package resolves without polluting
``sys.modules['app']``.
"""

import asyncio
import importlib
import importlib.util
import os
import sys

import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def _load_council():
    """Load script-writer's ``app.council`` under the unique name ``sw_app``.

    The script-writer dir is hyphenated and its ``app`` package collides with
    other services' ``app``; mirror test_script_council's isolation loader.
    """
    if "sw_app" not in sys.modules:
        app_dir = os.path.join(PROJECT_ROOT, "services", "script-writer", "app")
        spec = importlib.util.spec_from_file_location(
            "sw_app", os.path.join(app_dir, "__init__.py"),
            submodule_search_locations=[app_dir],
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules["sw_app"] = mod
        spec.loader.exec_module(mod)
    return importlib.import_module("sw_app.council")


council = _load_council()


class _Msg:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _Msg(content)


class _Resp:
    def __init__(self, content):
        self.choices = [_Choice(content)]


class _Completions:
    def __init__(self, content):
        self._content = content

    async def acreate(self, **_kwargs):
        return _Resp(self._content)


class _Chat:
    def __init__(self, content):
        self.completions = _Completions(content)


class _FakeClient:
    """Returns a fixed ``message.content`` for every completion call."""

    def __init__(self, content):
        self.chat = _Chat(content)


def test_call_json_raises_valueerror_on_null_content():
    client = _FakeClient(None)
    with pytest.raises(ValueError):
        asyncio.run(
            council._call_json(client, "sys", "user", temperature=0.1, max_tokens=10)
        )


def test_call_json_raises_valueerror_on_empty_content():
    client = _FakeClient("")
    with pytest.raises(ValueError):
        asyncio.run(
            council._call_json(client, "sys", "user", temperature=0.1, max_tokens=10)
        )


def test_single_writer_path_degrades_instead_of_typeerror():
    # brief=None -> single-writer path. Null content must not raise TypeError;
    # generate_script returns a degraded minimal script.
    client = _FakeClient(None)
    script, meta = asyncio.run(council.generate_script("Quantum tunneling", None, client))
    assert script.scenes, "expected a degraded fallback script, not an empty one"
    assert isinstance(script.title, str) and script.title
    assert meta["mode"] == "single"


def test_council_path_degrades_instead_of_typeerror():
    # target above COUNCIL_FULL_THRESHOLD_SECONDS -> planner/council path.
    # Planner null content must degrade (-> single-writer -> minimal), not 500.
    client = _FakeClient(None)
    brief = {"target_duration_seconds": 9999, "is_study_material": True}
    script, meta = asyncio.run(council.generate_script("Graph theory", brief, client))
    assert script.scenes, "expected a degraded fallback script, not an empty one"
    assert isinstance(script.title, str) and script.title
