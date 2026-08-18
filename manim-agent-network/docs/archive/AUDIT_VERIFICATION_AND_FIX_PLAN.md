# Pipeline Audit — Verification Results & Robust Fix Plan

> **STATUS: IMPLEMENTED (2026-07-05).** All workstreams below (WS-0..WS-8) plus
> three follow-ups (retry-history escalation to code-gen, persistent
> SigLIP-embedding image cache, A/V pacing gate) are merged into the source
> tree. Test state: tests/ 154 passed, web-tier 37 passed, voiceover 5 passed.
> Containers must be rebuilt for the changes to take effect.

**Date:** 2026-07-05
**Input:** `docs/PIPELINE_AUDIT_SPEC.md` (401 lines, 308 active findings)
**Method:** 9 parallel read-only verification agents, one per file cluster, each claim checked against current source with file:line evidence.

---

## 1. Verification summary

Of the ~90 named findings in the spec, the verification confirms the spec is **substantially accurate**: the systemic root causes (FR-2, FR-3, FR-4, FR-5, FR-7, FR-8, FR-9, FR-10, CQ-1..CQ-11 core) all hold. **11 findings are refuted or materially overstated** and should be downgraded/closed. Two findings are **worse than the spec states** (F22, FR-3 — they compound).

### 1.1 Confirmed as written (highest impact)

