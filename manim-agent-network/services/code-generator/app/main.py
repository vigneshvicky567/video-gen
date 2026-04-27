from fastapi import FastAPI
from shared.schemas.requests import CodeGeneratorRequest
from shared.schemas.responses import CodeGeneratorResponse
from shared.config import settings
from shared.llm_client import get_llm_client
import os
import json
import logging
import uuid
import time
from pydantic import BaseModel

# LangSmith Tracing
app = FastAPI(title="Code Generator Service")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Keywords for content type classification
HYPERFRAMES_KEYWORDS = [
    "title", "intro", "lower third", "text overlay", "caption", 
    "text animation", "welcome", "outro", "summary", "conclusion",
    "heading", "subtitle", "bullet points", "list", "quote"
]

MANIM_KEYWORDS = [
    "equation", "graph", "animation", "transform", "draw", "math",
    "function", "geometry", "plot", "diagram", "3d", "matrix",
    "vector", "coordinate", "axis", "curve", "surface", "shape"
]


def classify_scene(narration_text: str, visual_description: str) -> str:
    """Classify scene content type based on keywords.
    
    Args:
        narration_text: The narration text for the scene
        visual_description: The visual description for the scene
        
    Returns:
        "hyperframes" for text/UI content, "manim" for mathematical animations
    """
    combined_text = f"{narration_text} {visual_description}".lower()
    
    # Check for HyperFrames keywords
    hf_matches = sum(1 for kw in HYPERFRAMES_KEYWORDS if kw in combined_text)
    
    # Check for Manim keywords
    manim_matches = sum(1 for kw in MANIM_KEYWORDS if kw in combined_text)
    
    # Default to manim if no clear match
    if manim_matches > hf_matches:
        return "manim"
    elif hf_matches > manim_matches:
        return "hyperframes"
    else:
        # Default fallback - use manim for mathematical content
        return "manim"


def generate_hyperframes_html(scene_id: int, narration_text: str, 
                                visual_description: str, duration: int = 5) -> str:
    """Generate HyperFrames HTML for text/UI scenes.
    
    Args:
        scene_id: The scene identifier
        narration_text: The narration text (used for lower third)
        visual_description: The visual description (used for main content)
        duration: Estimated duration in seconds
        
    Returns:
        Complete HTML document string with proper HyperFrames attributes
    """
    # Truncate narration for lower third
    lower_third_text = narration_text[:120] if len(narration_text) > 120 else narration_text
    
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Scene {scene_id}</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            background: #0f0f0f;
            width: 1920px;
            height: 1080px;
            overflow: hidden;
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
        }}
        .stage {{
            position: relative;
            width: 100%;
            height: 100%;
        }}
        .clip {{
            position: absolute;
            opacity: 0;
        }}
        .title-card {{
            left: 50%;
            top: 40%;
            transform: translate(-50%, -50%);
            font-size: 72px;
            font-weight: 700;
            color: #ffffff;
            text-align: center;
            white-space: nowrap;
        }}
        .content-text {{
            left: 50%;
            top: 50%;
            transform: translate(-50%, -50%);
            font-size: 48px;
            color: #ffffff;
            text-align: center;
            max-width: 80%;
            line-height: 1.4;
        }}
        .lower-third {{
            left: 0;
            bottom: 0;
            width: 100%;
            height: 120px;
            background: linear-gradient(90deg, rgba(0,0,0,0.9) 0%, rgba(0,0,0,0.7) 100%);
            display: flex;
            align-items: center;
            padding: 0 60px;
        }}
        .lower-third-text {{
            font-size: 28px;
            color: #ffffff;
            line-height: 1.3;
        }}
    </style>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.2/gsap.min.js"></script>
</head>
<body>
    <div class="stage">
        <!-- Title card -->
        <h1 class="clip title-card" data-start="0" data-duration="2" data-track-index="1">
            Scene {scene_id}
        </h1>
        
        <!-- Main content clip -->
        <div class="clip content-text" data-start="0.5" data-duration="{duration - 0.5}" data-track-index="2">
            {visual_description}
        </div>
        
        <!-- Lower third with narration -->
        <div class="clip lower-third" data-start="1" data-duration="{duration - 1}" data-track-index="3">
            <span class="lower-third-text">{lower_third_text}</span>
        </div>
    </div>
    
    <script>
        // GSAP animations with proper timeline registration
        gsap.registerPlugin();
        
        // Register timeline for renderer
        window.__timelines = window.__timelines || [];
        
        var tl = gsap.timeline();
        
        // Title fade in (smooth easing)
        tl.to(".title-card", {{
            duration: 0.8,
            opacity: 1,
            ease: "power2.out"
        }});
        
        // Content fade in
        tl.to(".content-text", {{
            duration: 1,
            opacity: 1,
            ease: "power2.out"
        }}, "-=0.3");
        
        // Lower third slide up (smooth)
        tl.to(".lower-third", {{
            duration: 0.6,
            opacity: 1,
            ease: "power2.out"
        }}, "-=0.3");
        
        // Register the timeline
        window.__timelines.push(tl);
    </script>
