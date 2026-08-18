# manim-agent-network — Pipeline Audit & Remediation Spec

**Date:** 2026-07-05
**Scope:** Backend pipeline only. Frontend and security findings are **out of scope** for this document (a separate security review lists 16 security findings, incl. an open-admin-auth ship-blocker — track those separately).
**Method:** 18 finder agents mapped the full backend across per-service and cross-cutting dimensions → 334 raw findings. Adversarial verification was cut short by an org spend limit; 41 findings received a formal verdict (30 confirmed, 10 refuted, 1 uncertain). The remaining findings are **unverified** but the highest-impact ones are **cross-corroborated by 3–4 independent finder agents**, which this spec treats as strong signal. Verdict status is marked per finding.

---

## 1. Executive summary

The pipeline works on the happy path but is **fragile under any deviation** and produces **mediocre content by design**, not by accident. Both of the operator's stated pains trace to specific, fixable root causes — not vague flakiness.

- **308 active pipeline findings** (security excluded): **3 critical, 44 high, 104 medium, 157 low**.
- **Fragility** is dominated by five systemic root causes, each reported independently by multiple agents: (1) an int-vs-str `scene_id` key mismatch that breaks resume and the scene-video endpoint; (2) transient infra errors consuming the per-scene LLM retry budget and permanently failing jobs; (3) missing subprocess timeouts across voiceover/compositor; (4) an `asyncio` semaphore/rate-lock in `shared/llm_client.py` bound to a dead event loop **and** serializing all "parallel" LLM calls; (5) POSIX-only process handling that cannot run on the documented Windows host.
- **A CI job references a runner script that does not exist in the repo** (`scripts/runner_neon_mirror.py`) — if CI is the production render path, every dispatched job fails. **Verify this first.**
- **Content quality** has one overarching root cause: **there is no quality feedback loop.** The validator gates only *renderability*; a scene that renders but is dull, off-topic, or contradicts the narration ships as "success." Compounding this: the council concatenates section writers with no best-of/coherence pass, the reviewer critiques a 200-char truncated narration, HyperFrames has no few-shot example (→ templated "AI slop"), there is no fact-grounding, and the vision-QA path is silently broken for Claude models.

**Verdict — fragility:** real and systemic; ~10 findings explain the bulk of run failures. Fixable in a focused P0/P1 pass.
**Verdict — content quality:** structural. Prompt tweaks alone won't fix it; the missing quality-gate + council selection + fact-grounding are the levers.

---

## 2. WHY THE PIPELINE IS FRAGILE

Ranked by likely failure frequency × blast radius. IDs in brackets; where multiple agents found the same root, all IDs are listed and the finding is stated once (canonical).

### 2.1 Single points of failure

**FR-1 — `scene_id` int-vs-str key mismatch [F252, F92, F128, F253, F273] — CRITICAL, 4 agents.**
Every per-scene dict (`render_paths`, `code_paths`, `retry_counts`, `error_logs`, `audio_paths`, `previous_code`, `image_paths`) is keyed by **int** `scene_id` throughout `graph.py`. Job state persists to SQLite as JSON, and **JSON object keys are always strings**. `db._revive_scene_keys` (db.py:24-35) coerces *some* keys back to int on load, but coverage is partial and the coercion is duplicated knowledge that can drift.
- **Effect A (resume):** on `_resume_worker`, per-scene dicts come back string-keyed; `scene_id in render_paths` checks in the graph miss → already-rendered scenes are re-rendered or the router misroutes. Resume is unreliable.
- **Effect B (API):** `GET /video/{job_id}/scene/{scene_id}` (orchestrator/main.py:575-583) takes `scene_id: str` and does `render_paths.get(scene_id)` against an int-keyed dict → **always 404**, even for successfully rendered scenes.
- **Fix:** one `_coerce_scene_keys(state)` helper applied at every DB load (or standardize on `str` keys graph-wide). Type the route param `scene_id: int`. Add a round-trip test: persist mid-flight state → JSON → reload → assert resume skips completed scenes.

**FR-2 — transient infra error burns the per-scene retry budget [F256] — HIGH.**
`_post` (graph.py:32-36) calls `response.raise_for_status()`; any 502 (validator restarting), 503, or connection-refused (service down/OOM) is caught in `_generate_one_scene`/`_validate_one_scene` as a **per-scene failure** that bumps `retry_counts`. That counter is capped at 5 and is **shared between genuine code/render failures and transient infra failures**. A brief validator outage exhausts the budget on all scenes → job **permanently failed** despite nothing being wrong with the content.
- **Fix:** classify exceptions in `_post` — `ConnectError`/`ReadTimeout`/5xx are infra-transient: retry with backoff against the same scene **without** consuming the LLM-quality retry budget, or fail-fast the node with a clear "service X unavailable". Keep the retry cap for content failures only.

**FR-3 — CI render driver script missing [F293] — CRITICAL if CI is the prod path.**
`.github/workflows/render-job.yml:80-81` runs `python scripts/runner_neon_mirror.py`. There is **no `scripts/` directory and no such file** anywhere in the repo. Every dispatched render job pulls images, starts the pipeline, waits for readiness, then dies at this step.
- **Fix:** add the runner (POST to `$ORCH_URL/generate`, poll `/job/{id}`, mirror status to Neon, upload mp4 to R2) or correct the path. Add a CI smoke check: `test -f scripts/runner_neon_mirror.py`.

**FR-4 — compositor `/assemble` dedup Future leaks / never times out [F39, F288, F321, F144] — HIGH, 4 agents.**
The in-flight `_ASSEMBLING[job_id]` Future is popped only by the *owner* on its success/error paths. If the owning request is cancelled (client disconnect / server timeout) between creating the Future and reaching a pop site, the Future is never resolved and never removed → **every subsequent `/assemble` for that job awaits a dead Future forever.** Also created via deprecated `asyncio.get_event_loop().create_future()` (may bind to the wrong loop).
- **Fix:** wrap the owner body in `try/finally` that always pops `job_id` and `set_exception` on an unresolved Future; use `asyncio.get_running_loop()`; wrap waiters in `asyncio.wait_for` so a stuck owner can't hang them.

### 2.2 Missing timeouts / unbounded loops / blocking calls

**FR-5 — subprocess calls with no timeout [F5, F41, F40, F134, F236, F155, F257] — HIGH.**
`subprocess.run` with **no `timeout=`** in: voiceover `_validate_audio` ffprobe (main.py:31), `piper` TTS (234), `_audio_duration` ffprobe (281); compositor `probe_duration` (duration_prober.py:50). These run inside `asyncio.to_thread` workers; a hung ffprobe (corrupt/partial file) or a piper that never exits **blocks a thread-pool worker forever**. Under `ORCH_VOICEOVER_CONCURRENCY=8` the pool exhausts and the service wedges.
- **Fix:** explicit `timeout=` on every `subprocess.run` (e.g. 30s ffprobe, bounded piper); convert `TimeoutExpired` into a typed failure, matching the validator's existing pattern.

**FR-6 — `probe_duration` reads the wrong stream and crashes on missing duration [F40, F134] — HIGH, 2 agents.**
`duration_prober.py:44-60` takes `streams[0]['duration']`. Stream 0 is often the *video* stream (or cover-art), not audio, and many MP4/WebM containers omit per-stream `duration` (it lives only in `format`) → `KeyError`/`IndexError` → `AssemblyError`.
- **Fix:** `ffprobe -show_entries format=duration -of json` (fall back to `max` of stream durations). Correct value, robust to stream order.

**FR-7 — `shared/llm_client.py` concurrency is doubly broken [F107, F108, F219, F220, F305, F306] — HIGH, 6 agents.**
Two distinct bugs, both systemic:
- **(a) Loop-bound singletons never recreated.** `_get_semaphore()` / `_async_rate_lock` are cached on first use and the docstring *claims* "Re-create if the loop changed" but the code only creates when `None`. An `asyncio.Semaphore`/`Lock` binds to the loop that created it; a second loop (uvicorn reload, pytest-asyncio teardown/setup, anyio worker) → `RuntimeError: bound to a different event loop` or silent mis-limiting.
- **(b) Sleep-under-lock serializes everything.** `_acquire_rate_slot_async` holds `_async_rate_lock` and `await asyncio.sleep(wait)` **inside** the lock. Callers can't even compute their wait until the previous caller finishes sleeping → all concurrent LLM calls are **fully serialized**, defeating `NIM_MAX_CONCURRENT=6` and `COUNCIL_MAX_PARALLEL_WRITERS`. Your "parallel" section writers run one-at-a-time.
- **Fix (a):** key the semaphore/lock by the running loop (recreate on mismatch) or hang them off an app-state object created in a FastAPI startup hook. **Fix (b):** compute the wake time under the lock, update `_async_last_request_time` to the scheduled slot, **release**, then sleep outside the lock. Delete the misleading comment either way.

