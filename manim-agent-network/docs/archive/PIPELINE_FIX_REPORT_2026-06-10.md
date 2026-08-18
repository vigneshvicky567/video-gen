# Pipeline Fix Report — 2026-06-10

Follow-up to `VIDEO_QA_REPORT_f24799da.md`. Every claim in that report was re-verified
against the code and against the actual HyperFrames renderer source before fixing.
This doc records: what the QA report got right, what it got **wrong**, the deeper root
causes found, every fix applied with its reason, and the verification evidence.

---

## 1. Re-verification of the QA report

| QA finding | Verdict | Notes |
|---|---|---|
| F1 — scenes 3 & 6 dropped on `config.background` / `ThreeDCamera.animate` | ✅ Confirmed | Patterns absent from validator AST deny-list (`validator/app/main.py`) |
| F2(a) — master GSAP timeline empty | ✅ Confirmed | `llm_composer.py:303-308` (old) |
| F2(b) — per-scene timelines orphaned | ⚠️ Right symptom, **wrong mechanism** | See §2 — the proposed fix (`main.add(sub, start)`) would have violated the HyperFrames timeline contract |
| F2(c) — white host background | ✅ Confirmed | `llm_composer.py:193` and `:229` (old) |
| F3 — scene 9 dark-on-dark | ✅ Confirmed | Generated code omitted `config.background_color = WHITE` → Manim default near-black canvas + dark text |
| F4 — garbled LaTeX / partial reveals | ✅ Confirmed | No MathTex width/overlap rules in prompts |
| F5 — blank scenes still ship audio+caption | ✅ Confirmed | Consequence of F2; addressed via lint gate (§4.3) instead of frame-variance probe |
| F6 — dead ffmpeg assembler | ✅ Confirmed | `shared/config.py:49` default pointed at it |

## 2. Deeper root causes the QA report missed

Found by pulling the actual `hyperframes` npm package (v0.6.88, same `@latest` the
Docker image installs) and reading the bundled compiler/runtime in `dist/cli.js`.

### 2.1 Renderer contract (evidence from `cli.js` source)

- **Auto-nesting**: a timeline registered as `window.__timelines["X"]` is automatically
  nested at the `data-start` of the element carrying `data-composition-id="X"`.
  Lint rule `timeline_id_mismatch` states it verbatim: *"Timeline registered as "X" but
  no element has data-composition-id="X". The runtime cannot auto-nest this timeline."*
- **Visibility windows**: the compiler emits `tl.set(visibility/opacity)` at each clip's
  `data-start`/end (`generateDefaultGsapAnimations`).
- **Sub-composition inlining** (`core/src/compiler/inlineSubCompositions.ts`): for hosts
  with `data-composition-src`, the compiler parses the scene file (template wrapper
  OPTIONAL — falls back to `<body>` content), **scopes its CSS** to the composition root
  (`scopeCssToComposition`), **wraps its scripts in isolated closures**
  (`wrapScopedCompositionScript`), drops the inner root div, and rewrites asset paths.

### 2.2 Why the old composition was blank — three compounding defects

The old compositor inlined scene HTML **with hand-rolled regex**
(`_inline_hyperframes_scene`), bypassing all of the compiler machinery above:

