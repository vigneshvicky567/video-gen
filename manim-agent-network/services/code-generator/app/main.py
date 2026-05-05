from fastapi import FastAPI
from shared.schemas.requests import CodeGeneratorRequest
from shared.schemas.responses import CodeGeneratorResponse
from shared.config import settings
from shared.llm_client import get_llm_client
from shared.log import get_logger, set_log_context, timed_block, log_llm_call, log_file, make_request_logging_middleware
import os
import sys
from .sanitizer import sanitize_manim_code
import re
import json
import uuid
import time


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
_HF_SYSTEM = """You are an expert HyperFrames HTML video composer creating educational explainer videos.
HyperFrames renders HTML to MP4 frame-by-frame using Puppeteer + FFmpeg.

VISUAL STYLE (match professional educational slides like 3Blue1Brown / StatQuest):
- Canvas: 1920×1080px, WHITE background (#ffffff).
- Typography: Inter or system-ui font. Bold black titles (48-64px). Body text #1a1a2e (36-42px).
- Accent colors: #e63946 (red), #2196f3 (blue), #ff9800 (orange), #4caf50 (green).
- Shapes: rounded rectangles with colored fills and white text for diagram nodes.
- Arrows: thick SVG arrows (#e63946 or #1a1a2e) between diagram nodes.
- Layout: generous whitespace, centered content, nothing touching edges.
- Animations: GSAP fadeIn (opacity 0→1), slideUp (y: 40→0), stagger on lists/nodes.

REQUIRED STRUCTURE:
- Root div: data-composition-id, data-start="0", data-duration, data-width="1920", data-height="1080".
- Every timed element: unique id, class="clip", data-start, data-duration, data-track-index.
- GSAP timeline registered as: window.__timelines["scene-N"] = tl (paused).
- Load GSAP from: https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.2/gsap.min.js

Output ONLY a complete <!DOCTYPE html> … </html> document, no markdown fences."""

