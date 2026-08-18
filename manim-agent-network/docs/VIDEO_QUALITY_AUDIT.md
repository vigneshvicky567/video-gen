# Video Quality Audit — Root Causes & Fix Plan

**Date:** 2026-07-13
**Evidence base:** ffprobe/silencedetect/loudnorm measurements + frame extraction on real outputs
(primary specimen: job `594a0c28` "House Robber", 363.7s, status=failed-but-shipped), plus
line-level audit of compositor, voiceover, script-writer, code-generator, and validator.

---

## 1. Measured symptoms (the user-visible problems)

| # | Symptom | Measurement |
|---|---------|-------------|
| A | Video opens with ~7s of silent, mostly-black branding | `assets/intro.mp4`: 6.9s, audio track digitally silent (mean/max −91 dB); black 0–0.5s, 2.8–3.1s, 4.4–6.4s |
| B | Dead-air gaps throughout | 12+ silences of 1.2–5.4s; worst cluster **190.5–212.4s (~22s)** at `silencedetect noise=-35dB` |
| C | Whole video too quiet & uneven | Integrated **−25.8 LUFS** (platform target −14), LRA 17.8 LU |
| D | Background music inaudible | BGM bed measured ≈ −49 dB under content |
| E | Thin content / under-narrated | 456 words ÷ 2.2 wps ≈ **207s of speech in a 364s video** (~43% of runtime is voiceless) |
| F | Robotic, staccato narration | e.g. "Max 7. … Max 11." — telegraphic code-trace prose; flat single-voice TTS |
| G | Visual style inconsistent between scenes | Manim scenes: pure white bg + per-scene random palette; HyperFrames scenes: ivory `#f5f5f0` job palette |
| H | Massive dead space | frames at t=30/75/130: content occupies 5–30% of canvas |
| I | Text collisions & clipping | t=200: "SKIP=11" overlaps "House 3", "TAKE" clipped at frame edge; t=320: two code listings rendered **on top of each other** |
| J | Very low bitrate | 156–343 kbps @ 1080p30 (h264) |

---

## 2. Root causes (file:line) and what to change

### 2.1 AUDIO

| Cause | Location | Fix | Why |
|-------|----------|-----|-----|
| `amix` left at default `normalize=1` → divides all inputs by 2: narration −6 dB, BGM 0.12→~0.06 (≈−49 dBFS, inaudible) | `services/compositor/app/postprocess.py:49` | `amix=inputs=2:duration=first:normalize=0` | One flag restores intended voice level AND makes the 0.12 bed audible |
| No loudness normalization anywhere (zero `loudnorm`/`dynaudnorm` in repo) | final concat `postprocess.py:82-86` | Append `loudnorm=I=-14:TP=-1.5:LRA=11` to the final audio chain | Platform-standard loudness; fixes −25.8 LUFS and tames 17.8 LU LRA |
| BGM mixed into film body **before** intro/outro concat → branding never gets a bed | ordering `postprocess.py:139-207` (music at 176-186, concat at 192-207) | Concat first, then lay BGM across the full timeline | Silent branding disappears without touching assets |
| Intro/outro assets themselves carry silent audio tracks | `assets/intro.mp4`, `assets/outro.mp4` (−91 dB) | Re-export with music, or rely on post-concat BGM bed; **trim the black** (0.5s head, 2s tail); consider dropping intro entirely for cold-open | 7 wasted opening seconds is the single worst retention decision |
| Scene slot = `max(video, audio)` but `<audio>` spans only its own duration → silent scene tails | `duration_prober.py:175`, `llm_composer.py:389-399` | Primary fix is script-side (§2.3); secondarily, continuous BGM bed + ducking masks residual tails | Tails become music, not dead air |
| Scenes with failed TTS ship with **no audio element at all** (the 22s cluster) | voiceover failure tolerated at `orchestrator/app/core/graph.py:627-631`; `llm_composer.py:389` skips `<audio>` when `audio_path` empty | Treat missing narration audio as scene-retryable failure, not silent success | A silent minute is a defect, not a degraded success |
| No ducking | `postprocess.py:33-59` | `sidechaincompress` keyed on narration stem | Professional bed behavior; music breathes under voice |
| TTS output has no gain staging | `voiceover/main.py:165-166` | Per-clip peak/loudness normalize (e.g. to −16 LUFS mono) before compositing | Consistent scene-to-scene voice level |

