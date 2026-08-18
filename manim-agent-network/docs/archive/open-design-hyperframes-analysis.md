# Open Design HyperFrames vs manim-agent-network — Analysis

> Source: `github.com/nexu-io/open-design` (Apache-2.0), cloned & read 2026-06-18.
> Subject: what makes their HTML/GSAP video gen ("HyperFrames") robust, and what
> our Manim pipeline could borrow. Analysis (§1-7) + combined verdict (§8) + first
> implementation shipped (§9, intake "great questions" — code changed 2026-06-18).

---

## 0. TL;DR

- **Their renderer is dumb** (`npx hyperframes render`, paused GSAP timeline, seek-per-frame). The power is everything *around* it.
- **They close the loop on VISUAL correctness** (does the frame look right?), not just code correctness (does it run?).
- **Our pipeline is architecturally stronger** (multi-service, AST sanitizer, 5-retry repair loop, graceful degradation, SQLite resume) but has **no visual QA** and **no scene continuity**.
- Our scenes are generated **independently in parallel** then **concatenated** → no shared identity, no relative timing, jump cuts.
- Biggest wins for us: visual gates (contrast + animation-map) into the validator, inter-scene transitions, one motion signature + palette per job, deeper motion prompt.

---

## 1. What makes HyperFrames "perfect" — five layers

| Layer | Mechanism | Kills |
|---|---|---|
| Identity gate | Declare palette/font/motion BEFORE any HTML. 8 named style presets + DESIGN.md binding. Else ask 3 Qs. | Generic `#3b82f6`/Roboto slop |
| Layout-before-animation | Author static hero-frame CSS first, THEN `gsap.from()` entrances | Elements landing on top of each other |
| Timeline contract | All `{paused:true}`, registered on `window.__timelines`, duration from `data-duration` not GSAP length | Race conditions, nondeterminism |
| `contrast-report.mjs` | Seeks N frames, measures **actual rendered pixels** WCAG ratio, **exits 1 on AA fail** | Unreadable text |
| `animation-map.mjs` | Samples every tween bbox, flags `collision`/`offscreen`/`invisible`/`dead-zone`/pacing, ASCII Gantt | Invisible/colliding/dead-air scenes |

Core principle: **MEASURE the output, not just lint the input.** Generate → render → inspect rendered pixels → fix.

---

## 2. Head to head

Different strengths. Ours = production harness. Theirs = visual QA.

| Axis | Ours (manim-agent-network) | open-design |
|---|---|---|
| Architecture | Multi-service: script council → parallel code-gen → validator → voiceover/images → chunked assembly. SQLite resume. | Single agent authors inline |
| Code-correctness gate | **Strong** — AST sanitizer (forbidden modules/builtins), `manim render`, regex HF structural check, remote lint, **5-retry repair loop w/ error_log**, graceful degradation | Weaker — lint only, agent self-corrects |
| **Visual-correctness gate** | **NONE** — validate code RUNS, never that frames LOOK right | contrast-report + animation-map + visual-inspect |
| Visual identity | ONE hardcoded baseline in prompt → every video same look | 8 presets + DESIGN.md → variety/brand |
| Inter-scene transitions | Chunks **concatenated** = jump cuts | #1 non-negotiable: always transition, never jump-cut |
| Motion depth | Shallow ("vary eases ≥3") | Deep — easing=emotion, speed=weight, build/breathe/resolve |
| Manim/math path | Have it (hybrid hyperframes+manim) | HTML only |
| TTS pipeline | Kokoro+edge fallback, per-sentence resilience, clean_for_tts | basic |
| Long-form | Council planner, chunking, adaptive timeouts | manual |

---

## 3. Prompt comparison

Our `hf_rules.md` is a **compressed port of their SKILL.md baseline** — same DNA (banned fonts, scene-content padding, caption safe-zone, autoAlpha, paused timeline, WCAG 4.5:1, GSAP CDN pin). Ports the *baseline*, not the *intelligence*.

Missing from our HF prompt vs their full skill:

1. **Contrast/animation-map are instructions in our prompt, GATES in theirs.**
   - Ours: `"text must hit WCAG 4.5:1"` — a hope; LLM may ignore.
   - Theirs: prompt says it AND `contrast-report.mjs` measures rendered pixels and fails build.
2. **Motion language thin.**
   - Ours: `"vary eases (≥3), stagger, one motion signature"`.
   - Theirs: *"slowest 3× slower than fastest; easing is emotion (.out=confident, .in=exit); speed=weight (0.15-0.3s urgency … 0.8-2s cinematic); scene = build(0-30%)/breathe(30-70%, ONE ambient motion)/resolve(70-100%); don't start at t=0."*
3. **No identity system.** We bake one baseline (`#f4f1ea / #0e1116`) into every prompt. They pick a named style per job (Swiss Pulse, Velvet Standard, Shadow Cut…), each w/ exact palette + easing signature + anti-patterns.
4. **No transition contract.** Our HF scenes are independent compositions. Theirs: *"entrance on every scene, NO exit except final — the transition IS the exit, outgoing content fully visible when transition starts."*

Our **Manim prompt and script-writer prompt are excellent** and have no open-design equivalent (HTML-only). Pacing budget (2.2 w/s, run_time sum just under duration), council planner, few-shot, retry-with-error_log — ahead. Keep.

---

## 4. How they context-awarely attach scenes

**ONE html file. All scenes = divs under one root composition.** Not separate files.

```html
<div data-composition-id="my-video" data-duration="60">
  <div id="scene1" data-start="0"  data-duration="8">…</div>
  <div id="scene2" data-start="8"  data-duration="10">…</div>
</div>
```

Context-aware mechanisms:
- **`window.__timelines` auto-nesting** — each scene registers its paused timeline by `data-composition-id`; framework auto-nests into master clock. Agent never hand-wires master.
- **Relative timing** — `data-start` can reference another clip (`"el-1"`) or do math (`"intro + 2"`). Scenes know about each other.
- **`data-track-index`** prevents same-track overlap (≠ z-index, which stays CSS).
- **Continuity enforced:** shared palette gate (one DESIGN.md across ALL scenes), ambient motion carried through, transition rule = *"transition IS the exit, outgoing content fully visible when it starts"* = no dead frames.
- **Editing context-aware:** *"Read the full composition first — match existing fonts, colors, animation patterns. Only change what was requested. Preserve timing of unrelated clips."*

