from fastapi import FastAPI
from shared.schemas.requests import CodeGeneratorRequest
from shared.schemas.responses import CodeGeneratorResponse
from shared.config import settings
from shared.llm_client import get_llm_client
from shared.log import get_logger, set_log_context, timed_block, log_llm_call, log_file, make_request_logging_middleware
import os
import sys
from .sanitizer import sanitize_manim_code
from .prompts import load as load_rules
import re
import json
import uuid
import time


def _sampling_temperature(path_default: float) -> float:
    """CODE_GENERATOR_TEMPERATURE env override, else the per-path default.

    Reasoning models (nvidia/nemotron-3-*) need temperature 1.0; coder models
    work best at low temperature. Env-driven so a model swap in .env can carry
    its sampling params without a code change.
    """
    raw = settings.CODE_GENERATOR_TEMPERATURE.strip()
    return float(raw) if raw else path_default


def _sampling_top_p() -> float | None:
    raw = settings.CODE_GENERATOR_TOP_P.strip()
    return float(raw) if raw else None


def _run_sanitizer_self_test() -> None:
    """Fail-fast on stale image: confirm sanitizer rewrites ShowCreation."""
    sample = (
        "from manim import *\n"
        "class S(Scene):\n"
        "    def construct(self):\n"
        "        self.play(ShowCreation(Circle()))\n"
    )
    out, _ = sanitize_manim_code(sample, scene_id=0)
    if "ShowCreation" in out or "Create" not in out:
        # Logger may not exist yet at this import-time; print + exit.
        print("STALE IMAGE: sanitizer self-test failed (ShowCreation not rewritten)", file=sys.stderr)
        sys.exit(1)

app = FastAPI(title="Code Generator Service")
app.add_middleware(make_request_logging_middleware("code-generator"))
logger = get_logger(__name__)

_tracer = None
if os.getenv("LANGSMITH_API_KEY"):
    try:
        import langsmith
        langsmith_client = langsmith.Client()
        _tracer = langsmith_client
        logger.info("LangSmith tracing enabled")
    except ImportError:
        logger.warning("langsmith not installed, tracing disabled")

_run_sanitizer_self_test()

client = get_llm_client()
logger.info("Code Generator ready", extra={"model": settings.CODE_GENERATOR_MODEL})
logger.info("Sanitizer self-test passed")


# ─────────────────────────────────────────────────────────────────────────────
# Scene classification (fallback when script-writer doesn't set content_type)
# ─────────────────────────────────────────────────────────────────────────────
MANIM_KEYWORDS = [
    "equation", "formula", "graph", "plot", "curve", "axes", "matrix",
    "vector", "geometry", "proof", "derivative", "integral", "transform",
    "animate", "draw", "manim", "mathematical", "3d surface", "eigenvalue",
]

def classify_scene(narration: str, visual: str) -> str:
    """Return 'manim' only when the scene genuinely needs math animation."""
    combined = f"{narration} {visual}".lower()
    hits = sum(1 for kw in MANIM_KEYWORDS if kw in combined)
    return "manim" if hits >= 2 else "hyperframes"


