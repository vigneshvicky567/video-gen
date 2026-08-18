# nexu-io/html-video vs. Ours (manim-agent-network) — Competitive Analysis

> Cloned `nexu-io/html-video` @ `c67070b` (PR #29 merged) and read it deep against our `manim-agent-network`. This is what they are, where each wins, and exactly what to steal.

---

## 0. TL;DR

They and we are **different categories of thing** that happen to overlap on "HTML→video":

- **Theirs = a framework/SDK + product.** A clean TypeScript pnpm monorepo: engine-agnostic `EngineAdapter` layer, a content-graph IR, a CLI, a browser studio, 14 agent integrations, and **27 license-clean templates** with JSON-Schema inputs. Open-source, provenance-first, designer-accessible.
- **Ours = an autonomous generation pipeline.** A Python multi-agent microservice network (LangGraph orchestrator + 7 FastAPI services) that goes prompt → script → code → render → voiceover → composite → MP4, with self-healing retries, deterministic recovery, offline TTS, stock-image ranking, a security AST gate, and **two** render engines (Manim + HyperFrames).

**One-line verdict:** They are better *engineered as a reusable platform*; we are better *as an end-to-end autonomous product*. The single highest-leverage thing to steal is their **content-graph IR + template-with-JSON-schema model** — it would let common scenes skip per-scene LLM HTML generation entirely (faster, cheaper, deterministic, and it kills most of the reason our 5-retry repair loop exists).

Note: both projects orbit a third thing called **HyperFrames**. They wrote their *own* `adapter-hyperframes` (direct Chromium + Playwright `recordVideo` + ffmpeg trim). We shell out to the actual **`hyperframes` CLI** which does true frame-seek screenshot capture. On raw determinism of the HTML capture, **ours is arguably stricter** (seek-per-frame > record-then-trim). More on this in §4.

---

## 1. Architecture, side by side

| | **nexu-io/html-video** | **Ours (manim-agent-network)** |
|---|---|---|
| Category | Framework + SDK + studio (dev tool) | Autonomous pipeline (product/service) |
| Language | TypeScript 5.7 / Node 20 / pnpm monorepo | Python 3.10 / FastAPI / Docker Compose |
| Unit of work | `Project` → `ContentGraph` → frames → adapter render | `job` → LangGraph state → per-scene code → composite |
| Render engines | Pluggable via `EngineAdapter`: HyperFrames, Remotion (Motion Canvas/Revideo planned) | Manim CE **and** HyperFrames (per-scene), ffmpeg assembly |
| Authoring | Curated templates + agent fills JSON-schema inputs | LLM generates fresh HTML/Python per scene every time |
| Orchestration | Agent chat in studio; user-in-loop | Fully autonomous LangGraph DAG, no human needed |
| Persistence | In-memory bundle cache; project files on disk | SQLite WAL, full state after every node → resumable |
| Quality gate | Biome lint, strict TS, content-graph schema validation | AST security gate + `hyperframes lint` + HTML validator + retry |
| Audio | MiniMax API (paid, regional) | Kokoro ONNX offline + edge-tts fallback |
| Distribution | Open-source, Apache-2.0, provenance-tracked templates | Internal prototype, no license/marketplace, single-node |

---

## 2. What THEY do better (their pros / our gaps)

1. **Engine-agnostic adapter layer.** `EngineAdapter` is a minimal contract (`validate()` / `render()` / `preview()`). Templates, agent, and studio are all engine-blind; adding Remotion didn't touch templates. **We hardcode `if manim … else hyperframes …` branching everywhere** (script-writer sets `content_type`, code-gen branches, validator branches, compositor branches). Adding a third engine is a cross-service edit for us.

2. **Content-graph IR (RFC-06).** They generate *structure first*: `nodes` (entity/data/text) + `edges` (sequence/contrast/dependency), with `topoSort()` and `totalDurationSec()`. Same graph renders into any visual style without re-prompting the model; it's diffable, committable, and supports per-node re-render. **Our only intermediate is `ScenePlan`** (narration + visual_description + duration) — no semantic graph, no "restyle without regenerate", no per-node edit.

3. **Template + JSON-Schema inputs.** Each template ships `template.html-video.yaml` declaring `inputs.schema` (typed, constrained, with examples) + output spec (resolutions, fps, alpha, audio) + license + provenance. The agent fills a schema; the studio can auto-generate a form. **We LLM-generate bespoke HTML per scene every run** — flexible but slow, token-expensive, and the reason we need a 3–5x retry loop. For common scene types (stat reveal, bar chart, title card) a vetted template + schema is deterministic and ~free.

4. **Provenance + license discipline (RFC-07).** Three-layer attribution (`origin` → `via_skill` → `transformation`), root `ATTRIBUTIONS.md`, SPDX per template, commercial-use flags. Safe to ship publicly. **We have none of this** — fine for internal, blocking for any open release.

5. **Remotion native path.** `engine:remotion` templates are `.tsx` compositions animated on Remotion's frame-index clock — 100% deterministic, **no Chromium recording at all**, plus bundle caching (build once, reuse across N frames). For data-viz this is cleaner than screenshotting a browser.

6. **Render-engine micro-tricks worth lifting regardless** (`adapter-hyperframes/src/render.ts`):
   - **Freeze→font→unfreeze cycle:** inject `*{animation-play-state:paused}` via `addInitScript` *before* DOM parse → wait for stylesheets + `document.fonts.load()` each face + `fonts.ready` (8s hard cap) → start recording → `__hvUnfreeze()` in lockstep. Kills FOUT/font-swap flicker and guarantees frame-0 is the true opening frame.
   - **Blocking-resource neutralization:** rewrite external `<link rel=stylesheet>` to `media="print" onload="this.media='all'"` so headless Chromium never paints black waiting on Google Fonts.
   - **Explicit per-frame duration mode:** honor user cap as a hard ceiling, pad the tail with ffmpeg `tpad=stop_mode=clone` (we already freeze-pad — see §4 — but they separate `auto` vs `explicit` cleanly).

7. **Studio as a product surface.** Agent auto-detection (14 agents via PATH, Anthropic API fallback), source ingestion (article URL → markdown, GitHub repo → README+tree, even WeChat 公众号), content-graph viewer, frames strip, restyle/edit state machine. **Our studio is a vanilla-JS submit-and-poll panel** — no chat, no source ingestion, no graph editing.

8. **Quality bar / tooling.** Biome, strict TS (`noUncheckedIndexedAccess`, `isolatedModules`), declaration maps, smoke test, RFC-driven design notes in `notes/` and `research/`. Disciplined.

---

## 3. What WE do better (our pros / their gaps)

1. **Fully autonomous.** Prompt in, finished narrated MP4 out, zero human in the loop. Theirs is fundamentally **agent-chat in a studio** — a human drives it. This is our core moat.

2. **Self-healing generation.** Validation failure (AST / lint / render) feeds the error log + previous code back into the code-gen prompt, capped at 5 retries; unrenderable scenes are dropped and the job survives. **Their content-graph validation is strict and one-shot** — reject cycles/orphans immediately, no repair path.

3. **Deterministic recovery.** Full `LangGraphState` persisted to SQLite WAL after every node; orchestrator restart fast-forwards to the first unfinished scene. **Their bundle cache is in-process memory only** — lost on restart, no job resumption.

4. **Two real engines including Manim.** We do genuine mathematical animation (Manim CE) *and* motion graphics (HyperFrames), classified per scene. **They are HTML/Remotion only** — no math-render story.

5. **Offline, free TTS.** Kokoro ONNX (int8, on-device) primary, edge-tts fallback, with text-cleaning to avoid phonemizer crashes. **They depend on MiniMax** (paid, regional, network-required).

6. **Stock-image relevance ranking.** Pexels→Pixabay→Wikimedia fetch, then **SigLIP ONNX image-text scoring** (+ optional vision-LLM vetting). Theirs fetches sources but shows no relevance ranking.

7. **Security AST gate.** Generated Python is parsed and blocked on `import/exec/eval/open/getattr/...` before any render. They never execute untrusted code, so they don't need it — but it means we can safely run model-authored code, which is a harder problem solved.

8. **Long-form machinery.** Adaptive script council (single writer→reviewer for short, curriculum-planner→parallel-section-writers→merge for long), duration-budget enforcement (±10% via word-rate model), caption-window allocation that chains in 3-decimal space with zero same-track overlap, freeze-pad to narration end, and chunked rendering (>480s splits into ≤4-scene / ≤300s chunks, ffmpeg-concat). They have none of this — duration is just `sum(node.durationSec)`.

9. **Frame-seek determinism on HTML.** Our HyperFrames path uses the `hyperframes` CLI which **seeks the paused GSAP timeline to exact frame times and screenshots each** — stricter than their `recordVideo`-then-trim. See §4.

---

## 4. The HTML render engine — the nuance that matters

The user's recurring question is "what makes their HTML video part perfect." Honest read:

- **Their `adapter-hyperframes`** records *real-time playback* via Playwright `recordVideo`, then `ffmpeg -ss <freeze-lead-in> -t <dur>` trims and `tpad`-pads. Determinism comes from the freeze/font orchestration around the recording, **not** from frame-exact seeking. Risk: `recordVideo` jitter (they trim to compensate), wall-clock coupling, no ability to render frames 100–150 in isolation or parallelize on a farm.
- **Our path** delegates to the `hyperframes` CLI, whose contract (per our skill `references/motion-principles.md`) is a `gsap.timeline({paused:true})` registered on `window.__timelines["<id>"]` that the renderer **seeks to microsecond positions and screenshots per frame**. No wall-clock coupling.

**So the "crown jewel" is split:** their *setup tricks* (freeze, font-wait, blocking-resource neutralization, explicit duration mode) are genuinely better and worth stealing; their *core capture* (record-then-trim) is arguably weaker than the seek-per-frame capture we already get from the `hyperframes` CLI. Don't blindly copy their capture loop — copy the pre-roll hygiene around it.

Where we're weaker on the engine: **`repeat:-1` is banned** for us (breaks frame-seek) so ambient loops need manual repeat-count math; our `hyperframes lint` is **permissive on tool failure** (returns `ok:true` if the linter crashes → bad HTML can ship); and we have **no time-window/progressive render** (whole timeline in one pass, no farm parallelism).

---

## 5. STEAL LIST — ranked by leverage

| # | Steal this | From | Effort | Payoff |
|---|---|---|---|---|
| 1 | **Content-graph IR** between script-writer and code-gen (nodes+edges, topo-sort, per-node duration). Decouples "what to say" from "how to render"; enables restyle-without-regenerate and per-node re-render. | `packages/content-graph` | M | **Huge** — structural foundation for everything below |
| 2 | **Template + JSON-Schema inputs** for common scene types. Fill a vetted template instead of LLM-authoring HTML every run. Cuts cost/latency and removes most retry-loop pressure. | `templates/*/template.html-video.yaml` | M–L | **Huge** — faster, cheaper, deterministic, fewer failures |
| 3 | **Pre-roll render hygiene:** freeze-all-animations → font-load(8s cap) → unfreeze-in-lockstep; `media="print"` link neutralization. Eliminates font-swap flicker / black frames. | `adapter-hyperframes/src/render.ts` | S | High — quality bug class gone |
| 4 | **`EngineAdapter` abstraction** to replace our hardcoded engine branching. Makes Manim/HyperFrames/(future Remotion) pluggable. | `packages/core` + adapters | M | High — kills cross-service `if engine` sprawl |
| 5 | **Provenance + SPDX metadata** on any template/asset we curate. Mandatory before any open-source release. | RFC-07, `ATTRIBUTIONS.md` | S | High if we ever ship publicly |
| 6 | **Remotion native path** for data-viz (frame-bound, no Chromium, bundle-cached). Alternative deterministic backend for charts. | `adapter-remotion`, `frame-data-rollup` | L | Medium — strong for data scenes |
| 7 | **Studio upgrades:** source ingestion (URL→markdown, repo→README), content-graph viewer, restyle/edit flow. | `cli/src/studio-server.ts`, `project-studio` | L | Medium — product polish |
| 8 | **Explicit vs auto duration mode** naming + `tpad clone` tail (we already freeze-pad; adopt their clean split). | `adapter-hyperframes` | S | Low–Medium — clarity |

**Do NOT bother stealing:** their 27 templates wholesale (license/style-specific to them), MiniMax audio (we have better/free TTS), their `recordVideo` capture loop (ours is stricter), their in-memory-only caching.

---

## 6. The one strategic reframe

Our pipeline's biggest cost and failure source is **"LLM authors a fresh HTML document for every scene, then we lint-and-retry until it renders."** That is an open author-then-pray loop (already flagged in the hyperframes-SOTA memory). Nexu sidesteps it entirely: **author the structure once (content graph), then render by filling a measured, vetted template.** Adopting #1 + #2 from the steal list turns our most expensive, most failure-prone stage into a fast deterministic fill for the common cases, and reserves bespoke LLM HTML only for genuinely novel scenes — keeping the self-healing loop (our advantage) as the fallback, not the default path.

---

## Appendix — key files

**Theirs (cloned):** `packages/core/src/types`, `packages/content-graph/src/index.ts`, `packages/adapter-hyperframes/src/render.ts`, `packages/adapter-remotion/src/render.ts`, `packages/cli/src/{bin,studio-server}.ts`, `templates/frame-data-chart-nyt/template.html-video.yaml`, `CLAUDE.md`, `notes/`, `research/` (RFC-01..08).

**Ours:** `services/orchestrator/app/core/graph.py`, `services/code-generator/app/main.py` (+`prompts/hf_rules.md`), `services/compositor/app/{main,duration_prober,llm_composer,html_validator}.py`, `services/validator/app/main.py`, `shared/schemas/{common,requests,responses}.py`, `.agents/skills/hyperframes/`.

---

# Implementation Plan — Template-First HyperFrames Generation (Option B)

> Decision (2026-06-19): adopt **template-first + LLM fallback** (steal #2 from §5). Common HyperFrames
> scenes render by filling a vetted template; novel scenes keep the current LLM-authors-HTML path; Manim
> stays LLM-only. This plan slots beside the visual-QA roadmap in `open-design-hyperframes-analysis.md` §8.

## How this fits the existing roadmap (not a competing track)

The open-design roadmap (Phases 0–4) is about **visual quality** — measure rendered pixels, enforce
identity/transitions/motion. This template track is about **generation reliability + cost** — stop
LLM-authoring HTML for every common scene. They reinforce each other:

- A template is **authored once and measured once** (run it through the Phase-0 viz-QA gate during
  authoring). After that it renders deterministically and **cannot regress** — so templated scenes pass
  viz-QA by construction. **Prevention** (templates) complements **cure** (the repair loop + viz-QA gate).
- A template is the concrete home for **identity (Phase 1)** and **motion principles (Phase 3)**: palette,
  font pairing, easing signature, build/breathe/resolve timing are baked into the template's HTML/GSAP
  instead of hoped for in a prompt. Building templates *is* how Phases 1 + 3 stop being prompt text.
- The LLM-fallback path (novel scenes) and the Manim path still need viz-QA — so **Phase 0 stays the
  first visual-quality investment**; templates handle the common path in parallel.

**Net effect on our biggest cost:** today every scene = one LLM HTML generation + a 3–5× lint/retry loop.
After this, common scenes = a deterministic template fill (≈0 tokens, can't fail render). The repair loop
becomes the rare fallback, not the default for every scene.

## Design (ponytail — smallest thing that works)

- **A template = one Python module** in `services/code-generator/app/templates/` exposing:
  - a Pydantic input model (validation, no new dependency — reuses our stack), and
  - `render(inputs, *, scene_id, duration, image_paths) -> str` returning a complete
    `<!DOCTYPE html>…</html>` HyperFrames doc (same contract `_generate_hyperframes` writes today:
    `data-composition-id="scene-{id}"`, paused timeline on `window.__timelines["scene-{id}"]`,
    `.scene-content` layout, caption safe-zone). The HTML lives as an f-string in the module.
  - `ponytail:` v1 keeps render code as Python f-strings. Upgrade path when a designer joins or the catalog
    grows past ~10: split into `template.html` + `manifest.json` data files (the nexu shape). Don't build
    the file-loader until the catalog earns it.
- **Output is byte-identical in shape to the LLM path** → validator, `hyperframes lint`, compositor,
  captions, timing all unchanged. Zero blast radius downstream.
- **Selection lives in the script-writer**, not a new service: it already decides `content_type`; it now
  also picks `template_id` + `template_inputs` when a scene cleanly fits a catalog entry, else leaves them
  null. No new graph node, no new container.

## Tasks

- [ ] **T0 — End-to-end slice with one template (proves the seam)**
  - [ ] T0.1 `shared/schemas/common.py` — add two optional fields to `ScenePlan`:
    `template_id: Optional[str] = None`, `template_inputs: Optional[Dict[str, Any]] = None`.
    Optional → fully backward-compatible; existing scripts/jobs deserialize unchanged.
  - [ ] T0.2 New `services/code-generator/app/templates/__init__.py` — a `REGISTRY: dict[str, Template]`
    plus `get(template_id) -> Template | None`. A `Template` bundles the input model + `render`.
  - [ ] T0.3 First template `services/code-generator/app/templates/title_card.py` — title + subtitle +
    optional bg image. Bake the §6 identity baseline (palette/font/motion) straight into its HTML/GSAP.
  - [ ] T0.4 `services/code-generator/app/main.py` `generate_code()` — **before** the manim/hf branch:
    if `content_type == "hyperframes"` and `scene.template_id` resolves in `REGISTRY` and
    `template_inputs` validate against the model → `render()` → write `scene_{id}.html` → return.
    On any miss (unknown id, validation error) **fall through to `_generate_hyperframes` (LLM)** — never
    hard-fail. Log which path ran (`gen_path=template|llm`) for metrics.
  - [ ] T0.5 Test `tests/test_templates.py` — title_card renders, output parses, carries the required
    root attrs + `window.__timelines["scene-{id}"]`, and `generate_code` falls back to LLM on bad inputs.
  - _Checkpoint: a scene with `template_id="title_card"` renders with zero LLM call; everything else
    unchanged. This is the whole bet in miniature._

- [ ] **T1 — Teach the script-writer to select templates**
  - [ ] T1.1 Build a compact machine catalog (id · one-line use · input fields) from `REGISTRY`; inject it
    into the script-writer prompts (`council.py` single-writer + planner blocks).
  - [ ] T1.2 Instruct the model: for a scene that cleanly fits a catalog entry, set `content_type:
    "hyperframes"`, `template_id`, and `template_inputs`; otherwise leave `template_id` null (→ LLM path).
    Few-shot one templated + one free-form scene.
  - [ ] T1.3 Guard in script-writer: if `template_id` set but not in the catalog, drop it (null) before
    returning — selection errors degrade to the LLM path, never to a broken job.

- [ ] **T2 — Grow the catalog to cover the common ~80%**
  - [ ] Add templates: `stat_reveal`, `bullet_list`, `quote`, `bar_chart`, `comparison`, `logo_outro`.
        Each authored once, run through the Phase-0 viz-QA gate at authoring time, then frozen.
  - [ ] Track `gen_path` ratio in logs — target: majority of HyperFrames scenes on templates.

- [ ] **T3 — Fold identity + motion into templates (closes the loop with the roadmap)**
  - [ ] When Phase 1 (identity / 8 styles) lands, parameterize each template by the chosen style's palette
        + font + easing signature so a job's look flows through every templated scene for free.
  - [ ] Port the Phase-3 motion principles (build/breathe/resolve, easing=emotion, stagger<500ms) into the
        templates' GSAP — making templated scenes motion-correct by construction.

## Impact summary

| | Before | After (common scenes) |
|---|---|---|
| LLM calls / common scene | 1 + retries | 0 |
| Render failure rate | nonzero (fragile HTML) | ~0 (pre-tested template) |
| Visual consistency | drifts per generation | identical every render |
| Identity / motion (Phases 1, 3) | prompt hope | baked into template |
| Repair loop role | default path | rare fallback (novel scenes only) |

Preserved: full autonomy, self-healing retry (now a fallback), Manim path, all downstream services.
Risk: catalog gaps → those scenes silently take the (working) LLM path. Acceptable by design.

## Roadmap placement

Build order: **T0 → T1 → T2**, runnable in parallel with open-design **Phase 0** (viz-QA gate). T0 is the
smallest diff that proves the template seam; do it first. **T3** depends on Phases 1 + 3 and merges the two
tracks. See `open-design-hyperframes-analysis.md` §8 for the visual-quality phases this interlocks with.
