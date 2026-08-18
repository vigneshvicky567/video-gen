# Plan: Inject HyperFrames + Manim CE Skill Rules into Code-Generator Prompts

**Date:** 2026-05-05
**Goal:** Replace the existing terse, ad-hoc system prompts in `services/code-generator/app/main.py` with authoritative best-practice rules sourced from the official HyperFrames + Manim CE Skills repos. This is the root-cause fix for the blank-video output: the LLM was generating HTML/Manim that didn't follow the HyperFrames composition contract or Manim CE valid API set, so Puppeteer captured iframes that never animated and Manim emitted code with `NameError`s.

**Backend status:** NVIDIA NIM (Claude API was reverted at user request — Claude API expired). Models: `moonshotai/kimi-k2-instruct` (script + HF + compositor) and `qwen/qwen3-coder-480b-a35b-instruct` (Manim code). The skill rules feed *prompts*, not models — they work for any backend.

**Skill source paths (already cloned by user):**
- HyperFrames: `C:/Users/vicky/Desktop/samsung-lap-19-4/samsung-lap-19-4/video-gen/skill_files/hyperframes/skills/hyperframes/`
- Manim CE: `C:/Users/vicky/Desktop/samsung-lap-19-4/samsung-lap-19-4/video-gen/skill_files/manim_skill/skills/manimce-best-practices/`

**Scope (single project root):** `C:/Users/vicky/Desktop/samsung-lap-19-4/samsung-lap-19-4/video-gen/video-gen/manim-agent-network/`

---

## Phase 0 — Documentation Discovery (MANDATORY BEFORE ANY EDIT)

Deploy a single read-only subagent (or read inline) to extract concrete rules from the cloned skill files. **Do not summarize — copy the exact rule text where possible.** The subagent reports back with file:line citations.

### 0a. HyperFrames doc-discovery tasks

Read these files in full:

| Path | What to extract |
|---|---|
| `skills/hyperframes/SKILL.md` | Top-level authoring contract; what a composition is |
| `skills/hyperframes/patterns.md` | Required HTML structure, data-attributes, GSAP timeline registration pattern (`window.__timelines["scene-N"] = tl`), clip stacking rules |
| `skills/hyperframes/visual-styles.md` | Background/typography rules — addresses the "blank video" symptom |
| `skills/hyperframes/house-style.md` | Default style guard-rails |
| `skills/hyperframes/references/css-patterns.md` | Valid CSS patterns Puppeteer will capture |
| `skills/hyperframes/references/typography.md` | Font loading rules (CDN vs local) |
| `skills/hyperframes/references/captions.md` | Lower-third / caption HTML pattern |
| `skills/hyperframes/references/transitions.md` | Scene-to-scene transition primitives |
| `skills/gsap/SKILL.md` + `skills/gsap/references/` | GSAP timeline registration that lets HyperFrames seek frame-accurately (paused timeline, deterministic seeking) |

Output of phase 0a is a single file: `services/code-generator/app/prompts/hf_rules.md` containing:
- **Required HTML skeleton** (verbatim from `patterns.md`)
- **All data-attributes** with allowed values
- **GSAP registration pattern** (verbatim from `gsap/SKILL.md`)
- **Forbidden patterns** (anything `patterns.md` calls out as wrong)
- **Background/visibility checklist** (everything that prevents "blank frame")
- File:line citations for every rule

### 0b. Manim CE doc-discovery tasks

Read these files in full:

| Path | What to extract |
|---|---|
| `skills/manimce-best-practices/SKILL.md` | Scene class structure, when skill activates |
| `skills/manimce-best-practices/rules/scenes.md` | Scene class + `construct()` contract |
| `skills/manimce-best-practices/rules/animations.md` | Valid Animation classes (`Create` not `ShowCreation`) |
| `skills/manimce-best-practices/rules/creation-animations.md` | Valid creation animation API |
| `skills/manimce-best-practices/rules/text-animations.md` + `text.md` | `Text` / `Tex` / `MathTex` valid usage |
| `skills/manimce-best-practices/rules/colors.md` | Valid color constants (catch the `DARK_RED`/`DARK_BLUE` invalid-constant trap) |
| `skills/manimce-best-practices/rules/timing.md` | Valid `rate_func` names — directly fixes the scene-3 `NameError: ease_out_sine` bug from last run |
| `skills/manimce-best-practices/rules/transform-animations.md` | `.animate` patterns + forbidden kwargs |
| `skills/manimce-best-practices/rules/positioning.md` | `to_edge`, `next_to`, layout patterns |
| `skills/manimce-best-practices/rules/grouping.md` + `mobjects.md` | `VGroup`, `arrange`, `scale_to_fit_width` patterns |
| `skills/manimce-best-practices/rules/latex.md` | LaTeX-safe `Tex`/`MathTex` patterns |
| `skills/manimce-best-practices/examples/` | Copy-ready example scenes |