# ─────────────────────────────────────────────────────────────────────────────
# HyperFrames HTML generation via LLM
# ─────────────────────────────────────────────────────────────────────────────
# System prompt is the official HyperFrames skill rules + a thin task wrapper.
# Rule edits live in services/code-generator/app/prompts/hf_rules.md, not here.
_HF_SYSTEM = load_rules("hf_rules") + """

---

# Your Task

You are an expert HyperFrames HTML composer building educational-explainer scenes.
Output ONLY a complete <!DOCTYPE html> … </html> document — no markdown fences,
no commentary. Follow every rule above without exception. The composition
will be inlined into a master 1920x1080 canvas, so the rendered scene MUST
have a visible non-transparent background and visible foreground content.

Visual baseline (override with explicit user-supplied palette when given):
- Canvas: 1920×1080.
- LAYOUT: every scene's content lives in a `.scene-content` container sized
  `width:100%; height:100%; padding:80px 120px 160px; display:flex; flex-direction:column;
  gap:32px; box-sizing:border-box`. The bottom 160px is the composition caption
  band — keep content out of it. Position content with padding/flex — NEVER
  `position:absolute; top:Npx` on a content container (it overflows). Reserve
  `position:absolute` for decoratives only. Build the static end-state layout
  first, THEN add gsap.from() entrances.
- BACKGROUND: NOT flat pure white. Use a tinted near-neutral (e.g. #f4f1ea warm
  or #0e1116 dark) plus ONE depth layer (soft radial glow or subtle grain) and
  ONE accent hue used at full saturation on the focal element. Pure #ffffff/#000
  reads as "nothing loaded". Keep ONE palette across ALL scenes.
- TYPOGRAPHY (video scale, not web): headlines 64-110px, body 28-42px, labels
  18-24px. Pair a serif with a sans (NOT two sans). Extreme weight contrast
  (300 vs 900). Do NOT use Inter, Roboto, Poppins, Open Sans, Lato, Nunito —
  they are instant AI-design tells. Prefer system serif ("Georgia","Times New
  Roman",serif) paired with a system sans, or a bundled .woff2. Tabular-nums on
  stacked numbers. Let text wrap via max-width — never <br>.
- MOTION: stagger multi-element reveals (`stagger:{each:0.08, from:"center"}`),
  set one motion signature via `gsap.timeline({defaults:{ease:"power3.out",
  duration:0.6}})`, vary eases (≥3/scene), use autoAlpha not opacity. Entrance
  animations only — NO exit animations except the final scene.
- CONTRAST: on-screen text must hit WCAG 4.5:1 against whatever is behind it.
- GSAP CDN (exact URL — the compositor dedupes it against the master doc):
  https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"""

def _build_hf_prompt(scene_id: int, narration: str, visual: str, duration: int,
                     error_log: str = None, previous_html: str = None) -> str:
    """User-prompt body. Style + structure rules come from the system prompt
    (hf_rules.md). This message only carries scene-specific values + the two
    template strings the LLM must emit verbatim with the right scene_id."""
    contract = f"""REQUIRED root wrapper (copy literally — the HyperFrames compiler mounts the
scene by this exact data-composition-id, then drops the wrapper):
  <div id="composition"
       data-composition-id="scene-{scene_id}"
       data-start="0"
       data-duration="{duration}"
       data-width="1920"
       data-height="1080"
       style="position:relative;width:1920px;height:1080px;overflow:hidden;">

REQUIRED GSAP registration block (paste literally with the right scene_id —
the runtime auto-nests the timeline ONLY when this key equals the
data-composition-id above):
  const tl = gsap.timeline({{ paused: true }});
  window.__timelines = window.__timelines || {{}};
  window.__timelines["scene-{scene_id}"] = tl;
  // then add tl.from(...) / tl.to(...) calls for each animated element

Both `body` and the `#composition` div MUST have an explicit non-transparent
background-color following the system palette baseline (tinted near-neutral,
NOT pure #ffffff/#000000) so the rendered frame is visible.

Do NOT include a lower-third caption — narration is audio-only.
Do NOT use @font-face — use system font stacks per the system typography rules.
Do NOT load external scripts other than the GSAP CDN.

Output ONLY the complete <!DOCTYPE html>...</html> document."""

    if error_log and previous_html:
        return f"""Fix this HyperFrames scene per the system rules — it failed validation.

Scene ID: {scene_id}
Total duration: {duration} seconds
Narration (spoken, NOT on-screen): {narration}
Visual description: {visual}

PREVIOUS HTML:
```html
{previous_html[:6000]}
```

VALIDATION ERROR:
{error_log[-600:]}

Fix the error while keeping the scene's content and design intent.

{contract}"""

    return f"""Create a HyperFrames HTML scene per the system rules.

Scene ID: {scene_id}
Total duration: {duration} seconds
Narration (spoken, NOT on-screen): {narration}
Visual description: {visual}

{contract}"""