</body>
</html>"""
    return html

# LangSmith tracer setup
_tracer = None
if os.getenv("LANGSMITH_API_KEY"):
    try:
        import langsmith
        langsmith_client = langsmith.Client()
        _tracer = langsmith_client
        logger.info("LangSmith tracing enabled")
    except ImportError:
        logger.warning("langsmith not installed, tracing disabled")

# Initialize NVIDIA NIM client (DeepSeek)
client = get_llm_client()
logger.info(f"Code Generator using model: {settings.CODE_GENERATOR_MODEL}")

class CodeGenOutput(BaseModel):
    python_code: str

@app.post("/generate", response_model=CodeGeneratorResponse)
async def generate_code(request: CodeGeneratorRequest):
    logger.info(f"Generating code for job {request.job_id}, scene {request.scene.scene_id} | model: {settings.CODE_GENERATOR_MODEL}")

    # Classify scene content type
    content_type = request.scene.content_type or classify_scene(
        request.scene.narration_text, 
        request.scene.visual_description
    )
    logger.info(f"Scene {request.scene.scene_id} classified as: {content_type}")
    
    # Start LangSmith trace
    run_id = str(uuid.uuid4())
    start_time = time.time()
    
    if _tracer:
        try:
            _tracer.create_run(
                name="code-generator.generate",
                run_type="llm",
                run_id=run_id,
                metadata={
                    "service": "code-generator",
                    "job_id": request.job_id,
                    "scene_id": request.scene.scene_id,
                    "model": settings.CODE_GENERATOR_MODEL,
                    "content_type": content_type,
                    "is_retry": bool(request.error_log and request.previous_code)
                }
            )
        except Exception as e:
            logger.debug(f"LangSmith trace start failed: {e}")

    # Route based on content type
    if content_type == "hyperframes":
        return await _generate_hyperframes(request, run_id, start_time)
    else:
        return await _generate_manim(request, run_id, start_time)


async def _generate_hyperframes(request, run_id, start_time):
    """Generate HyperFrames HTML for text/UI content."""
    logger.info(f"Generating HyperFrames HTML for scene {request.scene.scene_id}")
    
    try:
        # Generate HyperFrames HTML
        html_content = generate_hyperframes_html(
            scene_id=request.scene.scene_id,
            narration_text=request.scene.narration_text,
            visual_description=request.scene.visual_description,
            duration=request.scene.estimated_duration_seconds
        )
        
        # Save HTML to workspace
        temp_dir = os.path.join(settings.WORKSPACE_DIR, "temp", request.job_id)
        os.makedirs(temp_dir, exist_ok=True)
        
        file_path = os.path.join(temp_dir, f"scene_{request.scene.scene_id}.html")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        
        total_duration = time.time() - start_time
        
        # Final trace update
        if _tracer:
            try:
                _tracer.update_run(
                    run_id=run_id,
                    outputs={"code_path": file_path, "content_type": "hyperframes"},
                    end_time=time.time(),
                    metrics={"total_latency": total_duration}
                )
            except Exception:
                pass
        
        logger.info(f"HyperFrames HTML generated for scene {request.scene.scene_id}: {file_path}")
        return CodeGeneratorResponse(
            scene_id=request.scene.scene_id,
            code_path=file_path
        )
        
    except Exception as e:
        total_duration = time.time() - start_time
        if _tracer:
            try:
                _tracer.update_run(
                    run_id=run_id,
                    error=str(e),
                    end_time=time.time(),
                    metrics={"total_latency": total_duration}
                )
            except Exception:
                pass
        logger.error(f"Error generating HyperFrames: {str(e)}")
        raise e


async def _generate_manim(request, run_id, start_time):
    """Generate Manim Python code for mathematical animations."""
    logger.info(f"Generating Manim code for scene {request.scene.scene_id}")

    # Construct prompt based on whether this is a retry or first attempt
    if request.error_log and request.previous_code:
        logger.info(f"Retry attempt for scene {request.scene.scene_id}. Providing error context.")
        prompt = f"""
You are an expert mathematical animator using Manim Community Edition (Manim CE).

You previously wrote Manim code for a scene, but it failed to render. Please fix the code following the layout rules.

