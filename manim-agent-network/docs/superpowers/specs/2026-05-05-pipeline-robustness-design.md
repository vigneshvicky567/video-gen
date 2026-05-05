# Pipeline Robustness Fix — Design Spec

**Date:** 2026-05-05
**Status:** Approved
**Owner:** ctsuser60

## Problem

Three failures observed in `job=9cb48a8e` and `job=02551eb1`:

1. **Deprecated Manim API leaked to runtime.** Scene 3 emitted `ShowCreation(...)` from LLM. Both the code-generator sanitizer and validator AST preflight should have caught it. Neither did. Code dump in failure log shows `ShowCreation` raw, meaning sanitizer never rewrote it. Most likely cause: container images on disk pre-date the sanitizer/preflight code; running images stale.
2. **Render timeout 120s false-fail.** Scene 5 timed out at 120s on first attempt, completed in 21s on retry. Cause is cold LaTeX cache + concurrent manim subprocesses contending for CPU under `asyncio.gather` fanout.
3. **Cold-start service race.** First job `02551eb1` failed with `script-writer 500`. `docker-compose.yml` uses plain `depends_on` (no `condition: service_healthy`) and Dockerfiles have no `HEALTHCHECK`. Orchestrator accepts traffic before downstream services are ready.

## Goals

- Fail-loud on deploy of stale images.
- Adaptive render budget that does not punish complex but valid scenes.
- Compose blocks orchestrator until every downstream is responding to `/health`.

## Non-goals

- Re-architecting validator into a sandbox-per-scene runner (rejected as Approach C; over-engineered).
- Auto-retry pipelines on transient failure (rejected as Approach B; hides bugs).

## Architecture

Three independent layers, each fix at its proper layer.

```
Layer 1 — Build/Deploy: containers actually run latest code
Layer 2 — Service contract: ready before traffic
Layer 3 — Render budget: adaptive, observable
```

## Layer 1 — Deploy correctness

**Self-test on service boot.** Each service that owns a guard runs the guard against a known-bad input at startup. Mismatch → `sys.exit(1)`. A stale image cannot pass startup.

- `services/validator/app/main.py`
  - Constant `_SELF_TEST_BAD_SOURCE` containing `ShowCreation(Circle())`.
  - On startup, call `_preflight_ast_checks(_SELF_TEST_BAD_SOURCE, scene_id=0)`. If it returns `(True, "")`, log fatal and `sys.exit(1)`.
- `services/code-generator/app/main.py`
  - On startup, call `sanitize_manim_code("ShowCreation(x)")`. If output contains `ShowCreation`, log fatal and `sys.exit(1)`.

**Makefile target.**
```
rebuild:
    docker compose build --no-cache
    docker compose up -d --force-recreate
```

## Layer 2 — Service readiness

**Add `curl` to base image** (needed by `HEALTHCHECK`). `Dockerfile.base` already runs `apt-get`; append `curl` to package list.

**Add `HEALTHCHECK` to every service Dockerfile.**
```
HEALTHCHECK --interval=5s --timeout=3s --start-period=15s --retries=5 \
    CMD curl -fsS http://localhost:<PORT>/health || exit 1
```
Per-service ports: orchestrator 8000, script-writer 8001, code-generator 8002, validator 8003, voiceover 8004, compositor 8005, image-fetcher 8006, assembler 8005.

**Convert compose `depends_on` to long-form with `condition: service_healthy`.**
Compose v3 supports this syntax; orchestrator gets all 6 downstream conditions.

**Orchestrator readiness self-poll** (defense in depth). On startup, poll each downstream `/health` with 60s budget. Refuse `/generate` until all green; respond 503 with `Retry-After: 5` until then.

## Layer 3 — Render budget

**Adaptive timeout.** Walk AST, count `self.play(...)` calls. Budget = `max(90, 90 + 20 * play_count)`, cap 600s.

```python
def _compute_timeout(source: str) -> int:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return 90
    plays = sum(
        1 for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "play"
    )
    return min(600, max(90, 90 + 20 * plays))
```

**LaTeX warmup at validator boot.** Render a one-time warmup scene with `Tex("warmup")` and `MathTex("x^2")` into a fixed media dir. Caches dvisvgm artifacts at image scope. Subsequent first-Tex penalty drops from ~30s to ~3s. Failure of warmup must not block service startup — log warning, continue.

**Concurrency cap.** Module-level `asyncio.Semaphore(max(1, os.cpu_count() // 2))`. `_validate_manim` acquires before `subprocess.run`. Prevents CPU thrash from N parallel manim subprocesses.

## Testing

- `tests/test_validator_robustness.py`
  - `test_compute_timeout_floor`: empty source → 90.
  - `test_compute_timeout_per_play`: source with 5 plays → 190.
  - `test_compute_timeout_cap`: source with 100 plays → 600.
  - `test_preflight_catches_show_creation`: confirms preflight rejects `ShowCreation`.
  - `test_self_test_constant_is_bad`: confirms `_SELF_TEST_BAD_SOURCE` triggers preflight.
- Manual smoke: `make rebuild && curl http://localhost:8000/health && curl -X POST http://localhost:8000/generate -d '{"topic":"How RFID works"}'` — expect no 500, no `NameError`, no 120s timeout.

## Files touched

| File | Change |
|---|---|
| `services/validator/app/main.py` | Self-test, adaptive timeout, semaphore, warmup |
| `services/code-generator/app/main.py` | Sanitizer self-test |
| `infrastructure/docker/Dockerfile.base` | Add `curl` |
| `infrastructure/docker/Dockerfile.{orchestrator,script-writer,code-generator,validator,voiceover,compositor,image-fetcher,assembler}` | Add `HEALTHCHECK` |
| `docker-compose.yml` | Long-form `depends_on` with `condition: service_healthy` |
| `Makefile` | `rebuild` target |
| `tests/test_validator_robustness.py` | New, 5 unit tests |

## Out of scope

- Fixing assembler vs compositor port collision (both default 8005). Pre-existing; orchestrator targets compositor at 8005, assembler runs in-process inside compositor flow.
- Replacing `qwen3-coder` with stricter model. LLM correctness is downstream of guards — guards catch what model misses.