| ID | Verdict | Evidence |
|---|---|---|
| FR-3/F293 | **CONFIRMED — CRITICAL** | `render-job.yml:81` runs `python scripts/runner_neon_mirror.py`; no `scripts/` dir exists anywhere. **And web-tier `dispatch.py:9-29` dispatches via GitHub Actions `workflow_dispatch` — CI IS the production render path.** Every dispatched job dies at this step. |
| F22 | **CONFIRMED — worse than spec** | `add_usage()` defined in web-tier `db.py:223-239`, called by **nothing** in the repo (only tests). The intended writer was the missing runner script. Monthly budget gate sums zeros → **budget enforcement is a complete no-op**. |
| FR-2/F256 | CONFIRMED | `graph.py:35` `raise_for_status()`; nodes catch bare `Exception` (117-119, 311-313) and bump the same `retry_counts` used for content failures. Brief validator outage permanently fails jobs. |
| FR-7a/F220/F305 | CONFIRMED | `_get_semaphore()` / `_async_rate_lock` create-when-None only (llm_client.py:112-122, 149-164); docstring promises loop-recreation that doesn't exist. |
| FR-7b/F219/F108 | CONFIRMED | `await asyncio.sleep(wait)` held **inside** `_async_rate_lock` (158-164) → all async LLM calls fully serialized. Council "parallel" writers and NIM_MAX_CONCURRENT=6 are decorative. |
| FR-8/F255/F117 | CONFIRMED | NIM path can return `content=None`; Claude refusal returns `""` as a normal response (395-417). `code-generator/main.py:674` bare `json.loads` inside the 3-attempt loop with only an outer catch-all that re-raises — malformed/None content aborts the scene attempt instead of retrying. |
| FR-9/F38/F165/F318 + F67/F254 | CONFIRMED | Compositor `preexec_fn=os.setsid`+`os.killpg` unconditional (main.py:134-153) — AttributeError on win32. Validator manim kill uses no process group (grandchild leak) and no rlimits. |
| FR-10/F14/F260/F44/F319/F170 | CONFIRMED | Vision-inspect exception → `return True, ""`; HF lint fail-open unless `COMPOSITOR_FAIL_CLOSED`; `_has_audio_stream` bare `except: return True` (also duplicated in postprocess.py); vision "majority" is absolute `len(bad) >= 2` — wrong for <3 frames. |
| FR-4/F39/F288/F321/F144 | CONFIRMED | Future created via deprecated `get_event_loop().create_future()` (main.py:301); popped only on owner success/error paths; cancellation orphans it; waiters have no `wait_for`. |
| F41/FR-5 | CONFIRMED | Voiceover: ffprobe (31), piper (234), ffprobe (281) — no `timeout=`. Compositor: only `probe_duration` (duration_prober.py:50) lacks timeout; other compositor subprocs have them. |
| FR-6/F40/F134 | CONFIRMED | `streams[0]["duration"]` (duration_prober.py:57) — wrong stream / KeyError risk. |
| F257 | CONFIRMED | `_normalize_audio_streams` runs sync `subprocess.run` from async `_assemble_chunked` without `to_thread` — blocks the event loop (health checks go dark mid-assembly). |
| F132 | CONFIRMED | HF-drop loop re-renders the whole film per bad scene; no time/iteration bound. |
| F45 | CONFIRMED | Final caption window can go negative → silently skipped → captions vanish. |
| F47/F48 | CONFIRMED | Concat `timeout=600` hardcoded (postprocess has `_timeout_for` unused here); freeze-pad never re-probes output. |
| F185 | CONFIRMED — divergent | Sanitizer 13 forbidden builtins incl. `vars/getattr/setattr/delattr`; validator (the **live** gate) only 9. F80: `check_manim_security()` has zero callers — the stronger list is dead. |
| CQ-1/F146 | CONFIRMED | Zero matches for rubric/score/critique/quality beyond binary vision verdict. Only renderability is gated. |
| CQ-2/F147 | CONFIRMED | `_full_council`: planner → per-section writers (gather+semaphore) → `scenes.extend`. No selection, no coherence pass, failed section → `[]` silently. |
| CQ-3/F148 | CONFIRMED | Reviewer sees `narration_text[:200]`, no `visual_description`. |
| CQ-4/F158 | CONFIRMED | No source material, no anti-fabrication directive anywhere in planner/writer prompts. |
| CQ-6/F151, CQ-7/F153 | CONFIRMED | HF prompt: rules only, zero worked example. Manim few-shot uses `there_and_back` for a MoveAlongPath entrance — exactly what `manim_rules.md:228-237` forbids. |
| CQ-10/F154/F156/F238/F239 | CONFIRMED | Keep-floor 5.0 = "loosely related", no sort by score, first-number parse, SigLIP exception → 1.0 pass, below-threshold best-image fallback. |
| CQ-11/F2/F109 | CONFIRMED | Validator sends OpenAI `image_url` blocks (validator main.py:264-274); `_ClaudeCompletions` assumes string content, no translation layer, no thinking, temperature intentionally dropped. |
| F202 | CONFIRMED — sharper than spec | `del cleaned[-2]` with **no length guard** — can delete an arbitrary mid-script scene on short scripts. |
| F249 | CONFIRMED | `extract_keywords` is sync LLM call invoked directly on the event loop (main.py:165, no `to_thread`) — blocks. |
| F21 | CONFIRMED | 4 quota reads then insert, no transaction (web-tier main.py:128-139). |
| F61/F62/F63/F64/F65 | CONFIRMED | All config-drift claims verified exactly (compose 300/4/180 vs code 480/8/300; edge_tts vs piper; IMAGE_EVAL_MODEL set in compose vs "empty→skip" contract). |
| F294/F295 | CONFIRMED | Zero healthchecks, short-form depends_on; CI mem_limits sum to exactly 7168 MB on a 7 GB runner — zero headroom. |
| F296/F299/F304, F70 | CONFIRMED | Unpinned chrome fetch at build; `:latest`-only tags; no compose-config CI check; config 360 min vs workflow `timeout-minutes: 350` (CI env override 333 min partially mitigates). |
| Also confirmed | | F164 (dead stage alias), F271 (render_mode out-of-band — works but schema smell), F272 (node_timings undeclared), F312/F315 (unguarded `res[...]`/`state["script"]` — `validation_router` TypeError if script None), F314 (silent file-read swallow), F280, F111, F112, F159, F181, F286, F81, F84, F203, F235, F237, F240, F250 (zero image-fetcher tests), F3, F6, F66, F90, F175, F259, F283, F325, F307/F113, F118, F120, F224. |

### 1.2 Refuted / overstated — downgrade or close

