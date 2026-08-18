"""The FR-1 regression lock: every Dict[int, ...] field of LangGraphState must
survive a JSON round-trip (SQLite persist -> resume) with int keys revived.
The revive list is DERIVED from the typed state, so adding a new scene-keyed
field automatically gets coverage here."""

import importlib
import json
import os
import sys
import typing

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_ORCH = os.path.join(PROJECT_ROOT, "services", "orchestrator")
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def _load_db():
    saved = {k: sys.modules[k] for k in list(sys.modules) if k == "app" or k.startswith("app.")}
    for k in saved:
        del sys.modules[k]
    sys.path.insert(0, _ORCH)
    try:
        return importlib.import_module("app.db")
    finally:
        sys.path.remove(_ORCH)
        for k in [k for k in sys.modules if k == "app" or k.startswith("app.")]:
            del sys.modules[k]
        sys.modules.update(saved)


dbmod = _load_db()
from shared.models.agent_state import LangGraphState  # noqa: E402


def _expected_scene_keyed():
    return {
        name for name, tp in typing.get_type_hints(LangGraphState).items()
        if typing.get_origin(tp) is dict and (typing.get_args(tp) or (None,))[0] is int
    }


def test_derived_whitelist_covers_every_int_keyed_field():
    assert set(dbmod._SCENE_KEYED) == _expected_scene_keyed()
    # The fields the resume path depends on must all be present.
    for required in ("render_paths", "code_paths", "audio_paths", "retry_counts",
                     "infra_retry_counts", "error_logs", "error_history",
                     "previous_code", "audio_segments", "image_paths"):
        assert required in dbmod._SCENE_KEYED, required


def test_json_roundtrip_revives_int_keys():
    state = {
        "job_id": "j", "topic": "t", "status": "validation",
        "render_paths": {1: "/a.mp4", 2: "/b.html"},
        "retry_counts": {2: 3},
        "infra_retry_counts": {1: 1},
        "error_history": {2: [{"attempt": 1, "source": "render", "error": "x"}]},
        "audio_segments": {1: [{"text": "hi", "start": 0.0, "duration": 1.2}]},
        "stage_timings": {"validation": 12.5},   # str-keyed — must NOT be coerced
    }
    revived = dbmod._revive_scene_keys(json.loads(json.dumps(state)))
    assert 1 in revived["render_paths"] and 2 in revived["render_paths"]
    assert revived["retry_counts"] == {2: 3}
    assert revived["infra_retry_counts"] == {1: 1}
    assert 2 in revived["error_history"]
    assert 1 in revived["audio_segments"]
    assert revived["stage_timings"] == {"validation": 12.5}
    # The resume-skip membership check that used to silently fail:
    assert 1 in revived["render_paths"]
