# Architecture & Code Review Findings

## 1. Concurrency & Blocking
**Critical Issues Found:**
- **Synchronous Subprocesses:** The `validator`, `assembler`, and `quality_review` services all use synchronous `subprocess.run()` calls inside async FastAPI route handlers. This blocks the Uvicorn worker threads completely while `manim` or `ffmpeg` run. A single long-running render will starve the server and cause health checks or subsequent requests to time out.
  - *Location:* `services/validator/main.py:30`, `services/assembler/main.py:33`, `services/quality_review/main.py:27`
- **Sequential API Calls:** In `orchestrator` (`node_generate_code`, `node_validate`, `node_voiceover`), scenes are processed sequentially in a `for scene in state.scenes:` loop. For 5 scenes, the total time is the sum of all generation/validation times instead of executing them concurrently via `asyncio.gather`.
  - *Location:* `services/orchestrator/main.py:44, 69, 102`

## 2. State Management & Bloat
**Critical Issues Found:**
- **Code Bloat in State:** The `SceneData` Pydantic model (`services/shared/models.py`) stores raw Python code as a string in `manim_code`. This code is passed in HTTP payloads and stored in the LangGraph state. For a large multi-scene animation, this drastically inflates the LangGraph state size.
  - *Mitigation:* The state should pass file paths (`script_path`) instead of raw code strings. The `manim_generator` should write the code directly to the shared `/workspace` volume, and the `validator` should read it from there.

## 3. The Self-Healing Loop
**Architectural Warnings:**
- **Retry Logic Truncation:** The `validator` captures Manim output and truncates it: `result.stderr[-1000:]`. If the traceback is long, the actual error root cause at the top might be missing, causing the LLM in `manim_generator` to hallucinate a fix since it can't see the actual Exception.
- **Pipeline Halting:** The `route_after_validate` function halts the entire pipeline if a *single* scene exceeds the max retry limit (`retry_count >= 3`). While this prevents infinite loops, a more robust architecture might render the successful scenes or mark the job as partially completed.
  - *Location:* `services/orchestrator/main.py:157`

## 4. Subprocess & Memory Leaks
**Critical Issues Found:**
- **Zombie Processes:** Because `subprocess.run` is used synchronously, if the FastAPI container is killed mid-render (e.g., OOM kill, Docker stop), the spawned `manim` or `ffmpeg` processes will be orphaned and consume host resources. Switching to `asyncio.create_subprocess_exec` and ensuring `.terminate()` or `.kill()` is called in an `except asyncio.CancelledError` block is mandatory.
- **File System Clutter:** The `assembler` creates intermediate files (`scene_{idx}_merged.mp4`, `concat_list.txt`) but does not clean them up upon success or failure, leading to disk space exhaustion over time.

## 5. Error Boundaries & Persistence
**Critical Issues Found:**
- **Ephemeral State:** The Orchestrator stores job statuses in a simple Python dictionary (`jobs: Dict[str, PipelineState]`). If the Orchestrator service crashes or is restarted, all active and completed jobs are lost, and running LangGraph pipelines become orphaned from a tracking perspective.
  - *Location:* `services/orchestrator/main.py:182`
  - *Mitigation:* We need a PostgreSQL database using SQLModel to track job state and to use LangGraph's checkpointer to persist the graph state.
- **Timeout Propagation:** The orchestrator defines HTTP timeouts (`timeout=300` for validate), but the validator also has a subprocess timeout of 300. The HTTP request will likely time out slightly before or at the exact same time the subprocess times out, potentially causing a race condition where the orchestrator marks it as an HTTP failure while the validator is returning a structured timeout response.