**FR-8 — unguarded None/empty LLM content crashes the retry loop [F255, F110, F117] — HIGH.**
NIM/Mistral/Claude can all return `content=None` (content-filter stop, `finish_reason='length'` truncation, refusal). `code-generator/main.py:674` does `json.loads(response.choices[0].message.content)` with **no None-check and no `JSONDecodeError` handling** (unlike `council._call_json`, which guards). `json.loads(None)` → `TypeError`; truncated content → `JSONDecodeError`. Both surface as a generic caught exception with the wrong label, aborting instead of a clean retry.
- **Fix:** in both `_do_request` paths, raise a typed retryable error when content is falsy or `finish_reason` is `refusal`/`content_filter`/`length`. At call sites, guard content before `json.loads`, wrap in `try/except (TypeError, JSONDecodeError)`, set `error_log='model returned non-JSON'` and continue the local repair loop.

**FR-9 — POSIX-only process handling on a Windows host [F38, F165, F318, F67] — HIGH, 3 agents.**
compositor `_run_render_subprocess` (main.py:139-148) uses `preexec_fn=os.setsid` + `os.killpg(os.getpgid(...))`. These don't exist on Windows; the repo host is win32 and the module docstring says it's "Overridable for host-side testing" → `AttributeError` at `Popen`, **every host-side render fails**. Related: the validator's `manim` subprocess kill does **not** use a process group, so it **leaks grandchild processes** (stuck `dvisvgm`/`ffmpeg`) even on Linux [F67, F254].
- **Fix:** guard with `if hasattr(os, 'setsid')` / `sys.platform != 'win32'`; on Windows use `creationflags=CREATE_NEW_PROCESS_GROUP` + `proc.terminate()`, or `subprocess.run(..., start_new_session=True, timeout=)` (cross-platform). Mirror the process-group kill into the validator's `_run_manim_subprocess`.

**FR-10 — fail-open quality gates produce broken-but-"successful" videos [F260, F14, F44, F319, F170] — HIGH.**
Vision-inspect and HF-lint "fail open" (default to pass) on any error [F14, F260]; `_has_audio_stream` returns `True` on any ffprobe exception [F44, F319], masking silent chunks and corrupting the concat. Net: failures in the checks that are supposed to catch bad output instead **certify bad output as good**.
- **Fix:** fail-closed on quality checks where a false-pass ships a broken artifact; at minimum log loudly and mark the job `degraded` rather than `success`. `_has_audio_stream` should treat probe failure as unknown/false, not true.

### 2.3 Resume / idempotency / config drift

- **FR-11 — resume re-enters at the wrong stage [F275, F274, F164] — HIGH.** `resume_job` forces `status='validation'` and clears code/retry state, but the graph always streams from `START`; a job that died before voiceover resumes with **no `audio_segments`**, and `script_writer_node`'s resume-skip drops `script_meta` so art_director loses `topic_classification`. Fix: use a neutral `resuming` status and let the graph's resume-safe skips drive; preserve `previous_code` and `script_meta`.
- **FR-12 — in-process `_DRIVING`/`_CANCEL` sets defeat multi-worker resume [F267, F169] — MEDIUM.** These live in module globals; with >1 orchestrator worker/replica, resume idempotency and cancellation break. Fix: move to the DB/shared store.
- **FR-13 — config drift across the deploy boundary [F61, F62, F63, F64] — HIGH/MED.** docker-compose defaults disagree with `shared/config.py`: chunk params (compose 300/4/180 vs code 480/8/300), voiceover fallback (compose `edge_tts` vs code `piper` — and `edge_tts` violates the documented offline-first design and adds a network dependency), `IMAGE_EVAL_MODEL`. The running system behaves differently from every test and host import. Fix: one source of truth; drop the redundant compose env or align the code defaults, and document intended values in one place.
- **FR-14 — fail-late secrets [F60] — HIGH.** All API keys default to `""`; `Settings()` never validates that the keys a service needs are present. Missing key → no boot failure, just a 401 inside the first LLM call mid-job. Fix: per-service startup assertion that required keys are non-empty; fail-fast at container boot.
- **FR-15 — no healthchecks; readiness ≠ start-order [F294, F295] — HIGH.** No service defines a `healthcheck`; `depends_on` short-form guarantees only *started*, not *listening*. Orchestrator `_resume_running_jobs` fires before workers are ready. CI `mem_limit`s sum to 7 GB = the entire runner → OOM. Fix: add `healthcheck: curl -sf /health` (endpoints already exist) + `condition: service_healthy`; cut CI mem budget to leave ~1.5–2 GB headroom.
- **FR-16 — retry cap off-by-one and triplicated magic number [F129, F95, F313] — MED.** The cap `5` is a literal in three places (graph.py:232, 329, 392) that can drift; and the loop actually grants **6** attempts, not the documented 5. On a code-gen failure, `code_generator_node` (`<5`) and `validation_router` can disagree → silent stall. Fix: hoist to `settings.MAX_SCENE_RETRIES`, reference everywhere, fix the off-by-one, add router unit tests.
- **FR-17 — wall-clock timeout re-raises into `BackgroundTasks` void [F258, F77, F70, F71] — MED.** The outer wall-clock cap persists `failed` then re-raises into `BackgroundTasks` where nothing handles it; there is no per-node timeout inside the `astream` loop (one hung node hangs the whole job up to the outer cap); the orchestrator wall-clock (360 min) can exceed the GitHub Actions cap (~350 min). Fix: per-node timeouts; align caps; swallow-and-log the re-raise after persisting.

---

## 3. WHY THE GENERATED CONTENT IS LOW QUALITY

### 3.1 The overarching root cause

**CQ-1 — no content-quality feedback loop [F146] — CRITICAL.**
The only signal that flows back into regeneration is `error_log`/`previous_code`: a render crash, syntax error, or "vision: render appears empty/broken/cluttered." **Nothing scores whether the scene teaches the concept, has legible information hierarchy, or matches the narration.** A scene that renders perfectly but is dull, off-topic, or generic is accepted as success. This is the structural reason output is mediocre — the system optimizes for "it rendered," not "it's good."
- **Fix:** add a self-critique / quality-gate node after generation. Cheap LLM+vision rubric scoring 1–5 on: (a) does the visual match the narration, (b) information hierarchy/legibility, (c) does it add insight beyond the words. Below threshold → regenerate with the critique fed back as the retry prompt. Cap iterations (e.g. 2) to bound cost.

### 3.2 Scriptwriting

- **CQ-2 — council averages to mediocrity [F147] — HIGH.** `_full_council` fans out one writer per section and concatenates (`scenes.extend`). No best-of, no candidate-and-pick, no cross-section coherence pass. Each section is written blind to the others (only topic+goal) → broken transitions, inconsistent terminology/metaphors, no difficulty ramp. A failed section silently returns `[]`. Fix: either generate 2–3 candidate scripts and have the reviewer pick the best (a *real* council), or give each writer the adjacent sections' goals + a shared style/terminology contract and add a final stitch/coherence pass. Make a failed section a hard error, not a silent gap.
- **CQ-3 — reviewer critiques a truncated summary [F148] — HIGH.** `_reviewer` builds `compact` with `narration_text[:200]` and **discards `visual_description` entirely**, yet is asked to judge narration quality and scene-type fit. It can see neither the full narration nor any visual. The verdict is theater. Fix: send full narration + visual_description (scripts are small); emit per-scene rewrite suggestions for the worst N scenes; always run `_writer_fix` when any high-severity issue exists.
- **CQ-4 — no fact grounding [F158] — HIGH.** Writers/planner get only the topic string + "explain clearly." No sources, no anti-fabrication directive → confident plausible-but-wrong dates/numbers/formulas. For educational video this is a credibility failure. Fix: add an accuracy directive ("prefer well-established facts; do not invent specific statistics/dates/quotes; keep uncertain claims qualitative"); optionally add a retrieval/grounding step and a fact-check pass.
- **CQ-5 — pacing math lies [F149, F200, F201, F202] — HIGH/MED.** `clamp_durations` runs **after** the duration audit is stored, and raises each scene's estimate up to `ceil(narration_seconds)` → a repair judged "within tolerance" gets bumped back over budget; the reported audit is false and the video overshoots target. Also `brief.max_duration_seconds` is never enforced [F200], and the scene-cap merge loop discards `visual_description`/`title` and can corrupt intro/outro [F201, F202]. Fix: clamp first, then audit, then decide repair/warn; enforce the max-duration cap; preserve fields on merge.

### 3.3 Code generation (Manim / HyperFrames)

- **CQ-6 — HyperFrames has no few-shot example [F151] — HIGH.** The Manim path ships a concrete `_MANIM_FEW_SHOT` JSON example; the HF path ships rules + long prose with **zero worked example**. LLMs lean on few-shot for layout/motion taste → HF scenes converge on default "centered title + 3 bullets, power3.out fade" — the exact templated look. Fix: add 1–2 strong, distinct HF few-shot scenes (split-screen comparison, big-number stat, annotated diagram) demonstrating varied eases and the build/breathe/resolve phases; rotate the example by scene role.
- **CQ-7 — Manim few-shot teaches a forbidden animation [F153] — MED.** The `_MANIM_FEW_SHOT` example uses `there_and_back`, which the rules explicitly forbid for ending states (self-undoing). The model is being shown the thing it's told not to do. Fix: replace the example's animation with a compliant one.
- **CQ-8 — HF system prompt is long and self-contradictory [F157] — MED.** The visibility rule is stated three times; baseline guidance conflicts. Long contradictory prompts degrade adherence. Fix: deduplicate and resolve contradictions; move invariants to a short checklist.
- **CQ-9 — scene classifier biases toward text slides [F152, F175] — MED.** `classify_scene`'s keyword heuristic pushes most scenes to text-slide HyperFrames; `detect_content_type` in the validator duplicates the intent with a fragile sniff. Fix: unify into one classifier; bias toward visual/animated forms for explanatory beats.

