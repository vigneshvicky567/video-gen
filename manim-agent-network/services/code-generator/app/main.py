from fastapi import FastAPI
from shared.schemas.requests import CodeGeneratorRequest
from shared.schemas.responses import CodeGeneratorResponse
from shared.config import settings
from shared.llm_client import get_llm_client
import os
import re
import json
import logging
import uuid
import time

app = FastAPI(title="Code Generator Service")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_tracer = None
if os.getenv("LANGSMITH_API_KEY"):
    try:
        import langsmith
        langsmith_client = langsmith.Client()
        _tracer = langsmith_client
        logger.info("LangSmith tracing enabled")
    except ImportError:
        logger.warning("langsmith not installed, tracing disabled")

client = get_llm_client()
logger.info(f"Code Generator using model: {settings.CODE_GENERATOR_MODEL}")


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
_HF_SYSTEM = """You are an expert HyperFrames HTML video composer.
HyperFrames renders HTML to MP4 frame-by-frame using Puppeteer + FFmpeg.

Rules:
- Canvas is always 1920×1080px, background #0f0f0f.
- The root composition div must have data-composition-id, data-start="0", data-duration, data-width="1920", data-height="1080".
- Every timed element needs a unique id plus class="clip" and data-start / data-duration / data-track-index attributes.
- Use GSAP (loaded from CDN) for animations. Register a paused timeline on window.__timelines["scene-N"].
- data-start and data-duration are in SECONDS (floats).
- data-track-index must be unique integers starting from 1.
- Use inline styles for positioning (position:absolute).
- Output ONLY a complete <!DOCTYPE html> … </html> document, no markdown fences."""

def _build_hf_prompt(scene_id: int, narration: str, visual: str, duration: int) -> str:
    return f"""Create a HyperFrames HTML scene for the following:

Scene ID: {scene_id}
Total duration: {duration} seconds
Narration (will be spoken): {narration}
Visual description: {visual}

Requirements:
1. Full 1920×1080 canvas, dark background (#0f0f0f or a gradient).
2. Use GSAP animations: fadeIn, slideUp, stagger, etc. — make it look polished.
3. Include a lower-third bar at the bottom with the narration text (max 120 chars).
4. Root wrapper must be:
   <div id="composition" data-composition-id="scene-{scene_id}" data-start="0" data-duration="{duration}" data-width="1920" data-height="1080">
5. All clips must have unique id, class="clip", data-start, data-duration, data-track-index.
6. Register exactly:
   const tl = gsap.timeline({{ paused: true }});
   window.__timelines = window.__timelines || {{}};
   window.__timelines["scene-{scene_id}"] = tl;
7. Do not use window.__timelines.push().
6. Load GSAP from: https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.2/gsap.min.js
8. Make it visually impressive — use gradients, accent colors, clean typography.

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
    logger.info(f"Generating HyperFrames HTML for scene {scene_id}")

    prompt = _build_hf_prompt(
        scene_id  = scene_id,
        narration = scene.narration_text,
        visual    = scene.visual_description,
        duration  = scene.estimated_duration_seconds,
    )

    last_error = None
    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model    = settings.CODE_GENERATOR_MODEL,
                messages = [
                    {"role": "system", "content": _HF_SYSTEM},
                    {"role": "user",   "content": prompt},
                ],
                temperature = 0.6,
            )
            html = _extract_html(resp.choices[0].message.content)
            if not html:
                raise ValueError("LLM returned empty HTML")

            temp_dir  = os.path.join(settings.WORKSPACE_DIR, "temp", request.job_id)
            os.makedirs(temp_dir, exist_ok=True)
            file_path = os.path.join(temp_dir, f"scene_{scene_id}.html")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(html)

            total = time.time() - start_time
            if _tracer:
                try:
                    _tracer.update_run(run_id=run_id,
                        outputs={"code_path": file_path, "content_type": "hyperframes"},
                        end_time=time.time(), metrics={"total_latency": total})
                except Exception:
                    pass

            logger.info(f"HyperFrames HTML saved: {file_path}")
            return CodeGeneratorResponse(scene_id=scene_id, code_path=file_path)

        except Exception as e:
            last_error = e
            logger.warning(f"HyperFrames attempt {attempt+1} failed: {e}")

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
1. No overlapping text. Use VGroup + arrange().
2. Max 3 lines per Tex block, 4-6 words per segment.
3. Title at top (.to_edge(UP)), content centered.
4. After building multi-part layouts: full=VGroup(*all); full.scale_to_fit_width(12); full.move_to(ORIGIN)
5. FORBIDDEN: Square.make_square_from_line(), Line.get_unit_normal() — these don't exist.
6. Class name MUST be Scene{sid}.

Return ONLY: {{"python_code": "..."}}
"""
    return f"""
You are an expert Manim CE animator. Create a clean mathematical animation.

SCENE DETAILS:
Narration: {scene.narration_text}
Visual:    {scene.visual_description}
Scene #:   {sid}

HARD RULES:
1. Import: `from manim import *`
2. Class name MUST be `Scene{sid}` (subclass of Scene).
3. No overlapping text — use VGroup + arrange() / next_to() / to_edge().
4. Sequential storyboard: Title → Formula/Object → Explanation → Motion.
5. After multi-part layouts: full=VGroup(*all); full.scale_to_fit_width(12); full.move_to(ORIGIN)
6. Font sizes 28-48. Use wait() for pacing.
7. FORBIDDEN methods (don't exist in Manim CE):
   - Square.make_square_from_line()
   - Line.get_unit_normal()
   - .set_fill_by_checkerboard() — does not exist
   - .animate.rotate(angle, axis=...) — axis param not supported in 2D scenes, use .rotate() directly
   Use manual numpy calculations instead.
8. No external assets or web calls.

FEW-SHOT EXAMPLE:
```json
{{"python_code": "from manim import *\\n\\nclass Scene1(Scene):\\n    def construct(self):\\n        title = Text('Gradient Descent', font_size=44).to_edge(UP)\\n        self.play(Write(title))\\n        self.wait(0.5)\\n        axes = Axes(x_range=[-3,3], y_range=[0,9], x_length=8, y_length=5).move_to(DOWN*0.5)\\n        curve = axes.plot(lambda x: x**2, color=BLUE)\\n        self.play(Create(axes), Create(curve))\\n        dot = Dot(axes.c2p(-2, 4), color=RED)\\n        self.play(FadeIn(dot))\\n        self.play(dot.animate.move_to(axes.c2p(0, 0)), run_time=2)\\n        self.wait(2)\\n"}}
```

Return ONLY: {{"python_code": "..."}}
"""


