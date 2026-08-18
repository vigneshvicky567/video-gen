# Local Diff Review — manim-agent-network

**Reviewed:** 2026-06-14
**Base:** HEAD `d28c230` (version 1.2)
**Scope:** uncommitted working-tree changes — 22 tracked files (~892 +/ ~382 -), 5 new source modules (~854 lines), 11 new/changed test files. Excluded as noise: `graphify-out/cache/`, `workspace/jobs.db*`, `frontend/`.
**Method:** 24 per-file correctness reviewers (fan-out) + adversarial verification of every CRITICAL/HIGH finding (refute-by-default).
**Decision:** REQUEST CHANGES — 3 confirmed HIGH defects, all runtime-reachable.

## Validation

| Check | Result |
|---|---|
| `pytest tests/` | **102 passed** (42s) |
| Test collection | 1 error — `workspace/temp/test_scene.py` (generated manim artifact, no local `manim` module; outside diff) |
| Lint / typecheck | not run (no configured command found) |

---

## CRITICAL
None.

## HIGH — confirmed by adversarial verification (fix before merge)

### H1 — `council.py` `_call_json` crashes on null LLM content
`services/script-writer/app/council.py:95` — `json.loads(response.choices[0].message.content)` with no None-guard. The shared NIM client (`shared/llm_client.py:237`) returns `message.get("content")`, which is `None` on content-filtered/refused/tool-only responses. `json.loads(None)` → `TypeError`. `_single_writer` (line 175) and `_planner` (line 208) call `_call_json` **unguarded**, so the error propagates through `generate_script` to `main.py:88` → HTTP 500 for the whole `/generate` request. The reviewer/repair paths already wrap `_call_json` in try/except, so only single-writer + planner crash — an inconsistent-resilience bug. The codebase already defends this exact hazard at `image-fetcher/app/keyword_extractor.py:88-91`.
**Fix:** guard inside `_call_json` (`msg = ...content; if not msg: raise ValueError("empty LLM response")`) and wrap the `_single_writer`/`_planner` dispatch in try/except with a minimal-script fallback, matching the council/reviewer/repair paths.

### H2 — `orchestrator/main.py` clobbers mid-stream progress on timeout/failure
`services/orchestrator/app/main.py:97-101, 117-119` — the new streaming path persists merged progress after every graph node (`db.update_job(job_id, state)`, line 72) — script, render_paths, statuses. But the `asyncio.TimeoutError` and generic `Exception` handlers write `db.update_job(job_id, initial_state)` — the bare original dict (`script=None`, empty paths). LangGraph `astream(stream_mode='values')` never mutates the input dict, and `db.update_job` does a **full replacement** (`json.dumps(state)`, no merge). So a timed-out/crashed job's record is reset to empty, destroying all live progress. Concrete trigger: a job that finishes script→codegen→validation (persisting state) then hits the wall-clock timeout during a long assembler render (`graph.py:352-353` notes this legitimately outlasts the timeout). Regression is new — pre-change used `ainvoke` with no per-node persistence, so the overwrite had nothing to lose.
**Fix:** track latest streamed state at `run_pipeline` scope; on failure persist `{...last_state, status:'failed', overall_error:...}` instead of `initial_state`.

### H3 — `validator/main.py` caption safe-zone check false-positives on positional `buff`
`services/validator/app/main.py:299-315` — the new caption safe-zone AST check resolves `buff` only from `node.keywords` (line 303), never `node.args[1]`. Manim CE's `to_edge(edge, buff=...)` / `to_corner(corner, buff=...)` accept `buff` as the **second positional arg**. So idiomatic `.to_edge(DOWN, 1.5)` / `.to_corner(DR, 2.0)` leave `buff_kw=None`, making `buff_kw is None or (...)` True → false flag. Returns `success=False`; orchestrator (`graph.py:189-195`) records a per-scene failure and increments retries (capped <5, `graph.py:170`), so repeated false positives can exhaust the budget and fail a correct scene. Verified by reproducing with the project's exact AST logic.
**Fix:** also read `pos_buff = node.args[1] if len(node.args) > 1 else None`; resolve numeric buff from either source; flag only when neither is supplied or a resolved numeric buff `< 1.2`.