### 3.4 Imagery

- **CQ-10 — vision image vet keeps loosely-related photos [F154, F156, F239, F238] — HIGH/MED.** `vision_select` deliberately does not sort by score and keeps anything ≥ `_VISION_KEEP_MIN=5.0` where the prompt defines 5 as "loosely related" → off-topic photos survive and can outrank relevant ones (SigLIP order wins). `_parse_score` grabs the first number anywhere in the reply (picks up stray digits) [F156]. `filter_by_relevance` returns the single best image even below threshold [F239]. SigLIP `score_image` returns 1.0 pass-through on any exception, silently defeating the filter [F238]. Fix: raise keep floor to ≥7 ("directly shows the topic"), tier by score (high ≥8 / mid 6–7) then keep SigLIP order within tier, parse only a bounded integer, and treat SigLIP exceptions as reject/unknown not pass.

### 3.5 Vision QA is silently broken

- **CQ-11 — vision inspector incompatible with Claude backend [F2, F109] — HIGH.** `_vision_inspect_manim` sends OpenAI `image_url` content blocks, but `_ClaudeCompletions._do_request` passes list content straight through and extracts text assuming a string → for a `claude-*` `IMAGE_EVAL_MODEL` the request mis-serializes and the visual check returns garbage/errors (and fails open per CQ-1/FR-10). Also temperature/response_format/`thinking` are silently dropped for Claude. Fix: add a content-block translation layer (`image_url` → Anthropic `{type:image,source:{base64}}`), or restrict `IMAGE_EVAL_MODEL` to a backend that accepts OpenAI blocks; decide `thinking` explicitly.

---

## 4. Architecture map (verified data-flow)

```
                         POST /generate (GenerationRequest)
  web-tier ──────────────────────────────────────────────────► orchestrator
  (auth, quota, budget gate, dispatch)                          (LangGraph state machine, SQLite persist)
                                                                      │  astream from START
        ┌─────────────────────────────────────────────────────────── ▼ ───────────────────────────────────────────┐
        │  script_writer ─► art_director ─► voiceover ─► image_fetcher ─► code_generator ─► validator ──► assembler │
        │      │                │             │              │                │               │(manim render/    │   │
        │   council           topic        piper/edge/     pexels/          Manim/HF LLM      HF lint) exec      │   │
        │  (analyzer,      classification   kokoro TTS    pixabay/wiki      + sanitize        per-scene          │   │
        │   budget,                          per-scene    + SigLIP +        (dead 2nd gate)   ▲                  │   │
        │   writers,                          cues        vision vet                          │ validation_router│   │
        │   reviewer)                                                                         └── retry (cap 5→6)┘   │
        └──────────────────────────────────────────────────────────────────────────────────────────────────────────┘
                                                                      │  render_paths + audio_paths (int-keyed!)
                                                          compositor ─┘  chunk ─► probe ─► concat ─► freeze-pad ─► VTT ─► finalize mp4
                                                                      │
                                            R2 upload + Neon mirror  ◄┘  (via CI scripts/runner_neon_mirror.py — MISSING, FR-3)
```

**Per-area health (from finder summaries):**

| Area | Findings (active, non-sec) | Health |
|---|---|---|
| orchestrator / graph | 11 | Control-plane logic sound in shape; **fragile** on key-typing, retry classification, resume, and untested routing. |
| compositor | 22 | Highest raw count; POSIX-only, unscaled timeouts, dedup-Future leak, brittle ffmpeg/VTT/CSS handling. |
| shared/llm_client | 15 | **Systemic** concurrency + rate-limit bugs affect every service. |
| script-writer / council | 17 | Functional but **structurally mediocre** output (no selection/coherence/grounding). |
| code-generator | 14 | Unguarded JSON parse, dead security gate, no HF few-shot, untested. |
| voiceover + validator | 18 | Missing subprocess timeouts; validator is the exec chokepoint. |
| image-fetcher | 18 | Loose relevance, no rate-limit handling, blocking calls, zero tests. |
| infra / CI | 12 | **Missing runner script**, no healthchecks, OOM-risk mem budget, `:latest`-only images. |
| cross-cutting (errors/data-flow/config/llm/tests) | ~110 | Contract mismatches and error-masking recur across every hop. |

---

## 5. Wrongly-mapped functions & contract mismatches

| ID | What's wrong | Correct wiring |
|---|---|---|
| F80 (conf via F185) | `sanitizer.check_manim_security()` is **dead code** — never called; the live gate is the weaker validator one. | Wire it in before writing generated code, or delete it; move the forbidden sets to `shared/`. |
| F185 (**confirmed**) | Duplicated, **divergent** forbidden-builtin lists in code-generator vs validator. | Single shared constant imported by both. |
| F271 | `render_mode` read as `brief.get('render_mode')` but it is **not a field of `GenerationBrief`** — injected out-of-band in one endpoint (main.py:316); `None` after resume. | Make it a first-class field of `GenerationBrief`/`LangGraphState`. |
| F22 (**confirmed**) | Budget gate sums `usage_minutes.runner_minutes`; the only writer `add_usage()` is **never called in web-tier** (cross-service write). | Document/assert which service writes it; add a dispatch-time estimated debit. |
| F222 | Config advertises a Mistral code-gen fallback that `llm_client` does not implement. | Implement or remove the advertised fallback. |
| F272 | `node_timings` written by every node but **not declared** in `LangGraphState`. | Declare it in the typed state. |
| F283 | For HyperFrames the validator returns `render_path = the HTML code_path`; orchestrator stores it in `render_paths` as if a video. | Separate HTML vs video path fields, or document the overload explicitly. |
| F278 | `AssemblerRequest.render_paths/audio_paths` typed `dict[int,str]` but int keys become str across JSON. | Same coercion contract as FR-1; validate on receipt. |
| F175 | `detect_content_type` (validator) duplicates `classify_scene` (code-gen) intent with a fragile sniff. | Unify into one shared classifier. |
| F164 | Pipeline stage `voiceover_and_images` is never emitted — dead alias + dead resume-status. | Remove the dead alias. |

---

## 6. Findings by severity (pipeline, security excluded)

### 6.1 Critical

| ID | Area | File:Line | Cat | Problem | Fix |
|---|---|---|---|---|---|
| F293 | infra | `.github/workflows/render-job.yml:80-81` | correctness | render-job invokes a runner script that does not exist in the repo | Add scripts/runner_neon_mirror.py (POST to $ORCH_URL/generate with job params read from the Neon row, poll $ORCH_URL/job/{id}, mirror status to NEON_DATABASE_URL, upload final mp4 to R2), or fix the … |
| F146 | xcut-content-quality | `services/code-generator/app/main.py:450-516, 639-721` | weak-point | No content-quality feedback loop: validator only gates renderability, never pedagogical/visual quality | Add a self-critique pass inside code-gen (or a new quality-gate node): after generation, run a cheap LLM/vision rubric scoring 1-5 on (a) does the visual match the narration, (b) information hierarch… |
| F252 | xcut-pipeline-fragility | `services/orchestrator/app/main.py:75, 128-136, 384-417` | correctness | JSON object-key coercion silently breaks resume: int scene_id keys become strings after SQLite round-trip | On every load from the DB, coerce all per-scene dict keys back to int (a single _coerce_scene_keys(state) helper applied in get_job or at run_pipeline entry), OR standardize on str keys throughout th… |

### 6.2 High