async def _generate_manim(request, run_id: str, start_time: float):
    scene    = request.scene
    scene_id = scene.scene_id
    logger.info(f"Generating Manim code for scene {scene_id}")

    if request.error_log and request.previous_code:
        logger.info(f"Retry for scene {scene_id}")

    prompt = _build_manim_prompt(scene, request.error_log, request.previous_code)

    try:
        llm_start = time.time()
        response  = client.chat.completions.create(
            model    = settings.CODE_GENERATOR_MODEL,
            messages = [
                {"role": "system", "content": _MANIM_SYSTEM},
                {"role": "user",   "content": prompt},
            ],
            temperature     = 0.2,
            response_format = {"type": "json_object"},
        )
        llm_dur = time.time() - llm_start

        if _tracer:
            try:
                _tracer.update_run(run_id=run_id,
                    inputs={"prompt": prompt[:500]},
                    outputs={"code_length": len(response.choices[0].message.content)},
                    metrics={"latency": llm_dur})
            except Exception:
                pass

        code_data = json.loads(response.choices[0].message.content)
        code      = code_data.get("python_code", "")

        temp_dir  = os.path.join(settings.WORKSPACE_DIR, "temp", request.job_id)
        os.makedirs(temp_dir, exist_ok=True)
        file_path = os.path.join(temp_dir, f"scene_{scene_id}.py")
        with open(file_path, "w") as f:
            f.write(code)

        total = time.time() - start_time
        if _tracer:
            try:
                _tracer.update_run(run_id=run_id,
                    outputs={"code_path": file_path, "code_length": len(code)},
                    end_time=time.time(), metrics={"total_latency": total})
            except Exception:
                pass

        logger.info(f"Manim code saved: {file_path}")
        return CodeGeneratorResponse(scene_id=scene_id, code_path=file_path)

    except Exception as e:
        total = time.time() - start_time
        if _tracer:
            try:
                _tracer.update_run(run_id=run_id, error=str(e),
                    end_time=time.time(), metrics={"total_latency": total})
            except Exception:
                pass
        logger.error(f"Manim generation error: {e}")
        raise e


# ─────────────────────────────────────────────────────────────────────────────
# Main endpoint
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/generate", response_model=CodeGeneratorResponse)
async def generate_code(request: CodeGeneratorRequest):
    scene    = request.scene
    scene_id = scene.scene_id
    logger.info(f"Generating code for job {request.job_id}, scene {scene_id} | model: {settings.CODE_GENERATOR_MODEL}")

    # Determine content type: script-writer sets it, fallback to classifier
    content_type = scene.content_type or classify_scene(scene.narration_text, scene.visual_description)
    logger.info(f"Scene {scene_id} → content_type={content_type}")

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