Output of phase 0b is a single file: `services/code-generator/app/prompts/manim_rules.md` containing:
- **Valid imports** (`from manim import *`)
- **Scene class skeleton**
- **Allowed animation classes** (whitelist)
- **Allowed `rate_func` names** (whitelist) — explicit fix for `ease_out_sine` failure
- **Allowed color constants** (whitelist + hex-fallback)
- **Forbidden APIs** (`ShowCreation`, `SVGMobject("…")`, `there_and_back_once`, `Circle(arc_length=…)`, `DARK_RED`, etc — already known from the existing prompt; cross-reference with skill rules to expand the list)
- **Layout patterns** (VGroup + arrange, scale_to_fit_width)
- File:line citations for every rule

### 0c. Subagent reporting contract

Each subagent must return:
1. List of files read with byte-counts
2. Exact rule snippets copy-pasted (with line refs)
3. Confidence note + known gaps
4. The output file path created

Reject any subagent report that paraphrases without citing.

---

## Phase 1 — Create Prompt-Rules Module

**Goal:** Have a single source of truth for HF + Manim rules that the code-generator can compose into system prompts.

### 1a. Create directory structure

```
services/code-generator/app/prompts/
├── __init__.py
├── hf_rules.md       (output of phase 0a)
├── manim_rules.md    (output of phase 0b)
└── loader.py
```

### 1b. Implement `loader.py`

```python
# services/code-generator/app/prompts/loader.py
from pathlib import Path
from functools import lru_cache

_PROMPTS_DIR = Path(__file__).parent

@lru_cache(maxsize=8)
def load(name: str) -> str:
    """Load a rules file by stem (e.g. 'hf_rules' or 'manim_rules')."""
    path = _PROMPTS_DIR / f"{name}.md"
    return path.read_text(encoding="utf-8")
```

Anti-pattern guards:
- Do NOT read the file inside the LLM call path (use `lru_cache`)
- Do NOT use f-strings to interpolate user content into the rule text (rules are static)

### 1c. Verification

- `python -c "from services.code_generator.app.prompts.loader import load; print(len(load('hf_rules')))"` returns >2000 chars
- `python -c "from services.code_generator.app.prompts.loader import load; print(len(load('manim_rules')))"` returns >2000 chars

---

## Phase 2 — Wire HyperFrames Rules into HF Prompt

**Goal:** Replace the terse `_HF_SYSTEM` constant + `_build_hf_prompt()` body with skill-sourced rules.

### 2a. Refs to copy from

- Existing code: `services/code-generator/app/main.py:70-123` (the `_HF_SYSTEM` and `_build_hf_prompt` functions)
- Rules source: `services/code-generator/app/prompts/hf_rules.md` (created in phase 0a)

### 2b. Implementation

In `services/code-generator/app/main.py`:

```python
from .prompts.loader import load as load_rules

_HF_SYSTEM = load_rules("hf_rules") + """

You are an expert HyperFrames HTML composer. Output ONLY a complete <!DOCTYPE html>...</html> document, no markdown fences. Follow every rule above without exception."""

def _build_hf_prompt(scene_id, narration, visual, duration):
    return f"""Create a HyperFrames HTML scene per the system rules.

Scene ID: {scene_id}
Total duration: {duration} seconds
Narration: {narration}
Visual: {visual}

REQUIRED root wrapper:
<div id="composition" data-composition-id="scene-{scene_id}" data-start="0" data-duration="{duration}" data-width="1920" data-height="1080">

REQUIRED GSAP registration:
const tl = gsap.timeline({{ paused: true }});
window.__timelines = window.__timelines || {{}};
window.__timelines["scene-{scene_id}"] = tl;

Output the complete HTML document only."""
```

### 2c. Anti-pattern guards