| ID | Correction |
|---|---|
| **FR-1 Effect A (resume)** | **Overstated.** `_revive_scene_keys` covers all 7 scene-keyed dicts and runs on every DB load path (`get_job`, `list_running_jobs`); resume state passes through it. Resume is NOT broken by key typing today. **Effect B (scene-video 404) is real** (`main.py:580`, str param vs int keys). Residual risk: the `_SCENE_KEYED` whitelist is duplicated knowledge that can drift — fix the fragility, not a live resume bug. |
| **FR-16 "off-by-one, 6 attempts"** | Disputed. All three sites use `< 5` consistently; no inter-module disagreement found. Triplicated literal confirmed (hoist it), off-by-one claim unproven. |
| **FR-11 script_meta drop (F274)** | Refuted — `script_meta` persists across resume; the skip node never touches it. The forced `status='validation'` + cleared `code_paths/retry_counts/error_logs` part stands. |
| **F131/F172 VTT ≥1h regex** | Refuted — `(\d+(?::\d+)?:\d+\.\d+)` matches `HH:MM:SS.mmm`; `_vtt_ts` emits compatible format. No bug. |
| **F278 assembler key coercion** | Safe today — dicts pass to Pydantic in-process (no JSON round-trip), int keys preserved. Keep as a contract test, not a bug. |
| **F308 sleep-in-semaphore** | Refuted — backoff sleeps run on `to_thread` workers; semaphore released before dispatch. |
| **F12 Kokoro gap** | Refuted — inter-sentence silence IS written to the audio (only trailing silence dropped); cue timing consistent. |
| **F43 audio_segments keys** | Already handled — `_segs_for` tries both `sid` and `str(sid)`. |
| **F248 log contextvars** | Refuted — `ContextVar` is per-task under asyncio; no leak. |
| **F24 get_or_create_user TOCTOU** | Refuted — whole block runs inside `engine.begin()` transaction. |
| **F71 assembler-timeout collision** | Refuted — chunk budget caps at 3600s, far under the 14400s assembler cap. |
| **CQ-5/F149 clamp-after-audit** | Partial — sequence is audit → repair → clamp → **re-audit (line 441)**. A post-clamp audit exists; verify which audit is *persisted/reported* before touching this. |
| **F150 word_budget** | Partial — `word_budget` IS passed to the model (inside the budgets JSON in the prompt). Real gap: no post-repair validation that word counts hit budgets. |
| **CQ-9/F152 classifier bias** | Partial — `scene.content_type` from script-writer IS primary (main.py:740); keyword heuristic is fallback-only. Bias exists only in the fallback. |
| **F222 Mistral fallback** | Nuanced — fallback IS implemented, but in code-generator as raw `httpx` (`_mistral_chat`), bypassing the client abstraction (= F112). Fix is consolidation, not implementation-from-scratch. |
| **FR-14 fail-late secrets** | Partial — orchestrator DOES assert LLM keys at startup (main.py:39-40). Gap is the other services (pexels/pixabay/mistral/web-tier). |
| **F42 drift check** | Valid check, redundant re-probe — optimization, not correctness. |
| **F4 double-clean** | Weak — both paths apply the same `_clean_for_tts`; divergence unproven. Low priority. |

### 1.3 New findings surfaced during verification

