# Architecture Review: Manim Agent Network

## 1. Concurrency & Blocking
**Issue:** The Validator service uses synchronous `subprocess.run` to execute Manim commands within an async FastAPI route handler (`validate_code` in `services/validator/app/main.py`).
**Impact:** This blocks the event loop, causing the Validator service to become unresponsive to other incoming validation requests while Manim is rendering.
**Recommendation:** Replace `subprocess.run` with `asyncio.create_subprocess_exec` to allow non-blocking execution of Manim renders.

## 2. State Management & Bloat
**Issue:** The LangGraph state (`LangGraphState` in `shared/models/agent_state.py`) currently stores raw code content directly within the `previous_code` dictionary. The Code Generator service reads from disk and injects file content into the state.
**Impact:** Storing large text blobs (or potentially base64 data) in the LangGraph state leads to state bloat, especially if persisted to a database, and goes against the pattern of passing file paths/metadata.
**Recommendation:** Modify the state to store `previous_code_paths` (a dictionary mapping `scene_id` to the file path of the previous code iteration) instead of raw `previous_code`. Update the Code Generator to read the file from disk only when generating a prompt, rather than returning it in the state.

## 3. The Self-Healing Loop
**Issue:** The retry logic in the Orchestrator (`orchestrator/app/core/graph.py`) correctly increments a `retry_counts` tracker and routes back to the Code Generator, but max retries is hardcoded and errors aren't perfectly contained.
**Impact:** If a render fails repeatedly, it can loop up to the hardcoded limit. The error logs are extracted correctly from `process.stderr` (or stdout fallback) in the Validator, but are truncated.
**Recommendation:** Ensure max retries is configurable. The current limit of 3 is functional.

## 4. Subprocess & Memory Leaks
**Issue:** While timeouts are enforced (`timeout=120` in `subprocess.run`), the synchronous nature means a killed FastAPI process could leave zombie `manim` processes.
**Impact:** Orphaned processes can consume CPU/Memory on the host.
**Recommendation:** Implementing `asyncio.create_subprocess_exec` with proper cleanup (e.g., catching `asyncio.CancelledError` and terminating the subprocess) will mitigate zombie processes if the request is canceled or the service dies.

## 5. Error Boundaries & Persistence
**Issue:** The Orchestrator uses an in-memory dictionary (`jobs_db` in `orchestrator/app/main.py`) to track job state and LangGraph results.
**Impact:** If the Orchestrator container crashes or restarts, all job history and in-progress LangGraph checkpoints are lost.
**Recommendation:** Implement PostgreSQL persistence using SQLModel for job tracking (`jobs_db` replacement) and LangGraph checkpointing. Configure the database in the `shared/database` layer.