def _extract_html(text: str) -> str:
    """Pull the HTML document out of an LLM response."""
    # Strip markdown fences if present
    text = re.sub(r"```html\s*", "", text)
    text = re.sub(r"```\s*$", "", text, flags=re.MULTILINE)
    m = re.search(r"<!DOCTYPE\s+html.*</html>", text, re.IGNORECASE | re.DOTALL)
    if m:
        return m.group(0)
    m = re.search(r"<html.*</html>", text, re.IGNORECASE | re.DOTALL)
    return m.group(0) if m else text.strip()


async def _generate_hyperframes(request, run_id: str, start_time: float):
    scene    = request.scene
    scene_id = scene.scene_id
    set_log_context(scene_id=scene_id)
    is_retry = bool(request.error_log and request.previous_code)
    logger.info("Generating HyperFrames HTML", extra={"scene_id": scene_id, "is_retry": is_retry})

    prompt = _build_hf_prompt(
        scene_id      = scene_id,
        narration     = scene.narration_text,
        visual        = scene.visual_description,
        duration      = scene.estimated_duration_seconds,
        error_log     = request.error_log,
        previous_html = request.previous_code,
    )

    last_error = None
    for attempt in range(3):
        try:
            t0 = time.time()
            resp = await client.chat.completions.acreate(
                model    = settings.CODE_GENERATOR_MODEL,
                messages = [
                    {"role": "system", "content": _HF_SYSTEM},
                    {"role": "user",   "content": prompt},
                ],
                temperature = _sampling_temperature(0.6),
                top_p       = _sampling_top_p(),
                max_tokens  = settings.CODE_GENERATOR_MAX_TOKENS,
            )
            elapsed = time.time() - t0
            html = _extract_html(resp.choices[0].message.content)
            if not html:
                raise ValueError("LLM returned empty HTML")

            log_llm_call(logger, settings.CODE_GENERATOR_MODEL,
                         prompt_chars=len(prompt),
                         response_chars=len(resp.choices[0].message.content),
                         elapsed_s=elapsed, attempt=attempt + 1,
                         scene_id=scene_id, content_type="hyperframes")

            temp_dir  = os.path.join(settings.WORKSPACE_DIR, "temp", request.job_id)
            os.makedirs(temp_dir, exist_ok=True)
            file_path = os.path.join(temp_dir, f"scene_{scene_id}.html")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(html)
            log_file(logger, "written", file_path, scene_id=scene_id, content_type="hyperframes")

            total = time.time() - start_time
            if _tracer:
                try:
                    _tracer.update_run(run_id=run_id,
                        outputs={"code_path": file_path, "content_type": "hyperframes"},
                        end_time=time.time(), metrics={"total_latency": total})
                except Exception as _trace_exc:
                    logger.debug(f"LangSmith trace failed: {_trace_exc}")

            logger.info("HyperFrames HTML saved", extra={"scene_id": scene_id, "path": file_path})
            return CodeGeneratorResponse(scene_id=scene_id, code_path=file_path)

        except Exception as e:
            last_error = e
            logger.warning("HyperFrames attempt failed", extra={"attempt": attempt + 1, "error": str(e)})

    raise RuntimeError(f"HyperFrames generation failed after 3 attempts: {last_error}")


