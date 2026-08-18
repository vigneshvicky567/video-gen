# Pipeline Bugfix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the verified CRITICAL/HIGH bugs in the Manim Agent Network orchestrator, config, and compositor that cause job loss, retry-loop crashes, dropped audio, and silent misconfiguration.

**Architecture:** Wire the already-implemented `db.py` SQLite layer into the orchestrator for durable job state; fix the LangGraph retry accounting so code-gen failures count against the retry cap; collect all parallel results before deciding failure; add startup config validation and a wall-clock job timeout.

**Tech Stack:** Python 3.12, FastAPI, LangGraph, SQLite, pytest.

**Status of prior fixes (already applied this session — do NOT redo):**
- `sanitizer.py` — security denylist + primary-class-only rename
- `validator/main.py` — security AST gate, semaphore moved to startup, Popen+kill on timeout
- `assembler/main.py` — `os.makedirs(temp_dir)`

**Out of band (user action, cannot be coded):**
- 🔴 Rotate `NVIDIA_API_KEY` + `PEXELS_API_KEY` in their dashboards. Live values sit in `.env`.

---

### Task 1: Durable job state — wire `db.py` into orchestrator

**Files:**
- Modify: `services/orchestrator/app/main.py`
- Test: `tests/test_orchestrator_jobstore.py` (create)

- [ ] **Step 1: Write failing test**

```python
# tests/test_orchestrator_jobstore.py
from services.orchestrator.app.db import JobDatabase

def test_job_survives_new_db_instance(tmp_path):
    p = str(tmp_path / "jobs.db")
    db1 = JobDatabase(db_path=p)
    db1.create_job("j1", "topic", {"status": "starting"})
    db1.update_job("j1", {"status": "completed", "final_output_path": "/x.mp4"})
    # Simulate restart: brand-new instance, same file
    db2 = JobDatabase(db_path=p)
    got = db2.get_job("j1")
    assert got is not None
    assert got["status"] == "completed"
```

- [ ] **Step 2: Run — expect PASS already** (proves db.py works standalone)

