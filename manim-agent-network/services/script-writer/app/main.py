from fastapi import FastAPI
from shared.schemas.requests import ScriptWriterRequest
from shared.schemas.responses import ScriptWriterResponse
from shared.schemas.common import ScriptResponse
from shared.config import settings
from shared.llm_client import get_llm_client
import json
import logging
import uuid
import time
import os

app = FastAPI(title="Script Writer Service")
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
logger.info(f"Script Writer using model: {settings.SCRIPT_WRITER_MODEL}")


@app.post("/generate", response_model=ScriptWriterResponse)
async def generate_script(request: ScriptWriterRequest):
    logger.info(f"Generating script for topic: {request.topic} | model: {settings.SCRIPT_WRITER_MODEL}")

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

Create a 3-5 scene script for a video about: **{request.topic}**

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
- Scene 1 MUST be "hyperframes" (title/intro)
- Last scene MUST be "hyperframes" (summary/outro)
- Middle scenes: pick the type that best serves the content
  - Text explanation → "hyperframes"
  - Visual diagram or math animation → "manim"
- Keep narration_text natural and conversational (TTS-friendly, 1-3 sentences)
- visual_description must be specific:
  - For hyperframes: describe layout, text content, colors, GSAP animations
  - For manim: describe exact objects, formulas, and animation sequence

Return ONLY valid JSON:
{{
  "title": "...",
  "scenes": [
    {{
      "scene_id": 1,
      "content_type": "hyperframes",
      "narration_text": "...",
      "visual_description": "...",
      "estimated_duration_seconds": 5
    }}
  ]
}}
"""

    try:
        llm_start = time.time()
        response  = client.chat.completions.create(
            model=settings.SCRIPT_WRITER_MODEL,
            messages=[
                {"role": "system", "content": "You are an expert technical director. Always respond with valid JSON only."},
                {"role": "user",   "content": prompt}
            ],
            temperature=0.7,
            response_format={"type": "json_object"}
        )
        llm_duration = time.time() - llm_start

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

        logger.info(f"Script generated: '{script_data.title}' with {len(script_data.scenes)} scenes")
        for s in script_data.scenes:
            logger.info(f"  Scene {s.scene_id}: [{s.content_type or 'unset'}] {s.narration_text[:60]}...")

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