1. **`require_admin()` auth bypass** (web-tier `auth.py:67-70`, comment "ponytail: auth bypassed") — always returns dev admin. Security scope, but it's a ship-blocker; tracked in the separate security review.
2. **`node_timings`** grows unbounded and is untyped — minor, fold into F272.
3. **F249 upgraded**: sync `extract_keywords` directly blocks the image-fetcher event loop (spec had it as observability/timeout issue; it's an event-loop blocker like F257).

---

## 2. Robust fix plan

Design principle: fix **classes**, not instances. Five shared mechanisms eliminate ~70% of the findings; the rest are local patches. Workstreams ordered by dependency.

### WS-0 — Revive production (FR-3 + F22 + F299) — *blocks everything*

The render path is: web-tier → GitHub `workflow_dispatch` → runner → **missing script**. Nothing ships until this exists.

1. **Write `scripts/runner_neon_mirror.py`** (single file, stdlib + httpx + psycopg):
   - Read job params from the Neon row for `job_id` (input from workflow dispatch).
   - `POST $ORCH_URL/generate`, poll `GET /job/{id}` with backoff until terminal.
   - Mirror every status transition to Neon (`UPDATE jobs SET status, stage, error`).
   - On success: upload mp4 to R2, write the R2 key to Neon, **call web-tier `add_usage(owner, month, actual_minutes)`** — this single line also fixes F22 (budget gate becomes real).
   - On failure/timeout: mark Neon row failed with the orchestrator's error payload.
2. **CI guard**: a lint job that runs `test -f scripts/runner_neon_mirror.py` and `docker compose -f docker-compose.yml -f docker-compose.ci.yml config -q` (F304).
3. **Image immutability** (F299): `build-images.yml` pushes `:${{ github.sha }}` + `:latest`; `render-job` dispatch carries the sha as `IMAGE_TAG`.

*Effort: ~1 day. Test: dispatch a real workflow against a staging Neon row.*

### WS-1 — `shared/llm_client.py` rewrite of the concurrency/retry core (FR-7, FR-8, F224, F307/F113, F120, F116, F117, F222/F112, CQ-11 transport half)

One module; fixes propagate to all 6 services.

1. **Loop-keyed primitives**: replace the two globals with
   ```python
   _LOOP_STATE: dict[int, tuple[asyncio.Semaphore, asyncio.Lock]] = {}
   def _loop_state():
       loop = asyncio.get_running_loop()
       key = id(loop)
       if key not in _LOOP_STATE:
           _LOOP_STATE[key] = (asyncio.Semaphore(_MAX_CONCURRENT), asyncio.Lock())
       return _LOOP_STATE[key]
   ```
   (WeakKeyDictionary on the loop if leak-averse.) Delete the lying docstring.
2. **Rate slot outside the lock**: under the lock compute `slot = max(now, last + interval)`, set `last = slot`, release, then `await asyncio.sleep(slot - now)`. Callers now sleep concurrently. Share one pacing clock between sync/async paths (single monotonic value guarded by the same discipline) — closes F120.
3. **Typed error taxonomy** (exported from the module):
   - `LLMEmptyContent` (content falsy / `finish_reason` in `refusal|content_filter|length`) — retryable-by-caller.
   - `LLMTransient` (429/5xx/timeouts after client-side budget exhausted).
   Raise instead of returning `None`/`""`. Callers (code-gen 674, council, vision paths) catch and feed the retry loop.
4. **One retry budget**: `TRANSIENT_MAX_ATTEMPTS` applied to 429 AND 5xx/timeouts (429 may still scale with key count, but bounded by the same named constant). `Retry-After` parsed defensively (`float` → fallback `parsedate_to_datetime` → fallback backoff), jitter added.
5. **Claude adapter completeness**: translate OpenAI `image_url` content blocks → Anthropic `{"type":"image","source":{"type":"base64",...}}`; on refusal raise `LLMEmptyContent`; keep temperature-drop but document at the adapter; decide `thinking` explicitly (off + comment, or adaptive for code-gen).
6. **Absorb Mistral**: add `_MistralCompletions` to `_RoutingCompletions`; delete code-generator's raw `_mistral_chat` and guard `_nim_down_until` with an `asyncio.Lock` (F111) — fallback now gets pooling/retry/pacing for free.
7. **Tolerant JSON extraction** helper (`strip fences → outermost {}`) used by every `_call_json`-style consumer (F116).
8. **Tests** (F333): mocked httpx — 429 rotation, Retry-After date parse, budget exhaustion, loop-swap semaphore recreation, image-block translation, refusal→typed error.

*Effort: ~1.5 days. This single workstream restores real parallelism (council writers, 6-way NIM) and un-breaks vision QA transport.*

### WS-2 — Orchestrator control plane (FR-2, FR-1 residual, FR-16, FR-11, FR-12, FR-17, F271, F272, F312/F315, F314, F164)

1. **Error classification in `_post`**: catch `httpx.ConnectError/ReadTimeout/HTTPStatusError(5xx)` → raise `InfraUnavailable(service, detail)`; nodes retry it with bounded backoff (3× exp, per node-call) **without touching `retry_counts`**; if still down, fail the node with "service X unavailable" — job pauses as resumable, not permanently failed. Content failures keep the existing budget.
2. **Key-typing single source of truth**: derive the revive whitelist from the schema instead of a hand list:
   ```python
   _SCENE_KEYED = {k for k, t in LangGraphState.__annotations__.items()
                   if typing.get_origin(t) is dict and typing.get_args(t)[0] is int}
   ```
   Declare `node_timings: list[dict]` in `LangGraphState` (F272) and add `render_mode: str | None` to `GenerationBrief` (F271). Route param `scene_id: int` (fixes the always-404). Round-trip test: state → json.dumps/loads → revive → router skips completed scenes.
3. **`settings.MAX_SCENE_RETRIES`** referenced at graph.py 232/329/392; router unit tests define the attempt semantics explicitly (settles the off-by-one dispute with a test instead of an argument).
4. **Resume**: neutral `resuming` status; stop clearing `previous_code`; keep clearing `retry_counts` only for infra-failed scenes. Guard `validation_router` for falsy `script` → route `failed` with explicit error (F315); `.get()` + contract-violation log for `res` fields (F312); log+drop on previous_code read failure (F314). Delete `voiceover_and_images` alias (F164).
5. **`_DRIVING`/`_CANCEL` → DB columns** (`driver_owner` claimed via `UPDATE ... WHERE driver_owner IS NULL` returning-row, `cancel_requested` bool polled by the stream loop). Works with >1 worker; in-process sets become a cache.
6. **Per-node timeout**: wrap each `astream` step in `asyncio.wait_for(node_budget)` sized from `shared/timeouts.py`; on outer wall-clock timeout persist `failed`, POST best-effort `/cancel` downstream, **log instead of re-raise** (F258). Align `JOB_TIMEOUT_MAX_SECONDS` ≤ 340 min (F70).

*Effort: ~1.5 days including tests (F130/F104/F270 router tests come free here).*

### WS-3 — Subprocess safety, one shared helper (FR-5, FR-9, F67/F254, F66, FR-6, F41, F48, F257, F249)

1. **`shared/proc.py`**: single `run_proc(cmd, timeout, *, input=None, cwd=None)`:
   - `timeout` is a **required** positional — impossible to forget.
   - POSIX: `start_new_session=True`; on timeout `os.killpg(pgid, SIGKILL)`.
   - Windows: `creationflags=CREATE_NEW_PROCESS_GROUP`; on timeout `proc.send_signal(CTRL_BREAK_EVENT)` then `terminate()`.
   - Converts `TimeoutExpired` → typed `ProcTimeout`.
   Replace every raw `subprocess.run/Popen` in voiceover (31, 234, 281), compositor (`probe_duration`, render subprocess), validator (manim, ffmpeg) with it. Kills FR-5, FR-9, F67/F254 in one sweep, and every future subprocess call inherits the fix.
2. **`probe_duration`**: `ffprobe -show_entries format=duration -of json`, fallback to max of stream durations, `timeout=120`, raise typed `AssemblyError` on absence. Re-probe freeze-pad output and store measured duration (F48).
3. **Event-loop hygiene**: `await asyncio.to_thread(...)` around `_normalize_audio_streams` (compositor main.py:267) and `extract_keywords` (image-fetcher main.py:165).
4. Optional (Linux only): `resource.setrlimit(RLIMIT_AS)` hook in `run_proc` for the validator render (F66).

*Effort: ~1 day.*

### WS-4 — Compositor assemble path (FR-4, F45, F46, F47, F132)

1. `/assemble` dedup:
   ```python
   fut = asyncio.get_running_loop().create_future()
   _ASSEMBLING[job_id] = fut
   try:
       result = await _do_assemble(...)
       fut.set_result(result); return result
   except BaseException as e:          # incl. CancelledError
       if not fut.done(): fut.set_exception(e)
       raise
   finally:
       _ASSEMBLING.pop(job_id, None)
   ```
   Waiters: `await asyncio.wait_for(asyncio.shield(fut), timeout=assembler_http_timeout)`.
2. Concat: scale timeout with `_timeout_for(total)` (already in postprocess); write absolute resolved paths in the list file (F46).
3. Caption windows: clamp final `dur = max(0.001, ...)` + warn (F45).
4. Bisect bound: cap drop iterations (e.g. 3) or a cumulative time budget, then fall back to Manim-only survivors (F132).

*Effort: ~0.5 day.*

### WS-5 — Content quality loop (CQ-1..CQ-11) — *the product lever*

1. **Quality gate node (CQ-1)** — new step between validator success and "scene done":
   - Input: 1–3 rendered frames + full narration + visual_description.
   - Rubric (single cheap vision call, JSON): `match_narration: 1-5, legibility: 1-5, adds_insight: 1-5, worst_problem: str`.
   - `min(scores) < 3` → regenerate with `worst_problem` + rubric verbatim appended to the retry prompt. Max 2 quality iterations per scene (separate counter from the content-failure budget of WS-2). After cap: accept but mark scene `degraded` in state; job status `success_degraded` if any scene degraded — visible, not silent.
   - **Fail-closed**: rubric-call failure = one retry then `degraded`, never silent pass. (Transport fixed by WS-1 so Claude vision actually works — CQ-11.)
2. **Council upgrade (CQ-2, F202, F201)** — pragmatic version, not a rewrite:
   - Give each section writer: adjacent sections' goals + a shared style/terminology contract emitted by the planner.
   - Failed section → hard error (retry once, then fail the job) instead of silent `[]`.
   - Single coherence pass at the end: one LLM call over all scene titles+first-sentences to fix transitions/terminology (cheap, high yield).
   - Merge loop: preserve `visual_description`/`title` on merge; guard `del cleaned[-2]` with `len(cleaned) >= 4` else merge the shortest adjacent pair.
   - Best-of-N candidate scripts: defer — measure after the above; it triples script cost.
3. **Reviewer (CQ-3)**: full `narration_text` + `visual_description` (scripts fit in context); per-scene rewrite suggestions for the worst 3 scenes fed into `_writer_fix`.
4. **Grounding (CQ-4)**: accuracy directive in planner+writer system prompts ("prefer well-established facts; never invent statistics, dates, quotes; keep uncertain claims qualitative"). Retrieval grounding: defer to P2.
5. **Few-shot (CQ-6/CQ-7)**: 2 HF worked examples (split-screen comparison; big-number stat) rotated by scene role; replace `there_and_back` in the Manim few-shot with an ease that lands + `self.wait`. Dedup the visibility rule to hf_rules.md only (CQ-8).
6. **Pacing (CQ-5, F200, F150)**: confirm which audit is persisted; if pre-clamp, persist the post-clamp re-audit (line 441) instead. Enforce `brief.max_duration_seconds` clamp at `generate_script` entry. Post-repair check: re-count words vs `word_budget`, one corrective iteration.
7. **Imagery (CQ-10, F235-F240, F249)**: keep-floor → 7; tier by score (≥8 / 6–7) then SigLIP order within tier; labeled score parse (`score:\s*(\d{1,2})`, cap max_tokens ~10); SigLIP exception → 0.0/skip (never 1.0); below-threshold → return empty (let scene render without image) instead of best-bad; cap candidates to N=12 before download; stream downloads with a 15 MB cap; 429 Retry-After backoff in the three clients; per-call timeout + gather with semaphore for vision vet.
8. **Classifier (CQ-9/F175)**: pass `content_type` in `ValidatorRequest` (orchestrator already knows it) and delete `detect_content_type` sniffing; keep `classify_scene` as fallback-only (verified it already is) with balanced keywords.

*Effort: ~3 days. The quality gate (item 1) is the single biggest lever; ship it first within this WS.*

### WS-6 — Config & deploy truth (FR-13, FR-14, FR-15, F63, F64, F65, F295, F296)

1. **One source of truth**: delete from docker-compose every env line that merely restates a differing default (`COMPOSITOR_CHUNK_*`, `VOICEOVER_FALLBACK_PROVIDER`, `IMAGE_EVAL_MODEL`) — code defaults win; keep only genuinely environment-specific values. Document intended prod values in one table in this repo's docs.
2. **Startup key assertions**: extend the orchestrator's existing pattern (main.py:39-40) into a `shared/config.require_keys("PEXELS_API_KEY", ...)` helper called in each service's startup hook. Fail at boot, not mid-job.
3. **Healthchecks**: `healthcheck: curl -sf localhost:PORT/health` (endpoints exist in all 8 services) + `depends_on: {svc: {condition: service_healthy}}` for orchestrator.
4. **CI memory**: cut to ~6 GB total (validator 2.5g, compositor 1g, voiceover 768m, others 512m) leaving headroom.
5. **Pin chrome-headless-shell** version + sha256 in Dockerfile.compositor.
6. `NVIDIA_READ_TIMEOUT_SECONDS` ≥ total or None; pass overrides to code-generator env (F64/F65).

*Effort: ~0.5 day.*

### WS-7 — Web-tier integrity (F21, F26; F22 fixed by WS-0)

1. Quota gates: single transaction — `BEGIN; SELECT count/minutes ... FOR UPDATE` (or atomic `INSERT ... SELECT ... WHERE` guard) around check+insert. Add dispatch-time estimated debit so the budget gate has signal even before the runner reports actuals.
2. `/cancel`, `/resume`, `/analyze`: make `async def` + `httpx.AsyncClient` (or keep sync def — FastAPI threadpools them — but then it's F26-refuted; verify which server config is in play before changing).
3. `require_admin` bypass: out of scope here, but do not ship anything until the security review's fix lands.

*Effort: ~0.5 day.*

### WS-8 — Test suite (spec §8, unchanged priorities, corrected targets)

1. `validation_router` table-driven tests incl. missing-script guard (F130/F104/F315).
2. State JSON round-trip + revive + router resume-skip (locks FR-1 against regression).
3. llm_client: loop-swap, rate-slot concurrency (assert two waiters sleep concurrently), retry budgets, image translation.
4. `run_proc` timeout/kill on both platforms (mock `os.killpg` on win32 CI).
5. Sanitizer battery + shared forbidden-list identity test (`assert sanitizer.FORBIDDEN == validator.FORBIDDEN` — after moving to `shared/security.py`, F185/F80: wire `check_manim_security` into code-gen pre-write OR delete it and import the shared set in the validator).
6. Compositor: bisect drop simulation, negative caption window, dedup-Future cancellation.
7. Image-fetcher: first real tests — magic bytes, score parse, tiering, 429 backoff.

*Effort: ~2 days, parallelizable with WS-5/6.*

### Sequencing

```
WS-0 (prod dead without it)
  → WS-1 (unblocks WS-5 vision QA; fixes all services' transport)
    → WS-2 + WS-3 + WS-4 (parallel)
      → WS-5 (content) + WS-6 + WS-7 (parallel)
        → WS-8 (continuous, starts with WS-2's router tests)
```

Total: ~10–11 focused days. After WS-0..WS-4, fragility findings are structurally closed (shared helpers prevent recurrence). After WS-5, the content-quality root cause (no feedback loop) is closed with bounded cost (≤2 extra vision calls + ≤2 regenerations per scene worst-case).

### Closed as no-fix-needed (verification refuted)

F131/F172 (VTT regex), F278 (assembler keys), F308, F12, F43, F248, F24, F71, F274 (script_meta), FR-1 Effect A as a live bug. FR-16's "6 attempts" claim: settle via WS-8 router test, not code churn.