### Where ours diverges (the big one)
Our scenes are **independent compositions** (`scene-{id}`), each generated by a **parallel code-gen call that sees ONLY its own narration+visual** — never prior/next. Then compositor **concatenates**. Result:
- No shared root, no `data-start` cross-references → no relative-timing chains.
- No context between scene prompts → scene 3 can't echo scene 1's motif.
- Concatenation = jump cuts (their #1 forbidden pattern).

Their "context-aware attach" is structurally a thing we lack: **a composition layer that knows all scenes at once.** Our parallelism is exactly what prevents continuity. Fixable without killing parallelism (§7).

---

## 5. How they handle errors

Core principle, from `apps/daemon/src/media.ts`:
```ts
// HyperFrames is a local render, not a remote provider. Falling back
// to a stub here hides actionable composition/preflight failures and
// can make the agent retry or narrate a fake MP4 as success.
if (def.provider === 'hyperframes') {
  throw err;   // NO STUB FALLBACK FOR LOCAL RENDERS
}
```
**They refuse to fake-success.**

Chain:
1. **Preflight asserts** — 3 files (`hyperframes.json`/`meta.json`/`index.html`) each missing → error carries exact fix command (`Run npx hyperframes init …`).
2. **Render** — stream stderr, keep last 8000 chars; on non-zero exit attach **last 12 stderr lines** to thrown error. 5-min `SIGKILL` timeout.
3. **CLI gates produce STRUCTURED, located guidance** (not raw stderr):
   - `lint` → DOM/attr syntax
   - `validate` → `⚠ .subtitle "secondary text" — 2.67:1 (need 4.5:1, t=5.3s)`
   - `inspect` → per-frame overflow element + fix (`max-width`, `fitTextFontSize()`, or mark `data-layout-allow-overflow`)

### Where ours diverges
We're **ahead on the loop**: AST sanitizer, `manim render`, **5-retry repair feeding error_log back**, graceful degradation, SQLite resume. Theirs is single-shot self-correct.

Lessons to steal:
- **Never narrate fake success.** Confirm our stub/fallback path can't let a placeholder mp4 pass as a finished scene.
- **Enrich error_log like their CLI.** Today repair gets `error_log[-600:]` (raw stderr). Theirs gives typed+located guidance (`contrast 2.67:1 @t=5.3s`, `overflow on .subtitle`). Better signal → fewer retries to converge.

---

## 6. How they animate "perfectly"

Philosophy: **motion is communication. Transition = verb, easing = adverb.**

- **Easing = emotion/direction:** `.out` entrances (default, confident), `.in` exits (accelerate away), `.inOut` repositioning. Same slide w/ `expo.out` vs `sine.inOut` vs `elastic.out` = confident vs dreamy vs playful.
- **Speed = weight:** 0.15–0.3s urgency · 0.3–0.5s professional · 0.5–0.8s luxury · 0.8–2s cinematic.
- **Scene = build/breathe/resolve:** build 0-30% (staggered entrances), breathe 30-70% (ONE ambient motion), resolve 70-100% (exit faster than entrance). "Stillness after motion is powerful."
- **Stagger = hierarchy:** order by importance not DOM order, overlap entries, whole sequence **<500ms regardless of count.**
- **Variety guardrails (anti-slop):** ≤2 tweens same ease/scene · slowest 3× slower than fastest · vary entrance direction (not all `y:30,opacity:0`) · per-scene stagger rhythm · don't start at t=0 (0.1-0.3s offset) · ambient motion chosen (pan/rotate/scale/color/none).
- **Layout-before-animation:** static hero-frame CSS first, THEN `gsap.from()`. Overlaps invisible until render if you guess from animated start-state.
- **Transition system:** energy table (calm/medium/high → transition+duration+easing) × mood table (warm/cold/editorial/tech/tense/playful/dramatic/luxury/retro) × narrative position (opening/between/topic-change/climax/wind-down/outro). CSS **or** shader catalog (`@hyperframes/shader-transitions`); never mix CSS+shader in one comp.

### Transition tables (verbatim)

**Energy → primary transition:**

| Energy | CSS primary | Shader primary | Duration | Easing |
|---|---|---|---|---|
| Calm (wellness, brand, luxury) | Blur crossfade, focus pull | Cross-warp morph, thermal distortion | 0.5-0.8s | `sine.inOut`, `power1` |
| Medium (corporate, SaaS, explainer) | Push slide, staggered blocks | Whip pan, cinematic zoom | 0.3-0.5s | `power2`, `power3` |
| High (promos, sports, music, launch) | Zoom through, overexposure | Ridged burn, glitch, chromatic split | 0.15-0.3s | `power4`, `expo` |

**Narrative position:**

| Position | Use |
|---|---|
| Opening | Distinctive, match mood. 0.4-0.6s |
| Between related points | Primary transition, consistent. 0.3s |
| Topic change | Different from primary (staggered blocks, shutter) |
| Climax / hero reveal | Boldest accent, fastest/most dramatic |
| Wind-down | Gentle, blur crossfade. 0.5-0.7s |
| Outro | Slowest, simplest, closure. 0.6-1.0s |

### Where ours diverges
`hf_rules.md` has baseline ("vary eases ≥3, stagger, autoAlpha") but none of: easing=emotion/speed=weight, build/breathe/resolve, stagger-by-importance <500ms, "slowest 3× fastest", transition system (we have zero inter-scene transitions). Manim path has **no motion philosophy** beyond pacing budget.

---

## 7. Root cause + ranked fixes

§4 and §6 gaps are the **same missing piece**: a **composition layer that sees all scenes together.** Independent per-scene gen buys parallelism + clean retries but costs continuity, relative timing, transitions, motion coherence.

Don't give up parallelism. Cheapest recovery:

| # | Fix | Type | Leverage |
|---|---|---|---|
| 1 | **animation-map.mjs + contrast-report.mjs into validator** → typed error_log → existing repair loop | infra (bolt-on) | **highest** — visual QA on infra we already built |
| 2 | **Inter-scene transitions at compositor** — even 0.4s crossfade kills jump-cut tell | infra (master-doc layer) | high |
| 3 | **One motion signature + palette per job** (art-director node) injected into every scene prompt | orchestration | high (continuity) |
| 4 | **Pass neighbor context** (prior scene's last visual+palette+motion, 1-2 lines) into each scene prompt | prompt/orchestration | medium |
| 5 | **Port motion-principles** into `hf_rules.md` | prompt-only | free |
| 6 | **Visual-inspect feedback** — render keyframes, vision-model "broken/empty/cluttered?" → repair loop | infra (heavy) | do last |

Do #1 first — it's the *measurement-before-enforcement* gap, and it bolts onto the repair loop we already have.

Source scripts in clone: `design-templates/hyperframes/scripts/{animation-map,contrast-report}.mjs`,
transitions/motion refs: `design-templates/hyperframes/references/`, `transitions.md`, `visual-styles.md`.

> **Correction (verified against fresh clone, v0.6.112, 2026-06-18):** the §7 source
> paths above are stale. Real locations + contracts in §8.

---

## 8. Verdict — both analyses combined, best outcome

Two independent passes (the five-layer "what makes it perfect" read + the §1-7
head-to-head) ranked the **same top 4** — visual QA, transitions, identity,
motion-depth. Same conclusion from two angles = high confidence.

### The one insight neither pass stated outright

**The 5-retry repair loop is the multiplier, not a feature in the list.** We
already built the expensive half (multi-service harness, render, repair loop
feeding `error_log`). open-design has the cheap half we lack (scripts that
*measure rendered pixels* and emit structured failures). Everyone else who runs
those scripts reads the report by hand. We'd pipe it straight into regeneration
we already wrote → a **self-healing visual-correctness loop for ~one new file.**

So the work splits clean:
- **Floor** (correctness, automatic) = the measurement → repair loop. Tiny diff. First.
- **Ceiling** (taste/variety) = identity, transitions, motion. Bigger; the floor keeps them honest as added.

This is why **#1 must land before the ceiling work, not alongside it** — that
sequencing is the only thing the two analyses didn't already agree on, and it's
the whole point.

### Verified script contracts (replaces §7's stale paths)

| Script | Real path in clone | Invoke | Output | Gate signal |
|---|---|---|---|---|
| contrast | `skills/hyperframes-creative/scripts/contrast-report.mjs` | `node … <comp-dir> --out D` | `contrast-report.json` + overlay png | **exits 1** on any WCAG-AA fail |
| anim-map | `skills/hyperframes-animation/scripts/animation-map.mjs` | `node … <comp-dir> --out D` | `animation-map.json` | **always exit 0** → caller parses flags |

- Both need `@hyperframes/producer` (auto-bootstraps via `package-loader.mjs`) + a comp dir with `index.html`. We already ship HF in the compositor image.
- Apply to **HF HTML scenes** (GSAP timelines + text). **Manim MP4 scenes can't be measured this way** → that's Phase 4 (vision model).
- `animation-map` fail flags: `collision`/`offscreen`/`invisible`/`degenerate` (hard) + `deadZones ≥ ~1.5s` (soft). `paced-fast/slow` = warn only.
- Identity source verified: `skills/hyperframes-creative/references/visual-styles.md` = **8 styles** (Swiss Pulse, Velvet Standard, Deconstructed, Maximalist Type, Data Drift, Soft Signal, Folk Frequency, Shadow Cut) + a Mood→Style auto-pick map.

### Best-outcome sequence

| Phase | What | Maps to | Status |
|---|---|---|---|
| **0** | viz-QA keystone: both scripts in validator → JSON flags → `error_log` → existing repair loop | §7 #1 (sharpened) | not started |
| **1** | identity layer: pick 1 of 8 styles per job, bind palette+font+easing to every scene prompt + compositor chrome | §7 #3 | **intake half shipped — §9** |
| **2** | inter-scene transitions at compositor (TRANSITION-REGISTRY) | §7 #2 | not started |
| **3** | port motion-principles into `hf_rules.md` (prompt-only) | §7 #5 | not started |
| **4** | vision-model keyframe inspect — covers Manim MP4 too | §7 #6 | not started |

**Build Phase 0 first.** Smallest diff, highest leverage, reuses the repair
loop, matches the measurement-before-enforcement gap. Phases 1-3 become
self-correcting instead of hope-driven once 0 exists.

### Parallel track: Template-first generation (Track T)

A separate analysis (`nexu-html-video-comparison.md`, comparing `nexu-io/html-video`) adds a
**reliability/cost** track that interlocks with these visual-quality phases. Instead of LLM-authoring HTML
for every scene, common HyperFrames scenes render by filling a **vetted template**; novel scenes keep the
LLM path; Manim unchanged. It is not a competing roadmap — templates are where this roadmap's **identity
(Phase 1)** and **motion (Phase 3)** become concrete reusable assets, and a templated scene passes the
**Phase-0 viz-QA gate by construction** (authored + measured once, then frozen). Prevention complements cure.

| Phase | What | Depends on |
|---|---|---|
| **T0** | `ScenePlan.template_id/template_inputs` + code-gen template branch w/ LLM fallback + 1 template | — (parallel to Phase 0) |
| **T1** | Script-writer selects templates from an injected catalog | T0 |
| **T2** | Grow catalog to cover the common ~80% of scenes | T1 |
| **T3** | Templates carry the chosen style's identity + motion principles | Phases 1 + 3 |

Full task breakdown in `nexu-html-video-comparison.md` → "Implementation Plan — Template-First HyperFrames
Generation". Do **T0 first** (smallest diff proving the seam), in parallel with **Phase 0**.

---

## 9. Implementation log

### 2026-06-18 — Intake "great questions" (Phase-1 precursor: the identity gate's question half)

Problem: the analyze step asked **the same 3 static questions every topic**
(`duration`/`audience`/`focus`) — open-design's identity gate is "declare the
forks that matter, else ask 3 *good* Qs." Ours asked dumb repeated ones.

Shipped:
- **`services/script-writer/app/analyzer.py`** — rewrote `build_analyze_prompt`:
  killed the `EXACTLY duration/audience/focus` mandate. Now duration is fixed +
  first; model designs **2-3 topic-specific** questions against a 3-test rubric
  (decision-changing / not-inferable / one-tap) + good-axes menu + anti-patterns
  + one few-shot. **Reserved-id scheme**: `audience`/`focus`/`style`/`pacing`
  used only when genuinely the fork (→ typed brief fields); any other axis gets a
  free `snake_case` id. Temp `0.3 → 0.6` (low temp was half the repetition).
- **`services/script-writer/app/council.py`** — added `_answers_block()`,
  injected into **both** the single-writer (`_budget_block`) and `_planner`
  prompts. Without it, topic-specific answers landed in `brief["answers"]` and
  were **collected then ignored** (council read only the 4 typed fields) → great
  questions would've been decorative. Reserved ids skipped (already in the typed
  line) → no double-inject.

Bug caught + fixed during impl: frontend maps `visual_style` from
`pickAnswer("style")` — reserved id is **`style`**, not `visual_style`. Prompt
had said `visual_style` → a style question would miss the typed field *and* get
filtered from the answers block = **silently dropped**. Aligned prompt to `style`.

Verified: both files `py_compile`; `_answers_block` logic unit-checked
(reserved-skip / custom-text merge / empty→`""`); frontend
(`questionnaire.js:213`, `studio.js:1068`) pushes every answer into
`brief.answers[]` by `q.id` → adaptive ids reach council. Stateless — picks up
on next `/analyze`.

Verdict on this impl: **correct + complete for the intake piece.** NOT yet bound
to the style library — a `style` question's *options* are still generic; they
become the 8 named styles when **Phase 1** proper lands. Phases 0, 2, 3, 4 not
started.