### 2.2 NARRATION DELIVERY (TTS)

| Cause | Location | Fix | Why |
|-------|----------|-----|-----|
| Single fixed voice `af_sarah`, speed 1.0, zero prosody | `shared/config.py:73-75`, `voiceover/main.py:144-149` | Expressive TTS path (higher-quality voice or provider); vary per-sentence pacing | Flat delivery is baked in regardless of script quality |
| Hardcoded 150ms inter-sentence gap, no pause control | `voiceover/main.py:137` | Respect punctuation: longer pauses after questions/paragraph beats (e.g. 350ms after `?`/`—`) | Rhythm is half of "professional narration" |
| No pronunciation layer for code/math (`dp[i]`, `O(n)`); `=` silently stripped by `_clean_for_tts` | `voiceover/main.py:89-118` (regex at :109) | Token→speech lexicon pass before TTS ("dp[i−1]" → "d p of i minus one", "O(n)" → "big O of n", "=" → "equals") | Currently correct speech depends on the writer voluntarily spelling tokens out |

### 2.3 SCRIPT / CONTENT (the deepest problem — fix first)

| Cause | Location | Fix | Why |
|-------|----------|-----|-----|
| **Duration audit passes on padding**: audit sums `max(est, narration_s)`; model inflates `est` ~2×; repair never fires | `budget.py:26-32` (slot), gate `council.py:764-776` | Add a **narration-coverage check**: `coverage = Σnarration_s / Σslot_s`; fire `_repair` when coverage < 0.85 even if total slot is "within tolerance" | This single bug creates BOTH thin content and half the dead air (symptom B+E) |
| Staccato style mandate: "hard max 25 words … at least one sentence under 6 words … short punches" | `council.py:63-64` (`_NARRATION_RULES`) | Rewrite narration rules for professional flow: varied rhythm, connective tissue, spoken-prose cadence (see §3) | The rules *cause* the robotic fragments ("Max 7. … Max 11.") |
| No warmth/analogy/depth requirements; ONE metaphor **max**, optional | `council.py:51-52` | Require a concrete analogy or mental picture per major concept; encourage narrator personality | Content richness is never asked for, so the model never produces it |
| Rich council path (planner → style contract → section writers → coherence) only above **600s** | `config.py:99` (`COUNCIL_FULL_THRESHOLD_SECONDS`), gate `council.py:720` | Lower threshold (e.g. 180s) so most real jobs get planner+coherence | ≤10-min videos get the leanest single-writer path today |
| Reviewer exception silently returns `{"verdict":"ok"}` | `council.py:644-646` | Retry once; log loudly; surface in meta warnings | In the specimen job the reviewer contributed nothing and nobody knew |
| Reviewer rubric lacks depth/flow dimensions | `council.py:602-613` | Add `prose_flow` (reads as spoken prose, not fragments) and `depth` (explains *why*, not just *what*) scored dimensions | What isn't scored doesn't get fixed |
| 2.2 wps assumption is fast for pedagogy | `config.py:97` | Consider 2.0 wps for technical topics | Small, but compounds with coverage fix |

### 2.4 VISUALS