| ID | Area | File:Line | Cat | Problem | Fix |
|---|---|---|---|---|---|
| F185 | code-generator | `services/code-generator/app/sanitizer.py:18-22` | wrongly-mapped | Duplicated, DIVERGENT forbidden-builtin lists between sanitizer and validator | Move the forbidden sets into shared/ (e.g. shared/security.py) and import the SAME constants in both the (live) validator gate an… |
| F39 | compositor | `services/compositor/app/main.py:294-305, 444-466` | weak-point | Dedup Future is leaked on the waiting-caller path and bound to a possibly-wrong event loop | Wrap the whole owner body in try/finally that always pops the job_id and, if the Future is unresolved, set_exception on it. Use a… |
| F40 | compositor | `services/compositor/app/duration_prober.py:44-60` | correctness | probe_duration reads streams[0]['duration'] — wrong stream and missing-duration crash | Probe format duration: ffprobe -v error -show_entries format=duration -of json (fall back to the max of all stream durations). Th… |
| F41 | compositor | `services/compositor/app/duration_prober.py:50` | weak-point | probe_duration has no subprocess timeout — can hang the event loop / assembly forever | Add timeout=60 and convert TimeoutExpired into AssemblyError. Where probe_duration is called from async code, wrap in asyncio.to_… |
| F235 | image-fetcher | `services/image-fetcher/app/main.py:121-133` | weak-point | No response-size limit on image download — unbounded memory read of attacker-controlled body | Stream with client.stream(), abort once bytes exceed a cap (e.g. 15MB), and/or reject when Content-Length header exceeds the cap … |
| F236 | image-fetcher | `services/image-fetcher/app/relevance_llm.py:96-131` | weak-point | Vision vet does N blocking synchronous LLM calls serially inside one to_thread, with no per-ca… | Add an explicit timeout to the LLM create() call (or to get_llm_client). Consider scoring images concurrently (run_in_executor / … |
| F294 | infra | `docker-compose.yml:42-49` | weak-point | depends_on provides start-order only, not readiness — orchestrator boots before workers accept… | Add a `healthcheck` (curl -sf http://localhost:<port>/health) to each service and switch orchestrator depends_on to the long form… |
| F295 | infra | `docker-compose.ci.yml:23-56` | weak-point | CI mem_limit budget exceeds the 7 GB runner; OOM risk despite the per-service caps comment | Cut the total to leave ~1.5–2 GB for host+runner: e.g. validator 2.5g, compositor 1g, voiceover 768m. Or scale the pipeline so he… |
| F203 | script-writer | `services/script-writer/app/council.py:111-121` | weak-point | No per-call timeout on any LLM call; a hung request stalls the whole job | Wrap each LLM call in asyncio.wait_for with an explicit budget, or pass a per-call timeout to the client. Add bounded retry with … |
| F219 | shared | `shared/llm_client.py:153-164` | weak-point | Async rate limiter serializes all concurrent LLM calls by sleeping while holding the lock | Compute the next-allowed start time under the lock, update `_async_last_request_time` to that scheduled time, release the lock, T… |
| F220 | shared | `shared/llm_client.py:112-122` | correctness | Concurrency semaphore is never re-created across event loops despite docstring claiming it is | Track the loop the semaphore was bound to and re-create on mismatch: store `(loop, sem)` and recreate when `asyncio.get_running_l… |
| F221 | shared | `shared/llm_client.py:125-134, 311-315` | weak-point | Sync rate limiter (time.sleep) is invoked from inside an async event-loop handler, blocking it | Either make `extract_keywords` use `acreate` (await client.chat.completions.acreate(...)), or wrap the sync call in `await asynci… |
| F2 | voiceover | `services/validator/app/main.py:260-278` | correctness | Vision inspector sends list-shaped message content that the Claude backend cannot serialize | Either restrict IMAGE_EVAL_MODEL to a backend that accepts OpenAI image_url blocks, or add a content-block translation layer in _… |
| F5 | voiceover | `services/voiceover/app/main.py:31-41, 234, 281-285` | weak-point | Multiple subprocess calls have no timeout — can block the asyncio thread pool indefinitely | Add explicit timeout= to every subprocess.run in voiceover (e.g. timeout=30 for ffprobe, a bounded timeout for piper) and handle … |
| F18 | voiceover | `services/validator/app/main.py:n/a` | test-gap | Test gap: no tests cover the AST security gate bypasses, the provider fallback chain, or the c… | Add unit tests: (1) a battery of malicious sources (import builtins, getattr-based imports, dunder traversal, relative imports) a… |
| F22 | web-tier | `services/web-tier/app/db.py:223-239` | correctness | Monthly budget gate reads usage_minutes that the web tier never writes | Confirm and document the contract: which service writes usage_minutes and when (job completion?). Add an integration test or a st… |
| F60 | xcut-config-timeouts | `shared/config.py:9, 28, 152` | weak-point | Required secrets default to empty and are never validated at startup (fail-late deep in a requ… | Add a model_validator (or per-service startup check in each FastAPI @app.on_event('startup')) that asserts the keys that service … |
| F61 | xcut-config-timeouts | `docker-compose.yml:212-214` | correctness | docker-compose COMPOSITOR_CHUNK_* defaults disagree with shared/config.py defaults | Pick one source of truth. Either drop these env lines from compose so the code defaults win, or update config.py defaults to matc… |
| F62 | xcut-config-timeouts | `docker-compose.yml:140` | correctness | VOICEOVER_FALLBACK_PROVIDER default differs between code (piper) and compose (edge_tts) | Change the compose default to piper to match the stated offline-first design, or update the config.py comment/default if edge_tts… |
| F65 | xcut-config-timeouts | `docker-compose.yml:88-105` | weak-point | code-generator service never receives NVIDIA timeout overrides; a hung NIM read can stall a si… | Pass NVIDIA_READ_TIMEOUT_SECONDS (and total/connect) into the code-generator service env with a value sized for 16k-token reasoni… |
| F147 | xcut-content-quality | `services/script-writer/app/council.py:281-316` | weak-point | Script council merges parallel section writers with no best-of/selection — averages to mediocr… | Either (a) generate 2-3 candidate scripts and have the reviewer pick the best (true council), or (b) give each section writer the… |
| F148 | xcut-content-quality | `services/script-writer/app/council.py:320-355` | weak-point | Reviewer critiques a 200-char-truncated narration summary, so it cannot judge real narration q… | Send full narration_text and visual_description for each scene (the model context can hold it; scripts are small). Have the revie… |
| F149 | xcut-content-quality | `services/script-writer/app/council.py:430-441` | correctness | clamp_durations runs AFTER the duration audit is stored, so the reported audit can lie and pac… | Audit AFTER clamping (clamp first, then audit, then decide repair/warn). Re-check within_tolerance on the post-clamp audit and ap… |
| F151 | xcut-content-quality | `services/code-generator/app/main.py:293-393, 549-621` | improvement | HyperFrames generation has NO few-shot example while Manim does — HF output is more generic/te… | Add 1-2 strong, distinct HyperFrames few-shot scenes (different layouts: split-screen comparison, big-number stat, annotated diag… |
| F154 | xcut-content-quality | `services/image-fetcher/app/relevance_llm.py:33-39, 140-155` | weak-point | Vision image vet keeps SigLIP order and never sorts by score; keep-floor 5.0 lets 'loosely rel… | Raise the keep floor (e.g. >=7 'directly shows the topic') and use the score as a coarse tier: bucket into high(>=8)/mid(6-7), pr… |
| F158 | xcut-content-quality | `services/script-writer/app/council.py:194-278` | correctness | No grounding of facts: writers/planner are never given source material and never told to avoid… | Add an accuracy directive ('prefer well-established facts; do not invent specific statistics, dates, or quotes; keep claims you a… |
| F271 | xcut-data-flow | `services/orchestrator/app/core/graph.py:104, 186` | wrongly-mapped | render_mode read from brief but stored at top level of brief — code-generator always gets None… | Make render_mode a first-class field of GenerationBrief (or of LangGraphState) so it is part of the validated contract and surviv… |
| F273 | xcut-data-flow | `services/orchestrator/app/main.py:575-583` | correctness | get_scene_video looks up int-keyed render_paths with a str path param — always 404 | Type the param as `scene_id: int` (FastAPI will coerce/validate) or do `(state.get('render_paths') or {}).get(int(scene_id))` wit… |
| F275 | xcut-data-flow | `services/orchestrator/app/main.py:402-417` | weak-point | resume_job re-enters at 'validation' — never re-runs script/art/voiceover/image gates, so a jo… | Don't fake status='validation'; let the graph's resume-safe skips drive it and set a neutral 'resuming' status. Preserve previous… |
| F165 | xcut-dead-and-overeng | `services/compositor/app/main.py:139, 146-148` | weak-point | `preexec_fn=os.setsid` / `os.killpg` is Linux-only — breaks on the documented win32 host | Guard with `if hasattr(os, 'setsid')` / `sys.platform != 'win32'`, falling back to `subprocess.Popen(..., creationflags=CREATE_NE… |
| F305 | xcut-errors | `shared/llm_client.py:112-122` | correctness | Per-loop semaphore is never recreated despite its own comment promising it | Track the loop the semaphore was created on and recreate when it differs: store `(_sem, _sem_loop)`; `if _sem is None or _sem_loo… |
| F306 | xcut-errors | `shared/llm_client.py:149-164` | weak-point | Async rate-limiter globals (_async_rate_lock, _async_last_request_time) leak across event loops | Bind the lock to the running loop the same way as the semaphore fix (recreate on loop change), or hang both the semaphore and the… |
| F312 | xcut-errors | `services/orchestrator/app/core/graph.py:305-310, 116, 205, 433` | correctness | Orchestrator accesses res['error_log'] / res['render_path'] / res['image_paths'] without guard… | Use res.get('render_path'), res.get('error_log') etc., and treat a missing required field as an explicit contract violation with … |
| F107 | xcut-llm-usage | `shared/llm_client.py:112-122` | weak-point | Async semaphore is cached across event loops despite a comment claiming it is recreated | Key the cached semaphore/lock by the running loop (e.g. a dict keyed on id(loop) or weakref to the loop), or create per-call and … |
| F108 | xcut-llm-usage | `shared/llm_client.py:149-164` | weak-point | Global async rate lock + single _async_last_request_time serializes ALL async LLM calls proces… | Compute the wake time under the lock, release the lock, then sleep: capture `slot = max(now, _async_last_request_time + interval)… |
| F109 | xcut-llm-usage | `shared/llm_client.py:367-393` | correctness | Claude backend never sends adaptive thinking and silently drops temperature/response_format de… | Either pass thinking={'type':'adaptive'} for quality on agentic/code tasks, or document that thinking-off is intentional. Fix the… |
| F110 | xcut-llm-usage | `services/code-generator/app/main.py:674-675` | weak-point | Manim JSON parse is unguarded — json.loads on possibly-None/malformed content can crash the re… | Guard content: `content = response.choices[0].message.content; if not content: raise/continue`. Wrap json.loads in try/except (Ty… |
| F253 | xcut-pipeline-fragility | `services/orchestrator/app/main.py:575-583` | correctness | get_scene_video looks up int-keyed render_paths with a string path param — always 404 | Declare scene_id: int in the route signature (FastAPI will coerce+validate), or do `.get(int(scene_id))` with a try/except -> 422… |
| F254 | xcut-pipeline-fragility | `services/validator/app/main.py:24-37, 109-110, 719-726` | weak-point | Manim render subprocess has no orchestrator-side cap distinct from per-request HTTP timeout; a… | Mirror the compositor's process-group kill in _run_manim_subprocess: Popen(preexec_fn=os.setsid), on timeout os.killpg(os.getpgid… |
| F255 | xcut-pipeline-fragility | `shared/llm_client.py:292-309, 395, 467-471` | correctness | LLM client can return None / empty content that flows unvalidated into downstream parsing | In both _do_request paths, raise a typed error when content is falsy, when stop_reason/finish_reason is 'refusal'/'content_filter… |
| F256 | xcut-pipeline-fragility | `services/orchestrator/app/core/graph.py:32-36, 117-119, 311-313, 356, 392-411` | weak-point | A single service returning 502/503 (or being down) burns all 5 retries per scene with no servi… | Classify exceptions in _post: ConnectError/ReadTimeout/5xx are infra-transient and should NOT consume the per-scene LLM-quality r… |
| F80 | xcut-security | `services/code-generator/app/sanitizer.py:25-68` | dead-code | check_manim_security() is dead code — the stronger security gate is never wired into the gener… | Either wire check_manim_security into _generate_manim BEFORE writing the file (reject the candidate and feed violations back as t… |
| F128 | xcut-tests | `services/orchestrator/app/main.py:575-583 (with services/orchestrator/app/db.py:24-35)` | correctness | GET /video/{job_id}/scene/{scene_id} always 404s — int-vs-str key mismatch with revived render… | Declare `scene_id: int` in the path signature (FastAPI will coerce/validate), or coerce locally: `path = (state.get('render_paths… |
| F130 | xcut-tests | `services/orchestrator/app/core/graph.py:377-411` | test-gap | validation_router and the retry/routing logic have no tests despite being the pipeline's contr… | Add unit tests for validation_router covering: all rendered -> assembler; some unrendered with retries left -> code_generator; so… |

### 6.3 Medium

| ID | Area | File:Line | Cat | Problem | Fix |
|---|---|---|---|---|---|
| F196 | code-generator | `services/code-generator/app/main.py:674-675` | weak-point | json.loads on Manim LLM response is unguarded; malformed JSON raises and aborts retries e… | Wrap json.loads in try/except inside the loop; on failure, treat like a parse error (feed back as error_log a… |
| F198 | code-generator | `services/code-generator/app/sanitizer.py:71-283` | test-gap | No tests for the sanitizer despite it gating executed code | Add a dedicated test module for sanitizer.py: assert each name/color/rate_func rewrite, assert background ass… |
| F38 | compositor | `services/compositor/app/main.py:134-153` | weak-point | preexec_fn=os.setsid breaks on Windows; whole render path is POSIX-only | Guard the process-group logic behind os.name == 'posix'. On Windows use creationflags=subprocess.CREATE_NEW_P… |
| F42 | compositor | `services/compositor/app/main.py:284-289` | correctness | Concat duration drift check re-probes the same paths used to build the film (tautological… | Compare actual film duration against the intended timeline length sum(slot_seconds(t) for t in active) (the v… |
| F43 | compositor | `services/compositor/app/llm_composer.py:57-59` | correctness | audio_segments key-type contract: orchestrator sends int keys, build_vtt only also tries … | Normalize once: build {int(k): v for k,v in (audio_segments or {}).items()} at entry, and add a test that pos… |
| F44 | compositor | `services/compositor/app/main.py:193-202` | weak-point | _has_audio_stream defaults to True on any error, hiding silent-chunk problems and produci… | On probe failure, treat the result as unknown and force normalization (synthesize silent audio) rather than a… |
| F45 | compositor | `services/compositor/app/llm_composer.py:146-169` | correctness | allocate_caption_windows final-chunk duration can go negative, silently dropping the last… | Clamp the final window to at least a small floor (e.g. max(dur, 0.001)) and/or compute the final dur as end_l… |
| F46 | compositor | `services/compositor/app/main.py:269-279` | weak-point | ffmpeg concat list uses unescaped single-quoted filenames; relative-name + cwd coupling i… | Escape single quotes per ffmpeg concat rules (replace ' with '\'') or write absolute paths and drop the cwd d… |
| F47 | compositor | `services/compositor/app/main.py:278` | weak-point | Concat timeout is a hardcoded 600s magic number, unscaled by film length | Scale like postprocess._timeout_for(total) (or reuse it) so the concat budget grows with the composed length,… |
| F48 | compositor | `services/compositor/app/duration_prober.py:193-218` | correctness | freeze_pad_renders forces -r 30 and re-encodes, but never verifies/re-probes the padded o… | Re-probe `out` and store the measured duration; or pad to stop_duration computed to land on the next frame bo… |
| F59 | compositor | `services/compositor/app/main.py:232-289, 386-423` | test-gap | No test covers the fault-tolerant HF-drop bisect, _normalize_audio_streams, or real ffmpe… | Add tests that simulate AssemblyError on the first _render_active call and assert exactly the bad scene(s) ar… |
| F237 | image-fetcher | `services/image-fetcher/app/pexels_client.py:63-68` | weak-point | Pexels/Pixabay/Wikimedia clients have no rate-limit (429) handling or backoff | Special-case 429 (and 503): read Retry-After, apply bounded exponential backoff with a small retry budget, an… |
| F238 | image-fetcher | `services/image-fetcher/app/siglip_scorer.py:162-164` | correctness | SigLIP score_image returns 1.0 (pass-through) on ANY exception, silently defeating the re… | On per-image scoring failure return a neutral-low or sentinel (e.g. 0.0 or skip the image entirely), not the … |
| F239 | image-fetcher | `services/image-fetcher/app/siglip_scorer.py:190-198` | correctness | filter_by_relevance always returns the single best image even when it is below threshold … | Recalibrate the threshold to the actual sigmoid output range of this SigLIP export (measure real positives vs… |
| F240 | image-fetcher | `services/image-fetcher/app/main.py:197-203` | weak-point | Candidate count is unbounded — every pooled URL is downloaded before any ranking trims th… | Cap candidates per scene (e.g. slice candidates to first N before downloading) and/or download concurrently w… |
| F248 | image-fetcher | `services/image-fetcher/app/main.py:161, 244` | weak-point | set_log_context(scene_id=...) called inside parallel coroutines mutates shared/contextvar… | Verify set_log_context uses contextvars bound per-task (asyncio.gather tasks each get a copied context, which… |
| F249 | image-fetcher | `services/image-fetcher/app/keyword_extractor.py:58-93` | weak-point | No timeout/observability on the keyword-extraction LLM call; synchronous create() blocks … | Wrap extract_keywords in asyncio.to_thread (as is already done for filter_by_relevance and vision_select), an… |
| F250 | image-fetcher | `services/image-fetcher/app/keyword_extractor.py:74` | test-gap | Zero tests for the entire image-fetcher service despite docstrings claiming property-base… | Add unit tests: validate_image_magic_bytes (boundary <4 bytes, JPEG/PNG/garbage), _parse_keywords_json (markd… |
| F296 | infra | `infrastructure/docker/Dockerfile.compositor:45-52` | weak-point | Chrome-headless-shell download URL resolved via live LLM-free JSON fetch at build, no pin… | Pin a specific chrome-for-testing version (matching the Chromium apt version), record its sha256, verify afte… |
| F299 | infra | `.github/workflows/build-images.yml:42-59` | weak-point | build-images pushes only :latest with no immutable tag; render-job pulls IMAGE_TAG=latest… | Tag and push both :${{ github.sha }} and :latest for base and every service, and have render-job dispatch car… |
| F304 | infra | `.github/workflows/render-job.yml:53-57` | test-gap | No test coverage for CI compose override correctness or the render workflow driver | Add a lightweight CI job that runs `docker compose -f docker-compose.yml -f docker-compose.ci.yml config` (wi… |
| F92 | orchestrator | `services/orchestrator/app/main.py:575-583` | correctness | Per-scene video endpoint uses str scene_id against int-keyed render_paths -> always 404 | Coerce the key: `path = (state.get('render_paths') or {}).get(int(scene_id))` (wrap in try/except -> 400 on n… |
| F95 | orchestrator | `services/orchestrator/app/core/graph.py:232, 329, 392` | improvement | Retry cap (5) is a magic number duplicated in three places and can drift | Hoist to settings.MAX_SCENE_RETRIES (or a module constant) and reference it in all three sites so they cannot… |
| F104 | orchestrator | `services/orchestrator/app/core/graph.py:377-411` | test-gap | No tests referenced for validation_router routing, retry exhaustion, scene-key int/str re… | Add table-driven tests for validation_router over synthetic states, a round-trip test asserting int keys surv… |
| F200 | script-writer | `services/script-writer/app/council.py:409-412` | correctness | brief.max_duration_seconds is never enforced — target can exceed the analyzer cap | At the top of generate_script, clamp target to the brief's max: `mx = (brief or {}).get('max_duration_seconds… |
| F201 | script-writer | `services/script-writer/app/council.py:172-175` | correctness | Scene-cap merge loop discards visual_description and title of merged scenes | Merge visual_description too (e.g. `a['visual_description'] = f"{a['visual_description']} Then: {b['visual_de… |
| F202 | script-writer | `services/script-writer/app/council.py:169-171` | weak-point | del cleaned[-2] in merge fallback can corrupt or empty intro/outro structure | When no same-type neighbor exists, still merge the globally-shortest adjacent pair (concatenating narration a… |
| F222 | shared | `shared/config.py:16-22` | wrongly-mapped | Config advertises a Mistral code-gen fallback that llm_client does not implement | Move the Mistral fallback into `_RoutingCompletions` / `_NimCompletions` (a third routed backend or an in-`_N… |
| F223 | shared | `shared/log.py:34-49` | correctness | Logging contextvars leak across concurrently-gathered scene tasks | Use `contextvars.copy_context()` per gathered task, or pass an explicit sentinel to allow clearing (e.g. acce… |
| F224 | shared | `shared/llm_client.py:227-242` | weak-point | Single-key 429 backoff can sleep up to 120s on the event-loop thread pool indefinitely wi… | Guard `float(retry_after)` in try/except (Retry-After may be an HTTP-date, not seconds). Add jitter (`wait *=… |
| F3 | voiceover | `services/validator/app/main.py:707-748` | correctness | Error message and code comment claim 1080p60 but validator renders at -qh = 1080p30 | Fix the error string to say 1080p30 (or change the flag to -qp/-p 1080p60 and the reencode to -r 60 if 60fps … |
| F4 | voiceover | `services/voiceover/app/main.py:191-211` | weak-point | edge-tts and piper segment timing double-cleans text, risking sentence-count divergence f… | Pass the already-cleaned `clean` string to _proportional_segments (and have it skip re-cleaning), so the sent… |
| F6 | voiceover | `services/voiceover/app/main.py:197-203` | weak-point | asyncio.run inside generate_edge_tts assumes no running loop, but the docstring's assumpt… | Wrap the save in asyncio.wait_for with a timeout inside _run, and either rename/document the function as thre… |
| F12 | voiceover | `services/voiceover/app/main.py:133-164` | correctness | Kokoro cue timing adds a 150ms inter-sentence gap to durations but the written audio drop… | Build the file and the cue timeline from the same source of truth: compute each segment's start from the actu… |
| F14 | voiceover | `services/validator/app/main.py:603-628, 230-297` | improvement | _lint_hyperframes_remote and _vision_inspect_manim fail open by default, silently disabli… | Emit an explicit observability signal (counter/log field gate_skipped=true with reason) whenever a gate fails… |
| F21 | web-tier | `services/web-tier/app/main.py:128-139` | weak-point | Concurrency, quota and budget gates are check-then-act races | Perform the count and the insert in one SERIALIZABLE/repeatable-read transaction, or use an atomic INSERT ...… |
| F24 | web-tier | `services/web-tier/app/db.py:79-89` | weak-point | get_or_create_user has a TOCTOU insert race on first login | Use an upsert (INSERT ... ON CONFLICT (clerk_id) DO NOTHING then SELECT) on Postgres, or catch IntegrityError… |
| F26 | web-tier | `services/web-tier/app/main.py:168-185` | weak-point | Synchronous (blocking) httpx calls inside async-served endpoints | Either make these endpoints async with httpx.AsyncClient, or keep them sync but set explicit connect/read tim… |
| F63 | xcut-config-timeouts | `docker-compose.yml:177` | correctness | IMAGE_EVAL_MODEL compose default contradicts the 'empty -> skip vision vet' contract | Reconcile to a single documented model id. Update the config.py comment to the actually-deployed model and ke… |
| F64 | xcut-config-timeouts | `shared/config.py:11-13` | weak-point | NVIDIA total timeout (300s) and read timeout (180s) are inconsistent; read dominates | Make read >= total or set read to None (use total) for the code-generator path, or raise NVIDIA_READ_TIMEOUT_… |
| F66 | xcut-config-timeouts | `services/validator/app/main.py:30-37` | weak-point | manim and ffmpeg subprocesses have time limits but no memory/CPU resource limits | Add preexec_fn=resource.setrlimit(RLIMIT_AS, ...) on Linux to cap render RAM, and/or set mem_limit/cpus on th… |
| F67 | xcut-config-timeouts | `services/validator/app/main.py:34-37` | weak-point | subprocess.Popen kill on timeout leaks grandchild processes (no process group) | Start the child in its own process group (start_new_session=True / preexec_fn=os.setsid) and on timeout kill … |
| F68 | xcut-config-timeouts | `services/orchestrator/app/core/graph.py:32-36` | weak-point | Orchestrator->validator HTTP fan-out uses fixed 900s timeout that ignores validator-side … | Either make the validator render budget + max queue depth strictly less than the caller's HTTP timeout with m… |
| F70 | xcut-config-timeouts | `shared/config.py:83` | correctness | Orchestrator wallclock cap (360 min) can exceed the GitHub Actions workflow cap (~350 min… | Set JOB_TIMEOUT_MAX_SECONDS below the real Actions ceiling (e.g. <=20400s/340min) so the orchestrator aborts … |
| F71 | xcut-config-timeouts | `shared/timeouts.py:49-58` | weak-point | assembler_http_timeout caps at 14400s but compositor's own chunk render budget can exceed… | Make the assembler HTTP timeout >= sum of worst-case chunk budgets + concat/normalize overhead, using the SAM… |
| F77 | xcut-config-timeouts | `services/orchestrator/app/main.py:228-231` | weak-point | No timeout on the orchestrator's astream loop per-node; only a single outer wallclock wra… | Wrap each node (or at least the long blocking ones — codegen fan-out, validation, assembly) in its own asynci… |
| F150 | xcut-content-quality | `services/script-writer/app/council.py:382-405` | dead-code | repair_budgets emits word_budget that the repair prompt references but never passes to th… | Pick one currency. Pass per-scene `{scene_id, target_words}` only, instruct 'rewrite narration_text to ~targe… |
| F152 | xcut-content-quality | `services/code-generator/app/main.py:118-128` | weak-point | classify_scene keyword heuristic biases the whole video toward text-slide HyperFrames | Trust script-writer's content_type as primary (it has full context) and only fall back to classification when… |
| F153 | xcut-content-quality | `services/code-generator/app/main.py:564-566` | correctness | Manim few-shot teaches a self-undoing animation (there_and_back) the rules explicitly for… | Change the few-shot to a one-way ease that lands (e.g. rate_functions.ease_in_out_sine) and hold with self.wa… |
| F155 | xcut-content-quality | `services/image-fetcher/app/relevance_llm.py:96-131` | weak-point | Vision image vet uses blocking synchronous LLM calls in an N-image loop with no timeout/c… | Use the async client (acreate) with asyncio.gather + a Semaphore to score images concurrently, add a per-call… |
| F156 | xcut-content-quality | `services/image-fetcher/app/relevance_llm.py:50-55, 103-126` | weak-point | Per-image vision prompt is a weak rubric: single integer, no rejection examples, parses f… | Constrain output (response_format/JSON or 'score: N' and parse the labeled value), drop max_tokens to ~10, an… |
| F157 | xcut-content-quality | `services/code-generator/app/main.py:136-183` | improvement | HF system prompt is extremely long and partly contradictory (visibility rule stated 3 tim… | Single-source each rule: keep mechanical rules only in hf_rules.md, keep the system 'Your Task' block to <=10… |
| F159 | xcut-content-quality | `services/code-generator/app/main.py:206-220, 239-256` | weak-point | _inline_images silently blanks invented/mismatched __IMAGE_k__ tokens — scenes lose requi… | After inlining, verify each provided image index was referenced; if a required image (index 0) is missing, lo… |
| F272 | xcut-data-flow | `shared/models/agent_state.py:4-44` | correctness | node_timings written by every graph node but not declared in LangGraphState | Add `node_timings: List[dict]` to LangGraphState for contract clarity, and either cap its length or drop it f… |
| F274 | xcut-data-flow | `services/orchestrator/app/core/graph.py:59-61` | correctness | script_writer_node resume-skip drops script_meta, so art_director loses topic_classificat… | On the resume-skip, echo the existing meta and a span: return {"status": "script_generation", "script_meta": … |
| F277 | xcut-data-flow | `services/voiceover/app/main.py:28 (VoiceoverResponse.segments), code-generator/app/main.py:259-290` | weak-point | voiceover segments come from the service unvalidated and are trusted as dicts with start/… | Define a typed AudioSegment Pydantic model ({text:str,start:float,duration:float}) in shared/schemas and use … |
| F278 | xcut-data-flow | `services/orchestrator/app/core/graph.py:500-509` | correctness | AssemblerRequest.render_paths/audio_paths typed dict[int,str] but orchestrator sends int-… | Standardize on a single key-coercion boundary: rely on Pydantic int-key coercion at the AssemblerRequest/Imag… |
| F280 | xcut-data-flow | `services/orchestrator/app/core/graph.py:32-36, 114` | weak-point | _post has no retry and a single shared timeout for wildly different operations; LLM code-… | Pass explicit per-stage timeouts to _post for code-gen and validation that are >= the downstream service's ow… |
| F283 | xcut-data-flow | `services/validator/app/main.py:391-392, 658-663` | wrongly-mapped | validator returns render_path for HyperFrames = the HTML code_path; orchestrator stores i… | Carry content_type alongside the path (e.g. render_paths value becomes {path, kind} or a parallel render_kind… |
| F286 | xcut-data-flow | `services/code-generator/app/main.py:417-447` | weak-point | _unhide_css regex-based CSS rewriting is brittle and can corrupt valid CSS / miss inline … | Replace regex CSS surgery with a real parser pass, or — given the compositor already runs hyperframes lint — … |
| F288 | xcut-data-flow | `services/compositor/app/main.py:292-305` | weak-point | compositor /assemble dedup Future keyed by job_id never times out; a hung first assembly … | Wrap the await in asyncio.wait_for with a bound, and resolve/pop the future in a finally block (or use a task… |
| F292 | xcut-data-flow | `shared/schemas/requests.py:n/a` | test-gap | No test coverage for the cross-service contract layer (schemas, key revival, validation_r… | Add unit tests for: (1) db round-trip preserving int scene keys, (2) validation_router reaching 'assembler_no… |
| F164 | xcut-dead-and-overeng | `services/orchestrator/app/main.py:141-154, 391-393` | dead-code | Pipeline stage `voiceover_and_images` is never emitted — dead alias + dead resume-status | Remove `voiceover_and_images` from `_STAGE_ORDER` and from the resume whitelist (line 392). Keep a single can… |
| F169 | xcut-dead-and-overeng | `services/orchestrator/app/main.py:222-225, 345-359` | weak-point | Cancel/resume race: `_CANCEL` membership is consumed by the streaming loop, but a cancel … | Cancel can't interrupt an in-flight node anyway — document that explicitly, and/or actually cancel the asynci… |
| F170 | xcut-dead-and-overeng | `services/validator/app/main.py:289-297` | correctness | Vision-inspect majority vote is wrong when fewer than 3 frames sampled | Make it a true majority: `if verdicts and len(bad) > len(verdicts)/2`. Report all distinct bad labels, not `b… |
| F172 | xcut-dead-and-overeng | `services/orchestrator/app/main.py:497-513` | weak-point | VTT timestamp parser is brittle and silently mis-shifts on unexpected formats | Since the compositor already builds the VTT (build_vtt), pass `intro_offset` INTO build_vtt at assembly time … |
| F175 | xcut-dead-and-overeng | `services/validator/app/main.py:300-325` | wrongly-mapped | `detect_content_type` (validator) duplicates `classify_scene` intent and is a fragile con… | Add `content_type` to ValidatorRequest (the orchestrator/graph already knows it per scene) and route on that;… |
| F181 | xcut-dead-and-overeng | `services/code-generator/app/main.py:206-236, 363-366` | correctness | `_strip_data_uris` numbering is per-call and not aligned with `_inline_images` indexing o… | Map each stripped data-URI back to its original index by matching against the inlined `image_paths` (build ur… |
| F183 | xcut-dead-and-overeng | `services/compositor/app/main.py:386-423` | test-gap | No test coverage for the critical fail-soft drop/bisect logic and the resume race guards | Add unit tests with `_render_active` stubbed to fail on a designated scene id: assert (a) one bad HF scene → … |
| F307 | xcut-errors | `shared/llm_client.py:210-280` | correctness | 429 retry path retries even after exhausting attempts only by chance; 5xx/timeout/request… | Use a single consistent attempt budget (max_attempts) for all retryable classes. Parse retry-after defensivel… |
| F308 | xcut-errors | `shared/llm_client.py:235-240` | weak-point | Blocking time.sleep inside _do_request runs on a thread-pool worker but can pile up unbou… | Move backoff sleeps outside the semaphore-held region, or convert the retry loop to async (await asyncio.slee… |
| F313 | xcut-errors | `services/orchestrator/app/core/graph.py:229-233, 273, 356, 392` | correctness | Retry cap mismatch: code_generator_node and validation_router use <5, but on a code-gen f… | Define MAX_SCENE_RETRIES once in config and reference it in all three places. Decide a single semantic for 'a… |
| F314 | xcut-errors | `services/orchestrator/app/core/graph.py:262-267` | weak-point | code_generator_node silently swallows file-read errors when caching previous_code, leavin… | Log the read failure (logger.warning with scene_id and path) and explicitly drop the stale entry: new_previou… |
| F315 | xcut-errors | `services/orchestrator/app/core/graph.py:381-411, 327, 359, 504-519` | correctness | validation_router and several nodes dereference state['script']['scenes'] / state['code_p… | In validation_router, return 'failed' if script is falsy. In nodes, read with .get and validate presence with… |
| F318 | xcut-errors | `services/compositor/app/main.py:134-153` | weak-point | Compositor: subprocess setsid/killpg/preexec_fn is POSIX-only — code runs on Windows dev … | Guard the process-group logic behind `if os.name == 'posix'` and fall back to proc.kill()/CREATE_NEW_PROCESS_… |
| F319 | xcut-errors | `services/compositor/app/main.py:193-202` | weak-point | _has_audio_stream returns True on ANY exception, masking ffprobe failures and corrupting … | Distinguish 'ffprobe failed' from 'no audio stream'. On probe failure, either re-run with a longer timeout, o… |
| F321 | xcut-errors | `services/compositor/app/main.py:294-466` | weak-point | Compositor /assemble future cleanup leaks the in-flight entry if the coroutine is cancell… | Wrap the body in try/finally that always pops _ASSEMBLING[job_id] and, if the future is unresolved, sets a Ca… |
| F325 | xcut-errors | `services/validator/app/main.py:671-673, 802-804` | correctness | Validator _validate_hyperframes/_validate_manim re-raise on unexpected exception, returni… | Classify validator-internal errors (infra) separately from render/lint failures (bad code). For infra errors,… |
| F333 | xcut-errors | `shared/llm_client.py:n/a` | test-gap | Test gap: no tests for the LLM client retry/backoff, semaphore-per-loop, or routing-by-mo… | Add unit tests with a mocked httpx that assert: 429 retries across keys, retry-after date parsing, max_attemp… |
| F111 | xcut-llm-usage | `services/code-generator/app/main.py:67-112` | weak-point | Circuit-breaker check-and-set on _nim_down_until is not atomic across concurrent code-gen… | This is single-process shared state mutated from many coroutines; guard reads/writes with an asyncio.Lock or … |
| F112 | xcut-llm-usage | `services/code-generator/app/main.py:71-90` | weak-point | Mistral fallback path bypasses all rate limiting, key pooling, and retry logic | Route Mistral through the same client abstraction (add a third backend to _RoutingCompletions keyed on model … |
| F113 | xcut-llm-usage | `shared/llm_client.py:210-278` | weak-point | max_attempts for 429 scales with key count but 502/503/504 and timeout/connect retries ar… | Use a single, named retry budget for transient errors (e.g. TRANSIENT_MAX_ATTEMPTS) and apply it consistently… |
| F114 | xcut-llm-usage | `services/image-fetcher/app/relevance_llm.py:93-126` | weak-point | Sync vision client builds a new NimClient per call and uses the blocking sync path with a… | Build the client once at module load. Cap max_tokens to ~16 (only an integer is parsed). If this runs inside … |
| F115 | xcut-llm-usage | `services/image-fetcher/app/relevance_llm.py:50-55` | weak-point | _parse_score extracts the first number anywhere in the reply — picks up stray digits from… | Prefer the LAST number, or anchor to a labeled pattern, or take the max of all matched 0-10 numbers. Better: … |
| F116 | xcut-llm-usage | `shared/llm_client.py:381-384` | weak-point | JSON-mode requested everywhere but the actual JSON contract is unenforced for NIM and Cla… | Add a tolerant JSON extractor in _call_json (strip ```json fences, then regex the outermost {...}) before jso… |
| F117 | xcut-llm-usage | `shared/llm_client.py:395-417` | correctness | Claude refusal handling logs a warning but returns empty content downstream as a normal r… | On refusal, either raise a typed RefusalError that callers can catch distinctly, or include stop_details so t… |
| F118 | xcut-llm-usage | `shared/llm_client.py:370, 441-442` | improvement | Model IDs and sampling params are scattered across many env settings with no central regi… | Introduce a small model-registry (id -> {provider, supports_temperature, supports_json_mode, max_output}) and… |
| F120 | xcut-llm-usage | `shared/llm_client.py:76, 150` | correctness | Sync rate limiter and async rate limiter track separate last-request timestamps — combine… | Share one pacing clock between the sync and async limiters (a single monotonic timestamp guarded by a lock th… |
| F257 | xcut-pipeline-fragility | `services/compositor/app/main.py:193-229, 285` | weak-point | Compositor _normalize_audio_streams, _has_audio_stream, concat, finalize_film run blockin… | Wrap _normalize_audio_streams and the probe_duration sanity-check sum in asyncio.to_thread (the concat itself… |
| F258 | xcut-pipeline-fragility | `services/orchestrator/app/main.py:228-231, 260-270` | weak-point | Wall-clock TimeoutError persists 'failed' but re-raises into BackgroundTasks where nothin… | On wall-clock timeout, also POST a /cancel to the validator/compositor for the job (or include job_id in a ca… |
| F259 | xcut-pipeline-fragility | `services/validator/app/main.py:97-110` | weak-point | _compute_timeout counts ALL .play attribute calls including unrelated objects, mis-budget… | Restrict to self.play (check n.func.value is ast.Name with id=='self'), and additionally weight by run_time= … |
| F260 | xcut-pipeline-fragility | `services/validator/app/main.py:235-237, 289-297, 623-628` | weak-point | Vision-inspect and HF-lint failures fail-open, producing broken-but-'successful' videos | Make QA failures fail-CLOSED for the high-signal checks (vision says broken, lint says error) and only fail-o… |
| F267 | xcut-pipeline-fragility | `services/orchestrator/app/main.py:28-32, 116-120, 331, 389-399` | weak-point | _DRIVING / _CANCEL in-process sets defeat resume idempotency across multiple orchestrator… | Move the driving-lock and cancel-flag to the shared DB (a 'driver_owner'/'cancel_requested' column with a cla… |
| F270 | xcut-pipeline-fragility | `services/orchestrator/app/core/graph.py:377-411` | test-gap | No test coverage for the resume/JSON-key round-trip, validation_router degradation branch… | Add unit tests: (1) round-trip a mid-flight state dict through json.dumps/loads and assert validation_router … |
| F81 | xcut-security | `services/code-generator/app/sanitizer.py:228-246` | correctness | Sanitizer drops keyword args it doesn't recognize as rate_func, silently mutating generat… | Only drop a bare-Name rate_func if it is provably undefined in the module (no matching FunctionDef/assignment… |
| F84 | xcut-security | `services/code-generator/app/sanitizer.py:257-268` | correctness | Background-color injection assumes config/WHITE are imported — NameError on valid code th… | Before injecting, verify `from manim import *` is present (or config/WHITE are otherwise importable); if not,… |
| F90 | xcut-security | `services/validator/app/main.py:44-51, 534-540` | test-gap | Validator self-test covers only deprecated names, not the security branch of the gate | Add security cases to the startup self-test: assert _preflight_ast_checks rejects sources with `import os`, `… |
| F129 | xcut-tests | `services/orchestrator/app/core/graph.py:232-233, 328-330, 392, 273, 356` | correctness | Retry cap is off-by-one: scenes get 6 code-gen/validate attempts, not the documented 5 | Decide the intended attempt budget and make the constant explicit (e.g. MAX_SCENE_ATTEMPTS) shared by both no… |
| F131 | xcut-tests | `services/orchestrator/app/main.py:497-513 (emitter: services/compositor/app/llm_composer.py:28-35)` | correctness | VTT timestamp regex in /captions cannot match the emitter's own format for >=1h films, si… | Add a round-trip test: build_vtt -> _shift_vtt(offset) and assert every cue moved by exactly offset and the f… |
| F132 | xcut-tests | `services/compositor/app/main.py:386-417` | weak-point | Compositor HF-drop bisect re-renders the whole film once per bad scene — quadratic cost, … | Bound the total recovery work: track cumulative time spent in the bisect and bail to Manim-only (survivors) o… |
| F134 | xcut-tests | `services/compositor/app/duration_prober.py:44-60` | weak-point | probe_duration reads streams[0].duration — picks the first stream, which may be a non-vid… | Probe format=duration (container) as the primary source, falling back to the max of per-stream durations; or … |
| F136 | xcut-tests | `services/voiceover/app/main.py:316-405, 31-47, 234, 281-289` | weak-point | Voiceover retry/fallback loop has no per-provider timeout — a hung TTS engine blocks the … | Add timeout= to every subprocess.run in voiceover (piper, ffprobe x2) and wrap kokoro.create in a thread with… |
| F142 | xcut-tests | `services/code-generator/app/sanitizer.py:228-268` | test-gap | No test exercises the sanitizer's rate_func dropping / background-injection / class-renam… | Add tests: an unknown rate_func is dropped and a known one is qualified; a scene with two classes renames onl… |
| F144 | xcut-tests | `services/compositor/app/main.py:292-466` | weak-point | assemble() dedup future is created with asyncio.get_event_loop().create_future() — deprec… | Use asyncio.get_running_loop().create_future() (or asyncio.Future()), and wrap the whole body in try/finally … |

### 6.4 Low

157 low-severity findings (style, minor robustness, micro-optimizations) are omitted here for signal. Full set: `scratchpad/merged-findings.json` (filter `severity == "low"`). Notable clusters: magic numbers, missing jitter on backoff, log-context leaks across gathered tasks, and assorted "defaults to True/pass on error" smells that individually are minor but collectively erode observability.

---

## 7. Dead code / over-engineering to delete

- **F80** `check_manim_security()` — dead gate (delete or wire in).
- **F164** `voiceover_and_images` stage alias + its resume-status branch — never emitted.
- **F150** `repair_budgets` emits `word_budget` the repair prompt references but never passes to the model — dead plumbing.
- **F175** `detect_content_type` duplicates `classify_scene` — collapse to one.
- **F222** advertised-but-unimplemented Mistral fallback — remove from config or implement.
- General: the triplicated retry-cap literal (FR-16) and the duplicated forbidden-builtin lists (F185) are copy-paste that should be single shared constants.

---

## 8. Test gaps (ranked by blast radius)

1. **`validation_router` / retry-exhaustion / partial-degradation branches [F130, F104, F270]** — the pipeline's control plane, entirely untested. Pure-function tests are cheap; write them first.
2. **`scene_id` int/str round-trip + resume [F252, F292]** — the FR-1 root cause; a single round-trip test would have caught it.
3. **`shared/llm_client` retry/backoff, semaphore-per-loop, model routing [F333, F142]** — systemic; untested.
4. **Compositor fault-tolerant HF-drop/bisect, `_normalize_audio_streams`, VTT windows, real ffmpeg args [F59, F183, F131]** — assembly correctness.
5. **Sanitizer / gate behavior [F198, F90, F142]** — gates executed code.
6. **image-fetcher (entire service) [F250]** — zero tests despite docstrings claiming property-based validation.
7. **web-tier auth/dispatch/quota contract [F250-adjacent]** — no tests for the budget/quota gates.

---

## 9. Prioritized remediation roadmap

**P0 — stop the bleeding (do now; directly maps to the two pains):**
- **FR-3** verify/add `scripts/runner_neon_mirror.py` — if CI is the render path, nothing works without it. *(~0.5–1 d)*
- **FR-1** `_coerce_scene_keys` on every DB load + typed route param + round-trip test — fixes resume and scene-video 404. *(~1 d)*
- **FR-2** classify infra-transient vs content failures in `_post` — stops brief outages from permanently failing jobs. *(~0.5 d)*
- **FR-7** llm_client: loop-bound singletons + sleep-outside-lock — restores real concurrency, fixes test breakage. *(~1 d)*
- **FR-5/FR-6** subprocess timeouts + `format=duration` probe. *(~0.5 d)*
- **CQ-1** add the quality-gate node (rubric self-critique + regenerate) — the single biggest content lever. *(~2–3 d)*

**P1 — robustness & content structure:**
- FR-4 dedup-Future `try/finally`; FR-8 guard None/empty LLM content; FR-9 cross-platform process handling + process-group kill; FR-10 fail-closed quality checks; FR-11 resume stage correctness; FR-13/14/15 config drift, secret validation, healthchecks.
- CQ-2 council best-of/coherence; CQ-3 full-narration reviewer; CQ-4 fact-grounding directive; CQ-6 HF few-shot; CQ-11 fix vision-QA for Claude.

**P2 — cleanup & hardening:**
- FR-12 move `_DRIVING`/`_CANCEL` to shared store; FR-16 hoist retry cap + fix off-by-one; FR-17 per-node timeouts.
- CQ-5 pacing (clamp-then-audit); CQ-7/8/9 prompt fixes; CQ-10 image relevance floor+tiering.
- Section 7 deletions; Section 8 test suite.

---

## 10. Uncertain / needs human review

- **F203 (uncertain):** "no per-call timeout on any LLM call" — the verifier noted the shared NIM read timeout (180s) does bound calls, so the *severity* is arguable; the resilience gap (no per-call `wait_for`, no bounded retry/backoff so one 429 collapses council→single-writer) still stands. Confirm intended behavior.
- **10 findings were refuted** on verification (e.g. an "unbounded `validation_router` recursion" claim, a "sanitizer swallows all exceptions" claim) — excluded from this spec. See `scratchpad/verdicts.json`.
- **293 findings are unverified** (verification cut short by spend limit). The P0/P1 items above are all either confirmed or cross-corroborated by ≥2 agents; treat isolated single-agent medium/low findings as leads, not facts, until spot-checked.

---

*Generated from a 334-finding multi-agent audit (18 finders, partial adversarial verification). Raw data: `merged-findings.json`, `verdicts.json`.*