============================================================
HARD RULES FOR LAYOUT (MANDATORY – NEVER VIOLATE)
============================================================
1. **ABSOLUTELY NO OVERLAPPING TEXT.** Use VGroup and arrange()
2. **Short text only.** Max 3 lines per Tex block, 4-6 words per segment
3. **Sequential storyboard:** Title → Formula → Diagram → Motion
4. **Positioning:** Title at top, content centered, use VGroup for groups
5. **FRAME FIT RULE:** full = VGroup(*all); full.scale_to_fit_width(12); full.move_to(ORIGIN)
6. **Never exceed 6 units from center horizontally**
7. **Use wait() calls** for pacing between animations

============================================================
PREVIOUS CODE (failed to render):
```python
{request.previous_code}
```

ERROR LOG:
{request.error_log}

============================================================
OUTPUT REQUIREMENTS
============================================================
1. Fix the code following the layout rules above
2. Use correct Manim CE syntax: `from manim import *`, `MathTex`, etc.
3. Class name MUST be Scene{request.scene.scene_id}
4. Return ONLY valid python code as JSON: {{"python_code": "..."}}
"""
    else:
        prompt = f"""
You are an expert mathematical animator using Manim Community Edition (Manim CE).

Goal:
- Generate clear, elegant, *non-overlapping* Manim scripts that visualize the mathematical idea.
- Output a valid Manim CE Python file.

Environment:
- Dependencies: manim, numpy, sympy, matplotlib are pre-installed.
- Use `from manim import *` for imports.
- Each scene must define a subclass of Scene and use self.play with animations.
- Never use external assets or web calls.

============================================================
FEW-SHOT EXAMPLES (Study these patterns carefully)
============================================================

Example 1: Simple function visualization
Input: "Visualize the sine wave function y = sin(x)"
Output:
```json
{{
  "python_code": "from manim import *\\n\\nclass Scene1(Scene):\\n    def construct(self):\\n        # Step 1: Title\\n        title = Text('Sine Wave', font_size=48).to_edge(UP)\\n        self.play(Write(title))\\n        self.wait(0.5)\\n\\n        # Step 2: Axes and curve\\n        axes = Axes(x_range=[-4, 4], y_range=[-2, 2], x_length=10, y_length=4).move_to(DOWN * 0.5)\\n        self.play(Create(axes))\\n        self.wait(0.5)\\n\\n        # Step 3: Sine curve\\n        sine_curve = axes.plot(lambda x: np.sin(x), color=BLUE)\\n        self.play(Create(sine_curve), run_time=2)\\n        self.wait(1)\\n\\n        # Step 4: Label\\n        label = MathTex(r'y = \\\\sin(x)', font_size=36).next_to(axes, UP)\\n        self.play(Write(label))\\n        self.wait(2)\\n"
}}
```

Example 2: Two objects with VGroup
Input: "Show a circle and square side by side"
Output:
```json
{{
  "python_code": "from manim import *\\n\\nclass Scene1(Scene):\\n    def construct(self):\\n        # Title\\n        title = Text('Shapes', font_size=36).to_edge(UP)\\n        self.play(Write(title))\\n\\n        # Create shapes\\n        circle = Circle(radius=1, color=BLUE)\\n        square = Square(side_length=1.5, color=RED)\\n\\n        # Group and arrange\\n        shapes = VGroup(circle, square)\\n        shapes.arrange(RIGHT, buff=1)\\n        shapes.move_to(ORIGIN)\\n\\n        self.play(Create(circle), Create(square), run_time=1.5)\\n        self.wait(2)\\n"
}}
```

Example 3: Formula with explanation
Input: "Explain E = mc² with the formula"
Output:
```json
{{
  "python_code": "from manim import *\\n\\nclass Scene1(Scene):\\n    def construct(self):\\n        # Title\\n        title = Text('Mass-Energy Equivalence', font_size=36).to_edge(UP)\\n        self.play(Write(title))\\n        self.wait(0.5)\\n\\n        # Formula\\n        formula = MathTex(r'E = mc^2', font_size=72).move_to(ORIGIN)\\n        self.play(Write(formula))\\n        self.wait(1)\\n\\n        # Brief explanation\\n        explanation = Text('Energy equals mass times speed of light squared', font_size=24).to_edge(DOWN)\\n        self.play(FadeIn(explanation, shift=UP))\\n        self.wait(3)\\n"
}}
```

============================================================
HARD RULES FOR LAYOUT (MANDATORY – NEVER VIOLATE)
============================================================
1. **ABSOLUTELY NO OVERLAPPING TEXT.**
   - Never place more than ONE paragraph-level block of text on screen at once.
   - Never place multiple long Tex blocks stacked manually unless explicitly arranged with:
     VGroup(...).arrange(DOWN), next_to(), to_edge(), shift()

