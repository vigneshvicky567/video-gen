"""Pure timeout-scaling helpers for long-form video jobs.

Kept side-effect free so they can be unit-tested on the host without importing
any service. All three functions degrade to today's behaviour when no target
duration is known, so legacy jobs (no brief) are unchanged.
"""

from __future__ import annotations

from typing import Optional

from shared.config import settings


def job_wallclock_timeout_s(target_duration_s: Optional[float]) -> float:
    """Whole-job wallclock budget.

    No target -> the legacy fixed ceiling (3600s). With a target, scale
    base + k x target_minutes, never dropping below the legacy default, capped.
    30 min target -> 1800 + 420*30 = 14400s (4h).
    """
    if not target_duration_s:
        return settings.JOB_WALLCLOCK_TIMEOUT_SECONDS
    scaled = (
        settings.JOB_TIMEOUT_BASE_SECONDS
        + settings.JOB_TIMEOUT_PER_TARGET_MINUTE_SECONDS * (target_duration_s / 60.0)
    )
    return min(
        settings.JOB_TIMEOUT_MAX_SECONDS,
        max(settings.JOB_WALLCLOCK_TIMEOUT_SECONDS, scaled),
    )


def chunk_render_timeout_s(chunk_output_s: float) -> int:
    """Per-chunk HyperFrames render budget.

    Software render runs ~5x realtime; budget 7.5x + 300s base, floored at 900s
    (never below today's effective per-render headroom), capped by config.
    """
    return int(
        min(
            settings.COMPOSITOR_CHUNK_TIMEOUT_MAX_SECONDS,
            max(900.0, 300.0 + 7.5 * chunk_output_s),
        )
    )


def assembler_http_timeout_s(planned_total_s: float) -> float:
    """Orchestrator-side timeout for the synchronous /assemble HTTP call.

    Covers rendering the whole output plus concat margin; never below the
    legacy service HTTP timeout (900s), capped.
    """
    return min(
        settings.ASSEMBLER_TIMEOUT_MAX_SECONDS,
        max(settings.SERVICE_HTTP_TIMEOUT_SECONDS, 600.0 + 9.0 * planned_total_s),
    )