Run: `python -m pytest tests/test_orchestrator_jobstore.py -v`
Expected: PASS (db.py is correct; it's just never used by main.py)

- [ ] **Step 3: Wire db into main.py**

Replace `jobs_db = {}` and the three call sites. In `main.py`:

```python
from app.db import db  # SQLite-backed durable store

# /generate
@app.post("/generate", response_model=dict)
async def start_generation(request: GenerationRequest, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())
    db.create_job(job_id, request.topic, {"job_id": job_id, "topic": request.topic, "status": "starting"})
    background_tasks.add_task(run_pipeline, job_id, request.topic)
    return {"job_id": job_id, "message": "Generation started."}

# run_pipeline success path: db.update_job(job_id, final_state)
# run_pipeline failure path: db.update_job(job_id, initial_state)
```

- [ ] **Step 4: Fix `/job/{id}` to return HTTP 404 on miss**

```python
from fastapi import HTTPException

@app.get("/job/{job_id}", response_model=dict)
async def get_job_status(job_id: str):
    state = db.get_job(job_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return state
```

- [ ] **Step 5: Verify import + compile**

Run: `python -m py_compile services/orchestrator/app/main.py`
Expected: no output (success)

- [ ] **Step 6: Commit**

```bash
git add services/orchestrator/app/main.py tests/test_orchestrator_jobstore.py
git commit -m "fix(orchestrator): persist jobs to SQLite, return 404 on missing job"
```

---

### Task 2: Fix retry-loop crash — count code-gen failures

**Files:**
- Modify: `services/orchestrator/app/core/graph.py`
- Test: `tests/test_validation_router.py` (create)

**Problem:** A scene that fails code generation never enters `code_paths`, so the validator never increments its `retry_counts`. `validation_router` keeps routing back to `code_generator_node` with the count stuck at 0 → LangGraph `GraphRecursionError`. The 5-retry cap is bypassed.

- [ ] **Step 1: Write failing test for the router invariant**

```python
# tests/test_validation_router.py
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "services" / "orchestrator" / "app"))
from core.graph import validation_router

def _state(scenes, render_paths, retry_counts):
    return {"overall_error": None, "script": {"scenes": scenes},
            "render_paths": render_paths, "retry_counts": retry_counts}

def test_router_fails_when_codegen_exhausted():
    scenes = [{"scene_id": 1}]
    # scene 1 never rendered, already at cap → must FAIL, not loop
    s = _state(scenes, render_paths={}, retry_counts={1: 5})
    assert validation_router(s) == "failed"
```

- [ ] **Step 2: Run — expect PASS** (router already checks `< 5`)

Run: `python -m pytest tests/test_validation_router.py -v`
Expected: PASS — confirms the router is correct; the bug is upstream (counts never reach 5).

- [ ] **Step 3: Increment retry_counts on code-gen failure in `code_generator_node`**

In `graph.py`, change the failure branch so a failed generation counts:

```python
        new_retry_counts = dict(state.get("retry_counts", {}))
        for scene_id, code_path, error in results:
            if code_path:
                new_code_paths[scene_id] = code_path
                try:
                    with open(code_path, "r") as f:
                        new_previous_code[scene_id] = f.read()
                except Exception:
                    pass
            else:
                logger.error(f"Scene {scene_id} code generation failed: {error}")
                new_retry_counts[scene_id] = new_retry_counts.get(scene_id, 0) + 1
                new_error_logs = dict(state.get("error_logs", {}))
                new_error_logs[scene_id] = error or "code generation failed"

        return {
            "code_paths": new_code_paths,
            "previous_code": new_previous_code,
            "retry_counts": new_retry_counts,
            "error_logs": {**state.get("error_logs", {}),
                           **{sid: (err or "code generation failed")
                              for sid, cp, err in results if not cp}},
            "status": "code_generation",
        }
```

- [ ] **Step 4: Run router test again** — Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/orchestrator/app/core/graph.py tests/test_validation_router.py
git commit -m "fix(orchestrator): count code-gen failures against retry cap to stop recursion crash"
```

---

### Task 3: Voiceover — collect all results before deciding failure

**Files:**
- Modify: `services/orchestrator/app/core/graph.py`

**Problem:** `voiceover_and_images_node` returns `failed` on the first `None` audio path inside the loop, discarding successful audio and failing the whole job on one transient error.

- [ ] **Step 1: Replace the early-return loop in `voiceover_and_images_node`**

```python
        new_audio_paths = dict(existing_audio)
        failed_scenes = []
        for scene_id, audio_path in vo_results:
            if audio_path:
                new_audio_paths[scene_id] = audio_path
            else:
                failed_scenes.append(scene_id)

        if failed_scenes:
            return {"audio_paths": new_audio_paths, "status": "failed",
                    "overall_error": f"Voiceover failed for scenes: {failed_scenes}"}
```

- [ ] **Step 2: Verify compile**

Run: `python -m py_compile services/orchestrator/app/core/graph.py`
Expected: no output

- [ ] **Step 3: Commit**

```bash
git add services/orchestrator/app/core/graph.py
git commit -m "fix(orchestrator): collect all voiceover results before failing job"
```

---

### Task 4: Remove dead code (`voiceover_node`, `image_fetcher_node`)

**Files:**
- Modify: `services/orchestrator/app/core/graph.py`

**Problem:** Both functions are defined but never added to the graph (`voiceover_and_images_node` superseded them). They duplicate logic and confuse maintenance.

- [ ] **Step 1: Delete `voiceover_node` (lines ~215-235) and `image_fetcher_node` (lines ~283-300)**

Keep `_generate_voiceover` (used by `voiceover_and_images_node`).

- [ ] **Step 2: Update the conditional-edge mapping key for clarity**

In `add_conditional_edges("validator_node", validation_router, {...})`, the router returns `"voiceover_node"` as a logical key mapped to the real node `"voiceover_and_images_node"`. Leave the mapping (it works), but add a comment so the string isn't mistaken for the deleted function.

- [ ] **Step 3: Verify compile** — `python -m py_compile services/orchestrator/app/core/graph.py`

- [ ] **Step 4: Commit**

```bash
git add services/orchestrator/app/core/graph.py
git commit -m "refactor(orchestrator): remove unused voiceover_node and image_fetcher_node"
```

---

### Task 5: Wall-clock job timeout + initial_state image_paths

**Files:**
- Modify: `services/orchestrator/app/main.py`
- Modify: `shared/config.py`

- [ ] **Step 1: Add config knob**

In `config.py`:

```python
    JOB_WALLCLOCK_TIMEOUT_SECONDS: float = float(os.getenv("JOB_WALLCLOCK_TIMEOUT_SECONDS", "3600"))
```

- [ ] **Step 2: Wrap ainvoke**

In `main.py run_pipeline`:

```python
        final_state = await asyncio.wait_for(
            app_graph.ainvoke(initial_state),
            timeout=settings.JOB_WALLCLOCK_TIMEOUT_SECONDS,
        )
```

Add `import asyncio` and `from shared.config import settings` at top. Add an `except asyncio.TimeoutError` branch that marks the job failed with a timeout message.

- [ ] **Step 3: Add `image_paths` to initial_state** (`main.py:42-47`)

```python
        "render_paths": {}, "audio_paths": {}, "image_paths": {},
```

- [ ] **Step 4: Verify compile** — `python -m py_compile services/orchestrator/app/main.py shared/config.py`

- [ ] **Step 5: Commit**

```bash
git add services/orchestrator/app/main.py shared/config.py
git commit -m "feat(orchestrator): wall-clock job timeout; seed image_paths in initial state"
```

---

### Task 6: Startup config validation for required keys

**Files:**
- Modify: `services/orchestrator/app/main.py`

- [ ] **Step 1: Add startup validation**

```python
@app.on_event("startup")
async def _validate_config():
    if not settings.NVIDIA_API_KEY:
        raise RuntimeError("NVIDIA_API_KEY is required but not set")
```

- [ ] **Step 2: Verify compile** — `python -m py_compile services/orchestrator/app/main.py`

- [ ] **Step 3: Commit**

```bash
git add services/orchestrator/app/main.py
git commit -m "fix(config): fail fast at startup when NVIDIA_API_KEY missing"
```

---

### Task 7: duration_prober — no crash when scene has no audio

**Files:**
- Modify: `services/compositor/app/duration_prober.py`
- Test: `tests/test_duration_prober.py` (create)

- [ ] **Step 1: Write failing test**

```python
# tests/test_duration_prober.py
import pytest
from services.compositor.app.duration_prober import compute_scene_timings

def test_scene_without_audio_does_not_crash(monkeypatch):
    import services.compositor.app.duration_prober as dp
    monkeypatch.setattr(dp, "probe_duration", lambda p: 4.0 if p else 0.0)
    scenes = [{"scene_id": 1, "estimated_duration_seconds": 6}]
    # render present, audio MISSING for scene 1
    recs = compute_scene_timings({1: "/x.html"}, {}, scenes)
    assert recs[0].actual_audio_duration_seconds == 0.0
```

- [ ] **Step 2: Run — expect FAIL** with `KeyError: 1`

Run: `python -m pytest tests/test_duration_prober.py -v`
Expected: FAIL (KeyError)

- [ ] **Step 3: Guard the audio lookup**

In `compute_scene_timings`:

```python
        audio_path = audio_paths.get(scene_id)
        audio_dur = probe_duration(audio_path) if audio_path else 0.0

        records.append(SceneTimingRecord(
            scene_id=scene_id,
            render_path=render_path,
            audio_path=audio_path or "",
            actual_video_duration_seconds=video_dur,
            actual_audio_duration_seconds=audio_dur,
            start_time_seconds=round(accumulated, 3),
        ))
```

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add services/compositor/app/duration_prober.py tests/test_duration_prober.py
git commit -m "fix(compositor): tolerate scenes with no audio in timing computation"
```

---

## Self-Review

- **Spec coverage:** Tasks map to verified bugs B1 (T1), G1 (T1), B5 (T2), B3 (T3), dead-code (T4), wall-clock + image_paths (T5), HIGH-6 config (T6), duration_prober KeyError (T7). Key rotation is out-of-band (documented).
- **Placeholder scan:** none — all steps show concrete code/commands.
- **Type consistency:** `db.create_job/update_job/get_job` match `db.py` signatures; `validation_router` keys unchanged; `SceneTimingRecord` fields match existing usage.
- **Deferred (separate hardening pass, not in this plan):** API auth (CRIT-4), path/job_id validation (CRIT-2/MED-5), Docker non-root + healthchecks, espeak `--` separator, image-fetcher rate limiting. These are real but larger-scope; tracked in the review summary.
