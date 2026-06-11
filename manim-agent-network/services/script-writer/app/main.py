from fastapi import FastAPI
from shared.schemas.requests import ScriptWriterRequest
from shared.schemas.responses import ScriptWriterResponse
from shared.schemas.common import ScriptResponse
from shared.config import settings
from shared.llm_client import get_llm_client
from shared.log import get_logger, set_log_context, timed_block, log_llm_call, make_request_logging_middleware
import json
import uuid
import time
import os

app = FastAPI(title="Script Writer Service")
app.add_middleware(make_request_logging_middleware("script-writer"))
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

client = get_llm_client()
logger.info("Script Writer ready", extra={"model": settings.SCRIPT_WRITER_MODEL})


@app.post("/generate", response_model=ScriptWriterResponse)
async def generate_script(request: ScriptWriterRequest):
    set_log_context(job_id=getattr(request, "job_id", ""))
    logger.info("Generating script", extra={"topic": request.topic, "model": settings.SCRIPT_WRITER_MODEL})

    run_id     = str(uuid.uuid4())
    start_time = time.time()

    if _tracer:
        try:
            _tracer.create_run(
                name="script-writer.generate", run_type="llm", run_id=run_id,
                metadata={"service": "script-writer", "topic": request.topic,
                          "model": settings.SCRIPT_WRITER_MODEL}
            )
        except Exception:
            pass

    prompt = f"""
You are an expert technical director for educational video production.

Create a script for a video about: **{request.topic}**

Decide how many scenes the topic needs. A simple concept might need 3 scenes.
A complex topic might need 7 or more. Use as many scenes as it takes to explain
the topic clearly — do not pad, do not cut short.

## Scene Types — choose based on what the scene ACTUALLY needs:

**"hyperframes"** — use when the scene is primarily text/UI:
- Title card, intro, outro, summary
- Bullet-point explanation or concept overview
- Animated text, lower thirds, typography-driven content

**"manim"** — use when the scene needs a visual diagram or mathematical animation:
- Plotting a function or graph (e.g., loss curve, decision boundary)
- Drawing a geometric construction or proof
- Animating a formula step-by-step
- Visualizing a neural network, matrix, or data structure
- Any scene where shapes, curves, or math objects move/transform

## Rules:
- Scene 1 MUST be "hyperframes" (title/intro card)
- Last scene MUST be "hyperframes" (summary/outro)
- Middle scenes: pick the type that best serves the content
  - Text explanation → "hyperframes"
  - Visual diagram or math animation → "manim"
- narration_text must be natural and conversational (TTS-friendly, 1-3 sentences per scene)
- estimated_duration_seconds should reflect how long the narration actually takes to speak
  (roughly 130 words per minute — a 2-sentence narration ≈ 8-12 seconds)
- visual_description must be specific:
  - For hyperframes: describe layout, text content, colors, GSAP animations
  - For manim: describe exact objects, formulas, and animation sequence
- Manim scenes MUST describe a 2D visualization: flat graphs, diagrams, formulas.
  NEVER ask for 3D surfaces, terrain, or rotating cameras — describe the same
  idea as a 2D cross-section or contour plot instead (e.g. "a U-shaped loss
  curve with a ball rolling to the minimum", not "a 3D hilly landscape").
- One focused visualization per Manim scene (one diagram OR one plot OR one
  formula walkthrough, ≤6 animation beats). Split denser ideas across scenes.

Return ONLY valid JSON:
{{
  "title": "...",
  "scenes": [
    {{
      "scene_id": 1,
      "title": "Short Scene Title (4-6 words, shown as title bar)",
      "content_type": "hyperframes",
      "narration_text": "...",
      "visual_description": "...",
      "estimated_duration_seconds": 8
    }}
  ]
}}
"""

    try:
        llm_start = time.time()
        response  = await client.chat.completions.acreate(
            model=settings.SCRIPT_WRITER_MODEL,
            messages=[
                {"role": "system", "content": "You are an expert technical director. Always respond with valid JSON only."},
                {"role": "user",   "content": prompt}
            ],
            temperature=0.7,
            response_format={"type": "json_object"}
        )
        llm_duration = time.time() - llm_start
        log_llm_call(logger, settings.SCRIPT_WRITER_MODEL,
                     prompt_chars=len(prompt),
                     response_chars=len(response.choices[0].message.content),
                     elapsed_s=llm_duration)

        if _tracer:
            try:
                _tracer.update_run(run_id=run_id,
                    inputs={"prompt": prompt[:500]},
                    outputs={"response": response.choices[0].message.content[:500]},
                    metrics={"latency": llm_duration})
            except Exception:
                pass

        script_data = ScriptResponse(**json.loads(response.choices[0].message.content))

        total_duration = time.time() - start_time
        if _tracer:
            try:
                _tracer.update_run(run_id=run_id,
                    outputs={"scenes": len(script_data.scenes), "title": script_data.title},
                    end_time=time.time(), metrics={"total_latency": total_duration})
            except Exception:
                pass

        logger.info(
            "Script generated",
            extra={"title": script_data.title, "scenes": len(script_data.scenes),
                   "types": [s.content_type for s in script_data.scenes]},
        )
        for s in script_data.scenes:
            logger.info("  scene plan", extra={"scene_id": s.scene_id, "type": s.content_type,
                                               "duration_s": s.estimated_duration_seconds,
                                               "narration_preview": s.narration_text[:60]})

        return ScriptWriterResponse(script=script_data)

    except Exception as e:
        total_duration = time.time() - start_time
        if _tracer:
            try:
                _tracer.update_run(run_id=run_id, error=str(e),
                    end_time=time.time(), metrics={"total_latency": total_duration})
            except Exception:
                pass
        logger.error(f"Error generating script: {str(e)}")
        raise e


@app.get("/health")
def health():
    return {"status": "ok"}