## HIGH — rejected by verification (no action required for the stated trigger)

### R1 — `orchestrator/db.py` PRAGMA poisoned thread-local — REJECTED
`db.py:29-34` — claim was that a failing `PRAGMA journal_mode=WAL` (run after `self._local.conn` assignment, before the `try`) leaves a half-configured connection cached forever. **Rejected (medium confidence):** WAL support is deterministic per-filesystem; `main.py:10` imports `db` at module load → `__init__` → `_init_db()` → `_get_connection()` on the **import thread with no try/except**, so a real WAL-unsupported `/workspace/jobs.db` crashes process startup (loud fail-fast), never reaching the silent-poison-and-reuse mode described. The only path to a cached half-config is a transient `database is locked` race the finding doesn't name, and even then the connection stays usable. The build-then-assign hardening is still reasonable but not required.

---

## MEDIUM (fix recommended)

- **`html_validator.py:154-158`** — same-track overlap epsilon `1e-6` is smaller than the 0.001 timing-emit granularity → spurious fatal overlap error on valid composer output (caption end double-rounds one LSB above next scene start). Use `1e-3` tolerance or compare values rounded to 3 decimals.
- **`compositor/main.py` `_render_project`/`_assemble_chunked`** — `subprocess.run(timeout=...)` raises `TimeoutExpired` (and `OSError` if `node` missing), not `AssemblyError`; the per-chunk handler only catches `AssemblyError`, so a chunk-render timeout loses its "chunk k/N" context and returns a raw-traceback 500. Re-raise `TimeoutExpired` as `AssemblyError`, or broaden the handler.
- **`compositor/main.py` `_assemble_chunked:195-217`** — all chunks share `comp_dir`; `compose_html` accumulates `scene_*.html` from every chunk into `comp_dir/compositions/`, unbounded and never cleaned. Render per-chunk isolated dirs or clear `compositions/` per chunk.
- **`orchestrator/main.py:131-136` `analyze_topic_endpoint`** — `httpx` calls + `raise_for_status()` unwrapped; upstream 422/503/connect-timeout surfaces as opaque 500 on a public endpoint. Map `HTTPStatusError`→matching/502, `RequestError`→503.
- **`orchestrator/main.py:72`** — synchronous SQLite `update_job` (connect/execute/commit + full `json.dumps`) now runs on every graph node inside the async coroutine, blocking the event loop (up to ~5s with `busy_timeout`). Use `await asyncio.to_thread(...)` and/or throttle to status-change only.
- **`shared/models/agent_state.py:25`** — `dropped_scenes: List[int]` added as a required key to a `total=True` TypedDict, but `initial_state` (`main.py:55-62`) never sets it → type-checker error + `KeyError` footgun for any future `state["dropped_scenes"]` on legacy/failed/pre-voiceover jobs. Use `NotRequired[List[int]]` / `Optional` and initialize it; read via `.get(..., [])`.
- **`shared/schemas/common.py:55`** — `max_duration_seconds: Optional[int]` unbounded while sibling `target_duration_seconds` is `ge=60, le=2400`. Orchestrator clamps `target = min(target, max_duration_seconds)` (`main.py:145-148`), so a client POSTing `max_duration_seconds=5` (or negative) drives target below the 60s floor into timeout/pacing math. Add `Field(ge=60, le=2400)`.
- **`script-writer/analyzer.py:30-33,244-257`** — user `topic` interpolated into the LLM prompt unbounded (`AnalyzeRequest.topic` is an unconstrained `str`); cost/latency amplification + prompt-injection surface, newly reachable via the modified `/analyze`. Add `Field(min_length=1, max_length=2000)` and/or trim in `analyze_topic`.
- **`council.py:120` `_renumber_and_enforce_invariants`** — `(s.get("title") or "")[:80]` and raw `s["narration_text"]` assume str; a numeric LLM value → `TypeError`/`'int' not subscriptable` or Pydantic `ScriptResponse` validation failure → 500. This is the declared sanitization boundary yet itself unguarded. Coerce with `str(...)`.
- **`tests/test_generation_request_compat.py:41-45` `test_target_clamp_to_max_helper`** — tautology: reimplements the clamp inline and asserts its own `min()` result; exercises no production code (passes even if `orchestrator/main.py:147-149` is deleted/inverted). Extract a real `clamp_target_to_max` helper and assert on it.