| Cause | Location | Fix | Why |
|-------|----------|-----|-----|
| Manim prompts never receive the per-job visual identity (`job_style`) | `code-generator/app/main.py:797-850` (`_build_manim_prompt`), call at :882 | Thread `job_style` into the Manim prompt; set `config.background_color` from palette | Kills white-vs-ivory clash and Manim per-scene palette roulette |
| Rules bias sparse: "build SMALL", "prefer ≤3", "if unsure, scale it down"; few-shot models one axes + one dot + one formula | `manim_rules.md:131,133,135,141`; few-shot `main.py:756-777` | Add frame-fill guidance (target ~60% canvas occupancy at hero moment, safe margins), richer few-shot | Dead space is trained in |
| Anti-overlap rules are prose-only; validator gate is AST-only (no pixel checks) | `validator/app/main.py:631-766` | Enable vision QA; add post-render bounding-box overlap assertion for Manim | t=320 double-code-listing shipped because nothing looks at pixels |
| Vision QA exists but **off by default** and unset in .env | `config.py:181-182` (`VISION_INSPECT_ENABLED=false`); short-circuit `validator/main.py:402` | Set `VISION_INSPECT_ENABLED=true`; its "cluttered" verdict + legibility rubric target exactly symptoms H/I | The gate that would have caught the worst frames never ran |
| HyperFrames scenes get zero rendered-pixel QA (regex-only) | `validator/main.py:214-275` | Run `hyperframes lint/validate/inspect` (built-in layout + WCAG contrast auditors in the existing dependency) as HF gate | Free, purpose-built tooling already shipped with the renderer |
| Encode chain has no quality floor: HF master `--quality standard` + NVENC; final concat `-preset veryfast -crf 20` | `compositor/app/main.py:108-122`; `postprocess.py:82-86` | HF `--quality high`; final `-preset slow -crf 18` | Low bitrate is mostly a *symptom* of empty frames, but these knobs matter for text edges |

---

## 3. Narration/style prompt rewrite (the "professional flow" ask)

Current `_NARRATION_RULES` optimize for terseness → telegraphic output. Replacement direction:

1. **Spoken-prose cadence**: full sentences by default; fragments only as deliberate emphasis
   (≤1 per scene). Vary sentence length 8–22 words; forbid three consecutive sentences of
   similar length. Every scene needs connective tissue ("which means…", "so here's the catch…").
2. **Depth mandate**: for each new idea, narrate *what*, *why it's true*, and *why the viewer
   should care* — in that scene, not deferred.
3. **Analogy requirement**: each major concept gets one concrete mental picture drawn from
   everyday life; sustained analogies preferred over one-off similes.