- Do NOT put style guidance like "WHITE background, BOLD title" in the user prompt — these belong in `hf_rules.md` and apply globally
- Do NOT keep both the old hardcoded `_HF_SYSTEM` and the new loader — replace, don't duplicate
- Do NOT inline the rules string into Python source — read from `.md` (so non-engineers can edit rules without touching code)

### 2d. Verification

- `grep "WHITE background" services/code-generator/app/main.py` returns 0 matches (style now lives in `hf_rules.md`)
- `grep "load_rules" services/code-generator/app/main.py` shows it being imported and called at module load
- Sanitizer self-test still passes: `python -c "from services.code-generator.app.main import _run_sanitizer_self_test; _run_sanitizer_self_test()"`

---

## Phase 3 — Wire Manim Rules into Manim Prompt

**Goal:** Same as phase 2, for Manim. Eliminates the `NameError: ease_out_sine` class of bugs by giving the LLM the authoritative whitelist.

### 3a. Refs to copy from

- Existing code: `services/code-generator/app/main.py:200-299` (the `_MANIM_SYSTEM` and `_build_manim_prompt` functions)
- Rules source: `services/code-generator/app/prompts/manim_rules.md` (from phase 0b)
- The valid `rate_func` whitelist must include only names that exist in `manim.utils.rate_functions` per `rules/timing.md`

### 3b. Implementation

```python
_MANIM_SYSTEM = load_rules("manim_rules") + """

Always respond with valid JSON containing the python_code key. The code must follow every rule above; the validator will reject code using forbidden APIs."""

def _build_manim_prompt(scene, error_log=None, previous_code=None):
    sid = scene.scene_id
    if error_log and previous_code:
        return f"""Fix this Manim scene per the system rules — it failed to render.

PREVIOUS CODE:
```python
{previous_code}
```

ERROR LOG:
{error_log}

Class name MUST be Scene{sid}. Return only: {{"python_code": "..."}}"""

    return f"""Create a Manim CE animation per the system rules.

SCENE DETAILS:
Narration: {scene.narration_text}
Visual: {scene.visual_description}
Scene #: {sid}

Class name MUST be Scene{sid} (subclass of Scene).
Background: config.background_color = WHITE; all strokes/text in dark colors.
No title text (HyperFrames adds title bar).

Return only: {{"python_code": "..."}}"""
```

### 3c. Anti-pattern guards

- Do NOT keep the long hardcoded "FORBIDDEN" list in the user-prompt — put it in `manim_rules.md` once and let the system prompt carry it
- Do NOT remove the existing post-LLM `sanitize_manim_code` step — it's a defense in depth (catches anything the LLM still gets wrong); the rules are first defense, sanitizer is second
- Do NOT add `temperature=0` to the qwen call — qwen3-coder is sampled at the existing 0.2; rule changes alone should fix most failures

### 3d. Verification

- After redeploy, run `POST /generate` with topic "vector calculus" (math-heavy, will exercise Manim path)
- `docker compose logs validator | grep "manim returncode=1"` — should drop from ~1/8 scenes to 0/8 in 3 consecutive runs
- `grep "ease_out_sine\|ShowCreation\|DARK_RED" workspace/temp/*/scene_*.py` returns 0 matches across runs

---

## Phase 4 — Compositor Background Fix (HF rendering blank issue)

**Goal:** Address the root cause of the blank-video output beyond the prompt fix. The compositor's master `index.html` (`services/compositor/app/llm_composer.py`) embeds each HyperFrames scene as `<iframe>` — Puppeteer's video capture in headless Chrome **does not always render iframe content into the parent canvas**. This is the *real* reason the user saw a blank video even though every scene HTML had `background:#ffffff`.

Two-track fix:

### 4a. (Quick) Force iframe capture

Update `services/compositor/app/llm_composer.py` to add `loading="eager"` and explicit width/height attributes on each iframe (some Puppeteer versions skip lazy iframes during screencast).

### 4b. (Better) Inline scene HTML instead of iframes

Refactor `compose_html()` to inline each HyperFrames scene's `<body>` content directly into `<div class="scene-host" data-start=… data-duration=…>` containers in the master composition, rather than as iframes. Manim scenes stay as `<video>` (those work).

This change is independent of skill-rules and can ship in either phase 4a or 4b — pick after 4a is tested. Defer 4b if 4a alone fixes the blank output.