# ─────────────────────────────────────────────────────────────────────────────
# Manim Python code generation via LLM
# ─────────────────────────────────────────────────────────────────────────────
# System prompt is the official Manim CE skill rules + a thin task wrapper.
# Rule edits live in services/code-generator/app/prompts/manim_rules.md.
_MANIM_SYSTEM = load_rules("manim_rules") + """

---

# Your Task

You are an expert Manim Community Edition animator. Always respond with valid
JSON containing a single `python_code` key whose value is the complete scene
file. Follow every rule above without exception — the validator runs the code
through `manim render` and a forbidden-API sanitizer; both will reject
violations.

Pipeline-specific contract:
- Background MUST be set at the top of `construct()` with
  `config.background_color = WHITE`. The white canvas is provided by the
  HyperFrames composition layer; never render white text/strokes on it.
- Use rich dark colors for math: axes `"#1a1a2e"`, curves `"#e63946"` or
  `"#2196f3"`, dots `"#ff9800"`.
- The class name MUST be exactly `Scene{N}` (one integer the caller fills in).
- No external asset loads, no `SVGMobject("...")`, no web calls."""


_MANIM_FEW_SHOT = (
    '{"python_code": "from manim import *\\n\\nclass Scene1(Scene):\\n'
    '    def construct(self):\\n'
    '        config.background_color = WHITE\\n'
    '        axes = Axes(x_range=[-3,3], y_range=[0,9], x_length=8, y_length=5,'
    ' axis_config={\\\"color\\\": \\\"#1a1a2e\\\", \\\"stroke_width\\\": 3})'
    '.move_to(DOWN*0.3)\\n'
    '        labels = axes.get_axis_labels(x_label=\\\"x\\\", y_label=\\\"y\\\")'
    '.set_color(BLACK)\\n'
    '        curve = axes.plot(lambda x: x**2, color=\\\"#e63946\\\", stroke_width=4)\\n'
    '        self.play(Create(axes), Write(labels))\\n'
    '        self.play(Create(curve), run_time=2)\\n'
    '        dot = Dot(axes.c2p(-2, 4), color=\\\"#ff9800\\\", radius=0.12)\\n'
    '        self.play(FadeIn(dot))\\n'
    '        self.play(MoveAlongPath(dot, curve), run_time=2, rate_func=there_and_back)\\n'
    '        self.wait(1)\\n"}'
)


def _build_manim_prompt(scene: object, error_log: str = None, previous_code: str = None) -> str:
    """User-prompt body. Style + forbidden-API rules come from the system
    prompt (manim_rules.md). This message only carries scene-specific values
    and a class-name reminder."""
    sid = scene.scene_id

    if error_log and previous_code:
        return f"""Fix this Manim CE scene per the system rules — it failed to render.

PREVIOUS CODE:
```python
{previous_code}
```

ERROR LOG (last 600 chars):
{error_log[-600:]}

Class name MUST stay `Scene{sid}`. The error often comes from one of the
forbidden APIs in the system rules — re-check those first.

Return ONLY: {{"python_code": "..."}}"""

    return f"""Create a Manim CE scene per the system rules.

SCENE DETAILS:
Scene #:    {sid}
Narration:  {scene.narration_text}
Visual:     {scene.visual_description}

Class name MUST be exactly `Scene{sid}` (subclass of `Scene`).
No on-screen title text (the HyperFrames layer adds the scene title).
First line of `construct()`: `config.background_color = WHITE`.

FEW-SHOT EXAMPLE (valid output for a different scene):
```json
{_MANIM_FEW_SHOT}
```

Return ONLY: {{"python_code": "..."}}"""