1. **`const tl` redeclaration → dead scripts.** Every generated scene registers
   `const tl = gsap.timeline(...)` at top level; the master script declared `const tl`
   too. Multiple top-level `const tl` declarations in one document share the global
   lexical scope → every script block after the first threw
   `SyntaxError: Identifier 'tl' has already been declared` at parse time and **never
   ran**. This is why scene 10's hide-tweens never executed and its outro checklist was
   visible at t=0 (the QA report's unexplained "outro markup at 0:00" anomaly), while
   scene 1's (first script) `tl.from(autoAlpha:0)` hides DID run and were never
   reversed (timeline never driven) — its "entrances never ran" symptom.
2. **Inner roots kept `data-start="0"` + had no `.clip` class** → wrong/initially-leaky
   visibility windows for the inlined content, stacked across scenes by z-index.
3. **No CSS/selector scoping** → `.title`, `.summary` etc. collided across the three
   inlined scenes (QA report's "garbled overlapping corner text").

The QA report's proposed fix (manually grafting `main.add(sub, start)`) would have
fought the auto-nesting runtime (double-drive risk) and contradicted the skill contract
("Framework auto-nests sub-timelines — do NOT manually add", hyperframes SKILL.md L291).

## 3. Fixes applied

### 3.1 Compositor — framework-native scene mounting (the real F2 fix)

`services/compositor/app/llm_composer.py`

- Deleted ~100 lines of regex inlining. Each HyperFrames scene is now mounted as a
  **sub-composition clip**:
  ```html
  <div class="clip scene-visual scene-host" id="host-scene-N"
       data-composition-id="scene-N"
       data-composition-src="compositions/scene_N.html"
       data-start="{slot start}" data-duration="{slot}"
       data-track-index="{track}" data-width="1920" data-height="1080"
       style="...background:#0a0f1c;...">
  ```
  The HyperFrames compiler does the inlining/scoping/nesting it was built for.
- Scene files are copied to `compositions/` — the CLI lints root-level HTML files with
  `data-composition-id` as duplicate entry points (`multiple_root_compositions`).
- Host background `#ffffff` → `#0a0f1c`: a failed scene now degrades dark instead of
  flashing white (F2c).
- Master GSAP CDN unified to `https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js`
  (same as the scenes use) so the compiler dedupes to one load; master script wrapped in
  an IIFE (no global `const tl`).
- Audio clip emitted only when the scene has an audio path; caption falls back to the
  slot duration when narration audio is missing.

### 3.2 Validator — catch the failure classes before they burn renders (F1)

`services/validator/app/main.py`

- AST deny-list additions (each message includes the replacement, because the message
  is fed back into the code-generator's retry prompt):
  - `config.background` → "use `config.background_color`" (scene 3's killer)
  - `<x>.camera.animate` → "use `self.move_camera(...)`" (scene 6's killer)
  - `Rotating(radians=/axis=)` → `Rotate(mob, angle=...)`
  - `Circle/Arc(arc_length=...)` → `radius=`/`angle=`
  - `Code(code=...)` → removed in Manim CE 0.20+
  - invalid color constants `DARK_RED/DARK_BLUE/DARK_GREEN/LIGHT_GRAY/DARK_GRAY`
- Each of these previously cost up to 5 full render attempts (scene 3 + 6 burned 10
  doomed renders ≈ a large slice of the 42-min wall time). Now they fail in
  milliseconds at preflight with a targeted fix hint.
- `validate_hyperframes(code_path, scene_id)` now enforces the mounting contract:
  `data-composition-id` AND the `window.__timelines[...]` registry key must equal
  `"scene-{scene_id}"` exactly (a mismatch = auto-nesting silently fails = blank
  scene), plus a `repeat: -1` rejection.
- Self-test source extended to cover the new checks (stale-image guard).

### 3.3 Real lint in the validation loop (replaces the F2b frame-variance idea)

The HyperFrames CLI ships a linter that detects the actual blank-scene classes —
verified against the f24799da artifacts where it caught scene 10's
`gsap_from_opacity_noop` (CSS `opacity:0` + `gsap.from(opacity:0)` = animates 0→0,
never visible: **the exact mechanism that blanked scene 10**), plus
`Math.random()` nondeterminism and `repeat:-1` in scene 1.

- New `POST /lint` on the compositor (it owns the node/hyperframes install): copies the
  scene into a temp project, runs `hyperframes lint --json` in a worker thread, returns
  errors/warnings with the CLI's FIX hints.
- Validator calls it for every HyperFrames scene after the structural checks; lint
  errors fail validation, so the code-generator's retry prompt receives the findings.
- Permissive on tooling failure (lint unreachable → structural checks only) so the
  pipeline never bricks on the new dependency.

### 3.4 Sanitizer — deterministic guarantees (F3 root kill)

`services/code-generator/app/sanitizer.py`

- `config.background` → `config.background_color` rewrite (works for assignments too).
- **Injects `config.background_color = WHITE` after the imports when the LLM omitted
  it.** Scene 9's dark-on-dark was dark text on Manim's default near-black canvas; the
  whole pipeline contract assumes a white canvas. Contract is now enforced in code, not
  hoped-for in prompts.
- `DARK_GREEN` added to the invalid-color map.

### 3.5 Code-generator prompts (F3/F4 + contradictions)

- `_build_hf_prompt` had three direct contradictions against its own system prompt:
  mandated `background:#ffffff` (system says tinted, never pure white), recommended
  Inter (system forbids it), and the system trailer pinned GSAP cdnjs 3.12.2 (rules
  + compositor use jsdelivr 3.14.2). All three aligned.
- **HyperFrames retries were blind**: `_generate_hyperframes` ignored
  `request.error_log`/`previous_code` entirely — every retry regenerated from scratch.
  Now a retry prompt carries the previous HTML + the validation/lint error.
- `manim_rules.md` additions: equation overflow rules (`scale_to_fit_width` before
  reveal, one equation per region, ReplacementTransform/FadeOut before rewriting a
  region — F4), and a contrast contract (explicit dark-color whitelist for the white
  canvas, forbidden light tints, node fill pattern — F3).
- `hf_rules.md`: documented the CSS-`opacity:0` + `gsap.from(opacity:0)` no-op trap.

### 3.6 Orchestrator loop fixes

`services/orchestrator/app/core/graph.py`

- **Stale-code re-render burn**: when code generation failed, the scene's previous
  `code_paths` entry survived, so the validator re-rendered the *exact code that had
  already failed* (up to minutes per render) and double-bumped the retry counter.
  Failed generations now pop the stale path.
- **Voiceover all-or-nothing**: one transient TTS failure failed the entire job at the
  last stage. Now: fail only if ALL scenes lost narration; otherwise ship affected
  scenes without audio (compositor + duration prober already tolerate this).

### 3.7 Script-writer planning guardrails

3D Manim is the most fragile, slowest path (scene 6 was planned as "blindfolded on
hilly terrain" → LLM reached for `ThreeDScene` + camera animation and died 5 times).
The planner prompt now requires 2D visualizations (describe contours/cross-sections
instead) and one focused visualization per Manim scene (≤6 beats) — scene 9 needed 4
retries because it packed a full training-loop diagram + text reveals into one scene.

### 3.8 Config (F6)

`shared/config.py`: `ASSEMBLER_URL` default now `http://compositor:8005` with a comment
that the ffmpeg `assembler` service is the legacy path. Removes the silent
default-vs-compose mismatch.

### 3.9 Test fixes

- `tests/test_validator_robustness.py` imported `app.main` ambiguously — both validator
  and code-generator expose an `app` package and code-generator's shadowed it (7 tests
  failing before any of this work). Now loads the validator module by file path.
- `tests/test_llm_composer.py` asserted the master timeline variable name; now asserts
  the contract (`window.__timelines["main"] =`).
- New `scripts/smoke_compose.py`: rebuilds a composition from any past job's artifacts
  on the host (no Docker) for fast compositor iteration.

## 4. Verification evidence

### 4.1 Unit level

- New AST checks: scene 3's and scene 6's exact failing sources now fail preflight with
  actionable messages; valid code passes; validator self-test passes.
- Sanitizer: rename, injection-after-imports, no-double-injection, DARK_GREEN cases all
  pass.
- Full suite: **53 passed** (only `test_latex_package_availability` excluded — needs a
  LaTeX install, host-only limitation; it runs inside the validator image).

### 4.2 Composition smoke test (real f24799da artifacts, host render)

`python scripts/smoke_compose.py` + `hyperframes lint` + `hyperframes snapshot`:

- Lint: zero composition-level errors (no `multiple_root_compositions`, no
  `timeline_id_mismatch`, no missing registry). The 3 remaining errors are content bugs
  inside the OLD job's generated scenes — two of which the new validator/lint loop now
  rejects at generation time.
- Snapshots vs the shipped video:

| t | Scene | Shipped video (QA report) | New composition |
|---|---|---|---|
| 5s | 1 (HTML) | near-black, garbled corner text, no entrances | Full title card + subtitle + starfield, entrances ran |
| 20s | 2 (HTML) | blank white + caption only | "The Learning Problem" + data table + pattern box |
| 70s | 5 (Manim) | OK | OK, correct slot |
| 170s | 10 (HTML) | blank white + caption only | Checklist animated in (sans `.summary` — old artifact's opacity-noop bug, now lint-rejected) |

### 4.3 Review

Cavecrew review of the full diff: 1 real finding (blocking `subprocess.run` in the
async `/lint` endpoint — fixed with `asyncio.to_thread`); 4 false positives verified
against code/tests and discarded.

## 5. Expected impact on the f24799da failure profile

| Failure | Old outcome | New outcome |
|---|---|---|
| `config.background` (scene 3) | 5 renders burned, scene dropped | Sanitizer rewrites it silently; if anything similar slips through, AST preflight fails in ms with the fix hint |
| `ThreeDCamera.animate` (scene 6) | 5 renders burned, scene dropped | Planner avoids 3D; AST preflight catches the pattern with the fix hint |
| Blank HTML scenes (1, 2, 10) | ~45s of blank/garbled video | Framework-native mounting renders them; comp-id/timeline-key contract + lint gate catch regressions at validation |
| Dark-on-dark (scene 9) | Shipped unreadable | WHITE canvas injected deterministically + contrast whitelist |
| Garbled LaTeX (scene 4) | Shipped garbled | Overflow/overlap prompt rules (prompt-level only — render-time probe still TODO) |
| Voiceover transient failure | Whole job failed | Per-scene degradation |

## 6. Remaining / deferred

- **E2E run** of the rebuilt stack on a fresh topic + `/watch` review (in progress).
- Frame-variance blank-scene probe at assembly (F2b defense-in-depth) — lower priority
  now that lint gates generation; revisit if a new blank class appears.
- LaTeX render-time overflow detection (F4 is prompt-level only).
- Out-of-band: rotate the NVIDIA/Pexels keys in `.env` (unchanged, still pending).
- Deferred hardening backlog from the 10-agent review (auth, traversal, Docker
  non-root, rate limiting) — unchanged.
