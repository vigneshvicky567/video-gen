"""Pure-logic tests for the runner→Neon mirror (no DB/network)."""
import pathlib
import sys

# scripts/ lives at the repo root, two levels above services/web-tier
ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

import runner_neon_mirror as m


def test_map_status():
    assert m.map_status("completed") == "done"
    assert m.map_status("complete") == "done"
    assert m.map_status("failed") == "failed"
    assert m.map_status("error") == "failed"
    assert m.map_status("cancelled") == "cancelled"
    assert m.map_status("running") == "running"
    assert m.map_status("") == "running"
    assert m.map_status(None) == "running"


def test_r2_key():
    assert m.r2_key("abc") == "jobs/abc/final.mp4"


def test_is_terminal():
    assert m.is_terminal("done") and m.is_terminal("failed") and m.is_terminal("cancelled")
    assert not m.is_terminal("running") and not m.is_terminal("queued")


def test_should_upload():
    assert m.should_upload("done", "/workspace/outputs/x_final.mp4")
    assert not m.should_upload("done", None)
    assert not m.should_upload("failed", "/workspace/outputs/x_final.mp4")
    assert not m.should_upload("running", "/x.mp4")
