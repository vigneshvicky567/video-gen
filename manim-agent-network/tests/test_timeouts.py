"""Tests for the long-form timeout-scaling helpers (shared/timeouts.py)."""

import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from shared.timeouts import (
    job_wallclock_timeout_s,
    chunk_render_timeout_s,
    assembler_http_timeout_s,
)
from shared.config import settings


def test_no_target_uses_legacy_ceiling():
    assert job_wallclock_timeout_s(None) == settings.JOB_WALLCLOCK_TIMEOUT_SECONDS
    assert job_wallclock_timeout_s(0) == settings.JOB_WALLCLOCK_TIMEOUT_SECONDS


def test_job_timeout_scales_and_floors():
    # 5 min -> 1800 + 420*5 = 3900 (above the 3600 floor)
    assert job_wallclock_timeout_s(300) == 3900.0
    # 10 min -> 6000
    assert job_wallclock_timeout_s(600) == 6000.0
    # 30 min -> 14400 (4h)
    assert job_wallclock_timeout_s(1800) == 14400.0


def test_job_timeout_never_below_legacy_floor():
    # A tiny target still must not drop below the legacy 3600 ceiling.
    assert job_wallclock_timeout_s(60) >= settings.JOB_WALLCLOCK_TIMEOUT_SECONDS


def test_job_timeout_capped():
    assert job_wallclock_timeout_s(10 ** 9) == settings.JOB_TIMEOUT_MAX_SECONDS


def test_job_timeout_monotonic():
    vals = [job_wallclock_timeout_s(t) for t in (120, 300, 600, 1200, 1800, 2400)]
    assert vals == sorted(vals)


def test_chunk_render_timeout_floor_and_growth():
    assert chunk_render_timeout_s(0) == 900          # floor
    assert chunk_render_timeout_s(100) == 1050        # 300 + 7.5*100
    assert chunk_render_timeout_s(10 ** 9) == int(settings.COMPOSITOR_CHUNK_TIMEOUT_MAX_SECONDS)


def test_assembler_timeout_floor_and_cap():
    assert assembler_http_timeout_s(0) == settings.SERVICE_HTTP_TIMEOUT_SECONDS  # floor 900
    assert assembler_http_timeout_s(1800) == settings.ASSEMBLER_TIMEOUT_MAX_SECONDS  # capped