async def _generate_manim(request, run_id: str, start_time: float):
    scene    = request.scene
    scene_id = scene.scene_id
    set_log_context(scene_id=scene_id)
    is_retry = bool(request.error_log and request.previous_code)
    logger.info("Generating Manim code", extra={"scene_id": scene_id, "is_retry": is_retry})

    prompt = _build_manim_prompt(scene, request.error_log, request.previous_code)

    try:
        llm_start = time.time()
        response  = await client.chat.completions.acreate(
            model    = settings.CODE_GENERATOR_MODEL,
            messages = [
                {"role": "system", "content": _MANIM_SYSTEM},
                {"role": "user",   "content": prompt},
            ],
            temperature     = _sampling_temperature(0.2),
            top_p           = _sampling_top_p(),
            max_tokens      = settings.CODE_GENERATOR_MAX_TOKENS,
            response_format = {"type": "json_object"},
        )
        llm_dur = time.time() - llm_start
        log_llm_call(logger, settings.CODE_GENERATOR_MODEL,
                     prompt_chars=len(prompt),
                     response_chars=len(response.choices[0].message.content),
                     elapsed_s=llm_dur, scene_id=scene_id, content_type="manim")

        code_data = json.loads(response.choices[0].message.content)
        code      = code_data.get("python_code", "")

        # Sanitize generated code to replace deprecated/forbidden Manim APIs
        try:
            sanitized_code, sanitize_warnings = sanitize_manim_code(code, scene_id=scene_id)
        except Exception as s_e:
            logger.warning("Sanitizer failed, using original code", extra={"scene_id": scene_id, "error": str(s_e)})
            sanitized_code = code
            sanitize_warnings = []

        if sanitize_warnings:
            for w in sanitize_warnings:
                logger.warning(f"Sanitizer: {w}", extra={"scene_id": scene_id})

        temp_dir  = os.path.join(settings.WORKSPACE_DIR, "temp", request.job_id)
        os.makedirs(temp_dir, exist_ok=True)
        file_path = os.path.join(temp_dir, f"scene_{scene_id}.py")
        # Write sanitized code when available
        code_to_write = sanitized_code if sanitized_code else code
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(code_to_write)
        log_file(logger, "written", file_path, scene_id=scene_id, content_type="manim")

        total = time.time() - start_time
        if _tracer:
            try:
                _tracer.update_run(run_id=run_id,
                    outputs={"code_path": file_path, "code_length": len(code_to_write)},
                    end_time=time.time(), metrics={"total_latency": total})
            except Exception as _trace_exc:
                logger.debug(f"LangSmith trace failed: {_trace_exc}")

        logger.info("Manim code saved", extra={"scene_id": scene_id, "path": file_path, "code_lines": code.count(chr(10))})
        return CodeGeneratorResponse(scene_id=scene_id, code_path=file_path)

    except Exception as e:
        total = time.time() - start_time
        if _tracer:
            try:
                _tracer.update_run(run_id=run_id, error=str(e),
                    end_time=time.time(), metrics={"total_latency": total})
            except Exception as _trace_exc:
                logger.debug(f"LangSmith trace failed: {_trace_exc}")
        logger.error("Manim generation error", extra={"scene_id": scene_id}, exc_info=True)
        raise e


# ─────────────────────────────────────────────────────────────────────────────
# Main endpoint
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/generate", response_model=CodeGeneratorResponse)
async def generate_code(request: CodeGeneratorRequest):
    scene    = request.scene
    scene_id = scene.scene_id
    set_log_context(job_id=request.job_id, scene_id=scene_id)
    content_type = scene.content_type or classify_scene(scene.narration_text, scene.visual_description)
    logger.info("Code generation request", extra={"scene_id": scene_id, "content_type": content_type,
                                                   "model": settings.CODE_GENERATOR_MODEL})

    run_id     = str(uuid.uuid4())
    start_time = time.time()

    if _tracer:
        try:
            _tracer.create_run(
                name="code-generator.generate", run_type="llm", run_id=run_id,
                metadata={
                    "service":      "code-generator",
                    "job_id":       request.job_id,
                    "scene_id":     scene_id,
                    "model":        settings.CODE_GENERATOR_MODEL,
                    "content_type": content_type,
                    "is_retry":     bool(request.error_log and request.previous_code),
                }
            )
        except Exception as _trace_exc:
            logger.debug(f"LangSmith trace failed: {_trace_exc}")

    if content_type == "manim":
        return await _generate_manim(request, run_id, start_time)
    else:
        return await _generate_hyperframes(request, run_id, start_time)


@app.get("/health")
def health():
    return {"status": "ok"}