### 4c. Verification

- After phase 4 redeploy, generate a video, open it: every scene's first frame should show the white HF background + title text, not black/empty
- `ffprobe -v error -show_streams workspace/outputs/<job>_final.mp4` shows non-empty video stream with correct duration

---

## Phase 5 — Verification & Regression Pass

**Goal:** Prove the prompt-rules + compositor changes work end-to-end.

### 5a. Rebuild + restart

```powershell
cd "C:\Users\vicky\Desktop\samsung-lap-19-4\samsung-lap-19-4\video-gen\video-gen\manim-agent-network"
docker compose down
docker compose up --build
```

(No `--no-cache` needed — only Python files changed; layer cache is fine since `requirements.txt` reverted.)

### 5b. Smoke tests (run all 3)

| Topic | Expected behavior |
|---|---|
| `"NLTK - Natural Language Processing with Python"` | Same prompt that produced the blank video. New run should produce visible HF backgrounds, no `NameError` retries. |
| `"How gradient descent finds minima"` | Math-heavy. Exercises Manim rules — should generate clean code with valid `rate_func`s. |
| `"What is a neural network"` | Diagram-heavy. Exercises HF rules — diagram nodes must be visible. |

### 5c. Greps for regression evidence

```sh
docker compose logs validator | grep -c "manim returncode=1"           # expect: 0 across 3 runs
docker compose logs code-generator | grep -c "is_retry=True"           # expect: 0 (no retry needed)
ls workspace/outputs/*_final.mp4                                       # expect: 3 new files >1MB each
```

### 5d. Visual check

Open each `*_final.mp4`. Pause at 0:01 and 0:30. Both frames must show non-black visible content.

---

## Anti-Patterns (apply to every phase)

- ❌ Do not invent rule text. Every rule in `hf_rules.md` / `manim_rules.md` must trace to a specific skill file path.
- ❌ Do not modify the script-writer prompt in this plan — its job is scene planning, not code authoring. Rule injection only applies to code-generator.
- ❌ Do not delete the existing `sanitizer.py` — keep as defense in depth.
- ❌ Do not switch LLM models or backends as part of this plan. NVIDIA NIM stays.
- ❌ Do not add `--no-cache` to docker rebuild — wastes ~15 min per iteration.
- ❌ Do not commit the `.env` file (already has a leaked `nvapi-…` key — separate cleanup needed).

---

## File Inventory

| Action | Path |
|---|---|
| Create | `services/code-generator/app/prompts/__init__.py` |
| Create | `services/code-generator/app/prompts/loader.py` |
| Create | `services/code-generator/app/prompts/hf_rules.md` |
| Create | `services/code-generator/app/prompts/manim_rules.md` |
| Modify | `services/code-generator/app/main.py` (replace `_HF_SYSTEM`, `_MANIM_SYSTEM`, prompt builders) |
| Modify | `services/compositor/app/llm_composer.py` (phase 4a iframe attrs; optional 4b inline) |
| Read-only | `services/code-generator/app/sanitizer.py` (keep, do not modify) |
| Read-only | `skill_files/hyperframes/skills/hyperframes/**` (sources) |
| Read-only | `skill_files/manim_skill/skills/manimce-best-practices/**` (sources) |

---

## Estimated Time

| Phase | Time | Confidence |
|---|---|---|
| 0a + 0b (doc discovery) | 30 min | High — files are local, well-organized |
| 1 (loader) | 10 min | High — trivial code |
| 2 (HF wire-in) | 20 min | High |
| 3 (Manim wire-in) | 20 min | High |
| 4a (iframe attrs) | 15 min | Medium — capture behavior depends on HyperFrames CLI version |
| 4b (inline scenes) | 60 min | Medium — refactor risk |
| 5 (verify, 3 runs × ~7 min) | 30 min | High |
| **Total** | ~3 hours | |

---

## Done Definition

1. ✅ All scenes render with visible backgrounds (no black frames)
2. ✅ 3 consecutive runs produce zero `manim returncode=1` errors
3. ✅ All rules in code-generator system prompts trace back to skill repo files via `hf_rules.md` / `manim_rules.md` citations
4. ✅ Existing test suite (`tests/`) passes
5. ✅ Final MP4s are >1MB and have non-empty video streams
