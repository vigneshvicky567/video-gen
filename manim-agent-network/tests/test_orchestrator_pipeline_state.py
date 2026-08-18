"""Regression tests for H2: run_pipeline must not clobber streamed progress.

The streaming path persists merged state after every graph node (script,
render_paths, statuses). The timeout and generic-exception handlers previously
wrote ``initial_state`` (script=None, empty paths) via ``db.update_job`` — a
full json.dumps replacement — destroying all live progress for a failed job.

These tests drive ``run_pipeline`` with a fake graph that streams real progress
then hangs (-> TimeoutError) or raises (-> generic Exception), and assert the
persisted record keeps script/render_paths with status='failed'.
"""

import asyncio
import importlib
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_ORCH = os.path.join(PROJECT_ROOT, "services", "orchestrator")
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def _load_orch_main():
    """Import orchestrator's app.main in isolation.

    Several services expose a top-level ``app`` package; orchestrator's
    ``main`` does ``from app.core.graph import app_graph``. If another service's
    ``app`` is already cached (e.g. compositor's, imported by an earlier test),
    that import fails. Evict any cached ``app``/``app.*`` and prepend the
    orchestrator dir, import, then restore the prior modules so later tests see
    the same conditions as before.
    """
    saved = {k: sys.modules[k] for k in list(sys.modules) if k == "app" or k.startswith("app.")}
    for k in saved:
        del sys.modules[k]
    sys.path.insert(0, _ORCH)
    try:
        return importlib.import_module("app.main")
    finally:
        sys.path.remove(_ORCH)
        for k in [k for k in sys.modules if k == "app" or k.startswith("app.")]:
            del sys.modules[k]
        sys.modules.update(saved)


orch_main = _load_orch_main()


class _FakeDB:
    """Mimics db.update_job's full-replacement semantics with a copy."""

    def __init__(self):
        self.state = None
        self.calls = 0

    def create_job(self, *_a, **_k):
        pass

    def update_job(self, _job_id, state):
        self.calls += 1
        self.state = dict(state)  # full replace, like json.dumps round-trip

    def get_job(self, _job_id):
        return self.state


class _FakeGraph:
    """astream yields the given progress states, then hangs or raises."""

    def __init__(self, states, after):
        self._states = states
        self._after = after  # "hang" | "raise"

    async def astream(self, _initial_state, stream_mode="values"):
        for s in self._states:
            yield s
        if self._after == "hang":
            await asyncio.sleep(10)
        elif self._after == "raise":
            raise RuntimeError("codegen blew up")


_PROGRESS = {
    "job_id": "j1",
    "topic": "t",
    "status": "rendering",
    "script": {"title": "T", "scenes": [{"scene_id": 1}]},
    "code_paths": {"1": "/workspace/code/s1.py"},
    "render_paths": {"1": "/workspace/renders/s1.mp4"},
    "audio_paths": {},
    "image_paths": {},
    "retry_counts": {},
    "error_logs": {},
    "previous_code": {},
    "final_output_path": None,
    "overall_error": None,
    "brief": None,
    "script_meta": None,
}


def _patch(monkeypatch, after):
    fake_db = _FakeDB()
    monkeypatch.setattr(orch_main, "db", fake_db)
    monkeypatch.setattr(orch_main, "app_graph", _FakeGraph([dict(_PROGRESS)], after))
    monkeypatch.setattr(orch_main, "job_wallclock_timeout_s", lambda *_a, **_k: 0.05)
    monkeypatch.setattr(orch_main, "_tracer", None, raising=False)
    return fake_db


def test_timeout_preserves_streamed_progress(monkeypatch):
    fake_db = _patch(monkeypatch, after="hang")
    asyncio.run(orch_main.run_pipeline("j1", "t", None))

    assert fake_db.state is not None
    assert fake_db.state["status"] == "failed"
    assert fake_db.state["script"] == {"title": "T", "scenes": [{"scene_id": 1}]}
    assert fake_db.state["render_paths"] == {"1": "/workspace/renders/s1.mp4"}
    assert fake_db.state["code_paths"] == {"1": "/workspace/code/s1.py"}
    assert fake_db.state["overall_error"]  # timeout message set


def test_exception_preserves_streamed_progress(monkeypatch):
    fake_db = _patch(monkeypatch, after="raise")
    asyncio.run(orch_main.run_pipeline("j1", "t", None))

    assert fake_db.state is not None
    assert fake_db.state["status"] == "failed"
    assert fake_db.state["script"] == {"title": "T", "scenes": [{"scene_id": 1}]}
    assert fake_db.state["render_paths"] == {"1": "/workspace/renders/s1.mp4"}
    assert "codegen blew up" in fake_db.state["overall_error"]