def _build_hf_prompt(scene_id: int, narration: str, visual: str, duration: int) -> str:
    return f"""Create a HyperFrames HTML scene for an educational explainer video.

Scene ID: {scene_id}
Total duration: {duration} seconds
Narration (will be spoken): {narration}
Visual description: {visual}

DESIGN REQUIREMENTS (match the style of StatQuest / 3Blue1Brown slides):
1. WHITE background (#ffffff). All text in dark colors (#1a1a2e or #111).
2. BOLD title at top center (font-size: 56px, font-weight: 900, color: #1a1a2e).
   - Highlight 1-2 key words with a colored span (e.g. color:#e63946).
3. Main content area: centered, max-width 1600px, vertically centered in remaining space.
4. For DIAGRAMS (flow charts, concept maps):
   - Use rounded rectangles (border-radius:16px) with colored backgrounds and white text.
   - Connect nodes with thick SVG arrows (stroke:#e63946, stroke-width:6, marker-end arrowhead).
   - Animate nodes in with GSAP stagger: tl.from(".node", {{opacity:0, y:30, stagger:0.15}})
5. For LISTS / BULLET POINTS:
   - Large colored bullet circles (40px) with text beside them.
   - Stagger animate each item: tl.from(".item", {{opacity:0, x:-40, stagger:0.2}})
6. For FORMULAS / EQUATIONS:
   - Display in a light gray pill (#f0f0f0 background, border-radius:12px, padding:24px 48px).
   - Use MathJax or styled HTML spans for formula parts.
7. NO lower-third text bar — narration is handled by audio, not on-screen text.
8. Root wrapper:
   <div id="composition" data-composition-id="scene-{scene_id}" data-start="0" data-duration="{duration}" data-width="1920" data-height="1080" style="background:#ffffff;">
9. GSAP registration:
   const tl = gsap.timeline({{ paused: true }});
   window.__timelines = window.__timelines || {{}};
   window.__timelines["scene-{scene_id}"] = tl;
   tl.from("#title-{scene_id}", {{opacity:0, y:-30, duration:0.6}});
   // then animate content elements

Output ONLY the complete HTML document."""


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
    logger.info("Generating HyperFrames HTML", extra={"scene_id": scene_id})

    prompt = _build_hf_prompt(
        scene_id  = scene_id,
        narration = scene.narration_text,
        visual    = scene.visual_description,
        duration  = scene.estimated_duration_seconds,
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
                temperature = 0.6,
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
                except Exception:
                    pass

            logger.info("HyperFrames HTML saved", extra={"scene_id": scene_id, "path": file_path})
            return CodeGeneratorResponse(scene_id=scene_id, code_path=file_path)

        except Exception as e:
            last_error = e
            logger.warning("HyperFrames attempt failed", extra={"attempt": attempt + 1, "error": str(e)})

    raise RuntimeError(f"HyperFrames generation failed after 3 attempts: {last_error}")


# ─────────────────────────────────────────────────────────────────────────────
# Manim Python code generation via LLM
# ─────────────────────────────────────────────────────────────────────────────
_MANIM_SYSTEM = "You are an expert Manim CE developer. Always respond with valid JSON containing the python_code key."

def _build_manim_prompt(scene: object, error_log: str = None, previous_code: str = None) -> str:
    sid = scene.scene_id
    if error_log and previous_code:
        return f"""
You are an expert Manim CE animator. Fix the code below — it failed to render.

PREVIOUS CODE:
```python
{previous_code}
```

ERROR LOG:
{error_log}

HARD RULES:
1. TRANSPARENT BACKGROUND: config.background_color = WHITE and set_background_stroke_width(0).
   All text/strokes must use DARK colors (BLACK, DARK_BLUE, DARK_GRAY) — never WHITE text.
2. No overlapping text. Use VGroup + arrange().
3. Max 3 lines per Tex block, 4-6 words per segment.
4. Title at top (.to_edge(UP)), content centered.
5. After building multi-part layouts: full=VGroup(*all); full.scale_to_fit_width(12); full.move_to(ORIGIN)
6. FORBIDDEN — these do NOT exist in Manim CE, never use them:
   - `SVGMobject("anything")` — no bundled SVG assets; use Circle, Square, Rectangle, Polygon, Arrow
   - `SVGCircle`, `VGraph` — use `Circle`, `VGroup`
   - `Square.make_square_from_line()`, `Line.get_unit_normal()`
   - `.set_fill_by_checkerboard()`
   - `.animate.rotate(angle, axis=...)` — use `.rotate()` directly
   - `there_and_back_once` — use `there_and_back` instead
   - `MoveAlongPath(Dot(curve, ...), curve)` — use `Dot(curve.get_start(), ...)` then `MoveAlongPath(dot, curve)`
   - `line_intersection(p1, p2)` — use `(p1 + p2) / 2`
   - `rate_func=` as kwarg to `.animate(...)` — pass it to `self.play()` instead
   - `Circle(arc_length=...)` or `Arc(arc_length=...)` — use `Circle(radius=...)` or `Arc(radius=..., angle=...)`
   - `ShowCreationThenFadeOut` — removed; use `self.play(Create(obj)); self.play(FadeOut(obj))`
   - `ShowCreation` — REMOVED; use `Create` instead
   - `rate_functions.ease_out` — use `rate_functions.ease_out_sine`, `smooth`, or `linear`
   - `DARK_RED`, `DARK_BLUE` — NOT valid constants; use hex `"#8B0000"`, `"#00008B"` or `RED_E`, `BLUE_E`
   - `LIGHT_GRAY`, `DARK_GRAY` — use `GRAY_A`...`GRAY_E` or hex strings
   VALID colors: WHITE, BLACK, RED, GREEN, BLUE, YELLOW, ORANGE, PURPLE, PINK, TEAL, GOLD,
   and variants RED_A...RED_E, BLUE_A...BLUE_E, GREEN_A...GREEN_E, GRAY_A...GRAY_E.
   VALID rate_functions: linear, smooth, rush_into, rush_from, there_and_back,
   ease_in_sine, ease_out_sine, ease_in_out_sine, ease_in_quad, ease_out_quad.
7. Class name MUST be Scene{sid}.

Return ONLY: {{"python_code": "..."}}
"""
    return f"""
You are an expert Manim CE animator. Create a clean mathematical animation with a TRANSPARENT background.

SCENE DETAILS:
Narration: {scene.narration_text}
Visual:    {scene.visual_description}
Scene #:   {sid}

HARD RULES:
1. TRANSPARENT BACKGROUND — set at the top of construct():
   config.background_color = WHITE
   All strokes, text, and fills must use DARK colors (BLACK, DARK_BLUE, "#1a1a2e", DARK_GRAY, "#e63946" for accents).
   NEVER use WHITE for any visible element — it will be invisible on the white canvas.
2. Import: `from manim import *`
3. Class name MUST be `Scene{sid}` (subclass of Scene).
4. No overlapping text — use VGroup + arrange() / next_to() / to_edge().
5. Sequential storyboard: Formula/Object → Labels → Motion. No title text (title is handled by HyperFrames layer).
6. After multi-part layouts: full=VGroup(*all); full.scale_to_fit_width(12); full.move_to(ORIGIN)
7. Font sizes 28-48. Use wait() for pacing.
8. FORBIDDEN — these do NOT exist in Manim CE, never use them:
   - `SVGMobject("anything")` — no bundled SVG assets exist; use primitive shapes (Circle, Square, Rectangle, Polygon, Arrow, etc.)
   - `SVGCircle`, `VGraph` — these don't exist; use `Circle`, `VGroup`
   - `Square.make_square_from_line()`, `Line.get_unit_normal()`
   - `.set_fill_by_checkerboard()`
   - `.animate.rotate(angle, axis=...)` — use `.rotate()` directly
   - `there_and_back_once` — use `there_and_back` instead
   - `MoveAlongPath(Dot(curve, ...), curve)` — `Dot()` takes a point, not a curve;
     use `Dot(curve.get_start(), ...)` and then `MoveAlongPath(dot, curve)`
   - `line_intersection(p1, p2)` — does not exist; compute midpoint as `(p1 + p2) / 2`
   - `rate_func=` as a kwarg to `.animate(...)` — pass it to `self.play()` instead
   - `Circle(arc_length=...)` or `Arc(arc_length=...)` — no such param; use `Circle(radius=...)` or `Arc(radius=..., angle=...)`
   - `ShowCreationThenFadeOut` — removed; use `self.play(Create(obj)); self.play(FadeOut(obj))` instead
   - `ShowCreation` — REMOVED; use `Create` instead
   - `rate_functions.ease_out` — use `rate_functions.ease_out_sine`, `smooth`, or `linear`
   - `DARK_RED`, `DARK_BLUE` — NOT valid constants; use hex `"#8B0000"`, `"#00008B"` or `RED_E`, `BLUE_E`
   - `LIGHT_GRAY`, `DARK_GRAY` — use `GRAY_A`...`GRAY_E` or hex strings
   VALID colors: WHITE, BLACK, RED, GREEN, BLUE, YELLOW, ORANGE, PURPLE, PINK, TEAL, GOLD,
   and variants RED_A...RED_E, BLUE_A...BLUE_E, GREEN_A...GREEN_E, GRAY_A...GRAY_E.
   VALID rate_functions: linear, smooth, rush_into, rush_from, there_and_back,
   ease_in_sine, ease_out_sine, ease_in_out_sine, ease_in_quad, ease_out_quad.
9. No external assets or web calls.
10. Use rich colors for math objects: axes in "#1a1a2e", curves in "#e63946" or "#2196f3", dots in "#ff9800".

FEW-SHOT EXAMPLE (transparent bg, dark strokes, correct MoveAlongPath):
```json
{{"python_code": "from manim import *\\n\\nclass Scene1(Scene):\\n    def construct(self):\\n        config.background_color = WHITE\\n        axes = Axes(x_range=[-3,3], y_range=[0,9], x_length=8, y_length=5, axis_config={{\\\"color\\\": \\\"#1a1a2e\\\", \\\"stroke_width\\\": 3}}).move_to(DOWN*0.3)\\n        labels = axes.get_axis_labels(x_label=\\\"x\\\", y_label=\\\"y\\\").set_color(BLACK)\\n        curve = axes.plot(lambda x: x**2, color=\\\"#e63946\\\", stroke_width=4)\\n        self.play(Create(axes), Write(labels))\\n        self.play(Create(curve), run_time=2)\\n        dot = Dot(axes.c2p(-2, 4), color=\\\"#ff9800\\\", radius=0.12)\\n        self.play(FadeIn(dot))\\n        self.play(MoveAlongPath(dot, curve), run_time=2, rate_func=there_and_back)\\n        self.wait(1)\\n"}}
```

Return ONLY: {{"python_code": "..."}}
"""


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
            temperature     = 0.2,
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
            except Exception:
                pass

        logger.info("Manim code saved", extra={"scene_id": scene_id, "path": file_path, "code_lines": code.count(chr(10))})
        return CodeGeneratorResponse(scene_id=scene_id, code_path=file_path)

    except Exception as e:
        total = time.time() - start_time
        if _tracer:
            try:
                _tracer.update_run(run_id=run_id, error=str(e),
                    end_time=time.time(), metrics={"total_latency": total})
            except Exception:
                pass
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
        except Exception:
            pass

    if content_type == "manim":
        return await _generate_manim(request, run_id, start_time)
    else:
        return await _generate_hyperframes(request, run_id, start_time)


@app.get("/health")
def health():
    return {"status": "ok"}