## LOW

- `duration_prober.py:77-78` — docstring still claims `Raises: AssemblyError`; per-scene probe now degrades silently. Update docstring.
- `html_validator.py:163` — caption detection uses substring `"lower-third" in cls`; matches `lower-third-note` etc. Use `"lower-third" in cls.split()`.
- `compositor/main.py:146-155 _has_audio_stream` — returns True ("assume audio") on any ffprobe failure, defeating audio-normalization in the exact failure mode it guards; concat `-c copy` then fails. Branch on `COMPOSITOR_FAIL_CLOSED` or log a warning.
- `orchestrator/graph.py:356-358` — `planned_total` divides by `SCRIPT_WORDS_PER_SECOND`; env `=0` → `ZeroDivisionError` (caught broadly → confusing "failed" job). Guard `wps = settings.SCRIPT_WORDS_PER_SECOND or 2.2`.
- `orchestrator/db.py:33` — `PRAGMA journal_mode=WAL` silently no-ops on unsupported FS (returns actual mode, never read); concurrency mitigation can silently fail. Read result, warn if `!= 'wal'`.
- `validator/main.py:60-62 _reencode_for_seek` — docstring claims "permissive, never fails a scene" but raises `RuntimeError` when `COMPOSITOR_FAIL_CLOSED`. Note the conditional.
- `voiceover/main.py:184,249` — `VOICEOVER_RETRY_BACKOFF_SECONDS` unclamped; negative env → `asyncio.sleep(neg)` ValueError on first retry. Clamp `max(0.0, ...)`.
- `script-writer/main.py:7,10` — dead imports after council refactor (`timed_block`, `log_llm_call`, `json`); also drops per-call `log_llm_call` observability. Remove unused; optionally re-add metric in `council._call_json`.
- `script-writer/analyzer.py:156-158` — when 4 presets returned and none equals `recommended`, the inject guard (`len < 4`) skips it, so the duration question renders with no option marked "Recommended". Snap recommended to nearest preset or always represent it.
- `script-writer/budget.py:22-23` — same `SCRIPT_WORDS_PER_SECOND` zero-division as graph.py, across `narration_seconds`/`scene_slot_seconds`/`audit`/`repair_budgets`/`clamp_durations`. Guard the divisor.
- `council.py:217 _section_writer` — `section.get("scene_count_hint", max(2, int(budget_s/25)))` eagerly evaluates default; string `time_budget_seconds` → `TypeError` (caught, but section yields 0 scenes → short video). Coerce numeric before arithmetic.
- `assembler` deletion — naming alias survives (`ASSEMBLER_URL`→`http://compositor:8005`, `assembler_node`, `AssemblerRequest/Response`) but every ref resolves to the live compositor; **no runtime breakage** (verified end-to-end: compose, docker-compose, orchestrator routing, validator lint, health map). Optional cosmetic rename only.
- `assembler` deletion — docs/spec/graphify artifacts still list `services/assembler/app/main.py` (copilot-instructions pipeline diagram, FINAL_STATUS, graphify-out). No runtime impact; regenerate graphify + update the diagram when convenient.

---

## Files reviewed
Modified (source): code-generator/main, compositor/{duration_prober,html_validator,llm_composer,main}, orchestrator/{core/graph,db,main}, script-writer/main, validator/main, voiceover/main, shared/config, shared/models/agent_state, shared/schemas/{common,requests,responses}.
New (source): compositor/chunking, script-writer/{analyzer,budget,council}, shared/timeouts.
Deleted: services/assembler/app/{main,__init__}, infrastructure/docker/Dockerfile.assembler.
Tests: 11 changed/new (validity-reviewed).
Clean (no findings): code-generator/main, llm_composer, shared/config, schemas/{requests,responses}, chunking, timeouts, schema-consistency cross-check.