2. **Short text only.**
   - Summarize long explanations into short 4–6 word segments per line.
   - NEVER exceed ~3 lines per Tex block.

3. **Sequential storyboard is required.**
   Every animation must follow this structure:
   STEP 1 — Title at top (short, 1–3 words)
   STEP 2 — Optional subtitle (short)
   STEP 3 — Main formula or key object
   STEP 4 — One compact bullet list or short explanation (3 bullets max)
   STEP 5 — Diagram / axes / shapes
   STEP 6 — Any transformation or motion
   Each step appears separately using FadeIn / Write.
   Never show more than two text elements on screen simultaneously.

4. **Text formatting rules:**
   - Break lines using LaTeX "\\\\" only.
   - Never use "\\n" inside Tex/MathTex.
   - Keep font sizes in the range 28–48.
   - Add a small background rectangle for readability if needed.

5. **Positioning rules:**
   - Title: .to_edge(UP)
   - Bullet list or short explanation: next_to(main_object, DOWN)
   - Never put anything at raw coordinates unless necessary.
   - Maintain safe margins (0.3–0.6 units).

6. **Global layout must ALWAYS fit inside a 16:9 frame.**
   - After constructing multiple large groups, wrap in VGroup or Group.
   - Apply: full_group.scale_to_fit_width(13); full_group.move_to(ORIGIN)

7. **Never place content further than 6 units from center horizontally.**
   - All objects must satisfy: abs(obj.get_x()) < 6

8. **FRAME FIT RULE (required):**
   After constructing ANY multi-part diagram, the entire layout MUST be grouped:
   full = VGroup(*all_diagrams)
   full.arrange(RIGHT, buff=0.6)
   full.scale_to_fit_width(12)
   full.move_to(ORIGIN)

9. **Content minimization:**
   - Extract only the essential mathematical ideas.
   - Prefer diagrams, formulas, and conceptual motion over large text.

10. **Never reproduce the user's entire prompt.**
    - Only visualize the concept, not the narration.
    - Turn long descriptions into conceptual scenes.

============================================================
SCENE DETAILS
============================================================
Narration: {request.scene.narration_text}
Visual Description: {request.scene.visual_description}
Scene Number: {request.scene.scene_id}

============================================================
OUTPUT REQUIREMENTS
============================================================
1. Import Manim CE: `from manim import *`
2. Create a Scene class named EXACTLY `Scene{request.scene.scene_id}`.
3. Keep the animation clean and mathematically accurate.
4. Do not include any standard file running blocks at the bottom.
5. Return ONLY valid python code as JSON: {{"python_code": "..."}}
"""

    try:
        # Trace LLM call
        llm_start = time.time()
        response = client.chat.completions.create(
            model=settings.CODE_GENERATOR_MODEL,
            messages=[
                {"role": "system", "content": "You are an expert Manim CE developer. Always respond with valid JSON containing the python_code key."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2,
            response_format={"type": "json_object"}
        )
        llm_duration = time.time() - llm_start
        
        # Log LLM trace
        if _tracer:
            try:
                _tracer.update_run(
                    run_id=run_id,
                    inputs={"prompt": prompt[:500]},
                    outputs={"code_length": len(response.choices[0].message.content)},
                    metrics={"latency": llm_duration}
                )
            except Exception:
                pass

        code_data = json.loads(response.choices[0].message.content)
        code = code_data.get("python_code", "")

        # Save code to workspace
        temp_dir = os.path.join(settings.WORKSPACE_DIR, "temp", request.job_id)
        os.makedirs(temp_dir, exist_ok=True)

        file_path = os.path.join(temp_dir, f"scene_{request.scene.scene_id}.py")
        with open(file_path, "w") as f:
            f.write(code)

        total_duration = time.time() - start_time
        
        # Final trace update
        if _tracer:
            try:
                _tracer.update_run(
                    run_id=run_id,
                    outputs={"code_path": file_path, "code_length": len(code)},
                    end_time=time.time(),
                    metrics={"total_latency": total_duration}
                )
            except Exception:
                pass

        return CodeGeneratorResponse(
            scene_id=request.scene.scene_id,
            code_path=file_path
        )

    except Exception as e:
        total_duration = time.time() - start_time
        if _tracer:
            try:
                _tracer.update_run(
                    run_id=run_id,
                    error=str(e),
                    end_time=time.time(),
                    metrics={"total_latency": total_duration}
                )
            except Exception:
                pass
        logger.error(f"Error generating Manim code: {str(e)}")
        raise e

@app.get("/health")
def health():
    return {"status": "ok"}
