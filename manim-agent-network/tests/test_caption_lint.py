"""Tests for composition lint additions: same-track overlap, caption-track
discipline, and the caption-band scene-file warning (services/compositor/app/html_validator.py)."""

import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest

from services.compositor.app.html_validator import validate_composition, _warn_caption_band
from services.compositor.app.duration_prober import AssemblyError

_TL = '<script>window.__timelines={};window.__timelines["main"]=1;</script>'
_ROOT_OPEN = ('<div id="composition" data-composition-id="main" data-start="0" '
              'data-duration="30" data-width="1920" data-height="1080">')


def _write(tmp_path, body):
    html = f'<!DOCTYPE html><html><body>{_ROOT_OPEN}{body}</div>{_TL}</body></html>'
    p = tmp_path / "composition.html"
    p.write_text(html, encoding="utf-8")
    return str(p)


def test_chained_captions_pass(tmp_path):
    body = (
        '<video id="v1" data-start="0" data-duration="10" data-track-index="1" '
        'src="http://x/v.mp4" muted playsinline></video>'
        '<div class="clip lower-third" data-start="0" data-duration="5" data-track-index="0">a</div>'
        '<div class="clip lower-third" data-start="5" data-duration="5" data-track-index="0">b</div>'
    )
    validate_composition(_write(tmp_path, body))  # must not raise


def test_same_track_overlap_rejected(tmp_path):
    body = (
        '<div class="clip lower-third" data-start="0" data-duration="6" data-track-index="0">a</div>'
        '<div class="clip lower-third" data-start="5" data-duration="5" data-track-index="0">b</div>'
    )
    with pytest.raises(AssemblyError, match="overlap"):
        validate_composition(_write(tmp_path, body))


def test_non_caption_on_caption_track_rejected(tmp_path):
    body = ('<video id="v" data-start="0" data-duration="5" data-track-index="0" '
            'src="http://x/v.mp4" muted playsinline></video>')
    with pytest.raises(AssemblyError, match="reserved caption track"):
        validate_composition(_write(tmp_path, body))


def test_caption_off_reserved_track_rejected(tmp_path):
    body = '<div class="clip lower-third" data-start="0" data-duration="5" data-track-index="3">a</div>'
    with pytest.raises(AssemblyError, match="must be on track 0"):
        validate_composition(_write(tmp_path, body))


def test_caption_band_warning(tmp_path):
    scene_dir = tmp_path / "compositions"
    scene_dir.mkdir()
    (scene_dir / "scene_1.html").write_text(
        '<div style="position:absolute;bottom:20px">label</div>', encoding="utf-8")
    (scene_dir / "scene_2.html").write_text(
        '<div style="position:absolute;bottom:300px">ok</div>', encoding="utf-8")
    warnings = _warn_caption_band(tmp_path)
    assert any("scene_1.html" in w for w in warnings)
    assert not any("scene_2.html" in w for w in warnings)