4. **Momentum**: scene openings must be forward references or consequences ("And that one
   decision is exactly what breaks…"), never restarts. Questions get answered within 2 scenes.
5. **Worked examples narrated as *thinking*, not tracing**: "Nine plus the two we banked
   two houses ago — eleven. Better than the seven we'd keep by skipping." (vs "9 plus 2
   equals 11. Max 11.")
6. **Keep** the existing bans (no "basically", no "in this video…"), the hook mandate, the
   reframe-ending, and words-per-second budgeting (now enforced via coverage, §2.3).

Verification protocol: A/B the old vs new prompt against the live script model
(`SCRIPT_WRITER_MODEL`, NIM) on the same topic; judge with an independent LLM pass on
flow/depth/hook; iterate until the new prompt wins decisively on all dimensions.

---

## 4. Priority order

| Tier | Items | Effort | Impact |
|------|-------|--------|--------|
| **1 — same day** | amix `normalize=0`; final `loudnorm`; BGM-after-concat; `VISION_INSPECT_ENABLED=true`; trim/replace intro | config + ~10 lines | Fixes A, C, D; guards I |
| **2 — this week** | Narration coverage audit + repair trigger; `_NARRATION_RULES`/`_STORY_RULES` rewrite (§3); reviewer retry + new rubric dims; TTS-failure = scene failure; ducking | ~100 lines | Fixes B, E, F (root) |
| **3 — next** | `job_style` → Manim prompts; frame-fill rules + few-shot; per-clip TTS normalize + pause logic + pronunciation lexicon; HF `inspect` gate; encode knobs; council threshold 600→180 | days | Fixes F (delivery), G, H, I, J |

**Single highest-leverage change:** the narration-coverage audit (§2.3 row 1) — it simultaneously
attacks thin content AND mid-video dead air, the two most user-visible defects.

---

## 5. Addendum — changes applied & live-verified (2026-07-13)

### 5.1 CRITICAL live finding: script-writer model is dead
`SCRIPT_WRITER_MODEL=moonshotai/kimi-k2.6` (.env) returns **404 on all 3 NIM keys**
("Function … not found for account") — the function was retired server-side. Every new job
was silently degrading to the minimal-script fallback. `mistralai/mistral-large-3-675b-instruct-2512`
verified reachable and now serves as fallback until .env is updated.

### 5.2 Applied to source (script-writer service + shared config)

| Change | Files |
|--------|-------|
| Narration-coverage audit: `narration_coverage` in `budget.audit()`; `within_tolerance` now requires coverage ≥ `SCRIPT_MIN_NARRATION_COVERAGE` (default 0.80) so repair fires on under-narrated scripts | `budget.py`, `shared/config.py` |
| Model fallback chain: `SCRIPT_WRITER_FALLBACK_MODELS` (comma list) tried in order on any provider failure, per call | `council.py` (`_acreate_with_fallback`), `shared/config.py`, `.env.template` |
| `_NARRATION_RULES` rewritten for professional flow: words-drive-time, connected spoken prose (≤1 fragment/scene), rhythm variance, what-why-so-what depth, analogy per concept, examples-as-thinking, symbols spoken as words | `council.py` |
| `_STORY_RULES`: never re-walk an already-seen example | `council.py` |
| `_budget_block`: total word budget stated as a number + 3-step words→duration recipe | `council.py` |
| Reviewer: retry once on failure, loud `reviewer_failed` marker in meta warnings (was: silent `verdict:ok`); new scored dimensions `prose_flow` + `depth` | `council.py` |
| Repair prompt: style guard (trim redundancy not sentences; expand depth not filler) | `council.py` |

### 5.3 Live A/B + end-to-end verification (mistral-large-3, real council code path)

| Metric | Old prompts | Tuned prompts (e2e) |
|--------|------------|---------------------|
| Narration coverage | 0.46 (54% dead air — matches shipped job 594a0c28) | **0.83** |
| Fragment sentences (<4 words) | 39.5% | ~2–12% (rhetorical only) |
| Avg sentence length | 5.6 words (telegraphic) | ~10–12 words |
| Final duration deviation | audit lied ("within tolerance") | **−0.2%** after auto-repair |
| Fallback chain | n/a | fired 4/4 stages (dead primary → fallback), logged |

### 5.4 Tier 1–3 applied & reviewed (2026-07-13, subagent-driven, each task reviewed + fix-looped; final whole-branch review = MERGE-READY)

| Item | Change | Files | Verified |
|------|--------|-------|----------|
| Audio mix | `amix ...:normalize=0`; sidechain-duck music under voice; `loudnorm=I=-14:TP=-1.5:LRA=11` master; concat-intro/outro-FIRST then one bed+loudness pass over whole timeline; `build_loudnorm_cmd` for no-music case; concat `-preset fast -crf 18` | compositor/app/postprocess.py (+test) | test_postprocess.py green; ffmpeg filtergraph reviewed valid |
| Vision QA | `VISION_INSPECT_ENABLED` default → true | shared/config.py | — |
| Intro | trimmed 6.9s→4.07s (dead black tail cut); backup in scratchpad | assets/intro.mp4 | ffprobe |
| Council | `COUNCIL_FULL_THRESHOLD_SECONDS` 600→180 | shared/config.py | — |
| TTS delivery | per-clip `loudnorm=I=-16`; punctuation pauses (?/!→0.35s, .→0.25s, else 0.15s); code/math pronunciation lexicon (operand-context `*`/`+`, `O(...)`, `name[...]`, compound comparisons) that does NOT mangle markdown | voiceover/app/main.py | demo() self-check run, all pass |
| TTS failure | failed narration = retryable scene failure via shared budget; exhausted scene dropped → job "partial", never silent video | orchestrator/app/core/graph.py | py_compile; test_validation_router_retry green |
| Manim identity | `job_style` threaded into Manim prompt → `config.background_color`/colors from job palette; WHITE mandates reworded background-relative | code-generator/app/main.py, prompts/manim_rules.md | py_compile; compositor `pal_bg` share verified (llm_composer.py:306) |
| Manim layout | frame-fill (~60-75% occupancy) + safe-margins + anti-collision replace shrink bias; larger few-shot | prompts/manim_rules.md, code-generator/app/main.py | reviewed |
| HF QA + quality | render `--quality standard`→`high`; layout+contrast QA gate: `check` → fallback `inspect`+`validate` (image pins hyperframes 0.6.97 which lacks `check`) → warn if none; findings = warnings only | compositor/app/main.py | verified vs actual 0.6.97 install (fallback fires, findings flow) |

### 5.5 Deferred follow-ups (documented, NOT blockers — confirmed correctly deferred by final review)
1. **Voiceover service returns HTTP 500 for content failures** → `_post` maps 5xx to `InfraUnavailable`, so genuine content failures (unsynthesizable narration) burn the *infra* retry budget (3, shared with code-gen/validator) and are mislabeled `[infra]` in job state. Correctness holds (scene dropped, job "partial"). Fix: have `voiceover/main.py` return 4xx / structured `success:false` for content failures so `graph.py`'s already-present content branch fires. Wastes compute on deterministic failures until fixed.
2. **No automated test on the new `voiceover_node` retry loop** (loop is provably terminating; add a small unit test as insurance).
3. **Palette fallback default mismatch**: code-gen defaults `palette_bg` to `#f5f5f0` (light), compositor `pal_bg` to `#0e1116` (dark). Unreachable in normal flow (`art_director_node` always sets `job_style`; `palette_bg` is a required schema field), but if `job_style` is ever None (legacy/resume) Manim renders light while the backdrop is dark → dark flash at crossfades. Fix: one shared default constant.

### 5.6 Operator actions required (cannot be done from source)
- Restart the affected services to load the changes (per standing rule, not done automatically): **script-writer** (prompts/coverage/fallback), **voiceover** (TTS delivery), **code-generator** (Manim identity/fill), **compositor** (audio master + HF QA/quality), **orchestrator** (TTS-failure handling).
- `.env`: confirm `SCRIPT_WRITER_MODEL` reachable + `SCRIPT_WRITER_FALLBACK_MODELS` set (§5.1); confirm `COMPOSITOR_LLM_MODEL`/`CHAT_MODEL` aren't the dead kimi-k2.6.
- `VISION_INSPECT_ENABLED` now defaults true in code; no .env change needed unless overriding.
- Optional: to make the HF QA gate run on newer CLIs directly (skip the fallback), bump the compositor image's `hyperframes@0.6.97` pin — but that pin is flagged render-breaking-if-changed; test renders first.
**.env update required by operator** (ping-verified 2026-07-13, all 3 keys):

```
SCRIPT_WRITER_MODEL=mistralai/mistral-large-3-675b-instruct-2512
SCRIPT_WRITER_FALLBACK_MODELS=openai/gpt-oss-120b,deepseek-ai/deepseek-v4-flash
```

Ping results: mistral-large-3 (200, 1s, proven e2e) · gpt-oss-120b (200, real prose) ·
deepseek-v4-flash (200 but intermittent 503 — tail fallback) · **nemotron-super-49b-v1.5
EXCLUDED** (returns reasoning-only, empty `content` → breaks the script parser) ·
kimi-k2.6 + mistral-large-2 dead (404 all keys) · deepseek-v4-pro / qwen3.5 / glm-5.2 /
llama-3.3-70b cold-start timeouts (>150s) on this account.
Also check `COMPOSITOR_LLM_MODEL` and `CHAT_MODEL` in .env — if they point at kimi-k2.6
they are dead too.
