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
from pathlib import Path

# LangSmith Tracing
app = FastAPI(title="Script Writer Service")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
logger.info(f"Script Writer using model: {settings.SCRIPT_WRITER_MODEL}")

@app.post("/generate", response_model=ScriptWriterResponse)
async def generate_script(request: ScriptWriterRequest):
    logger.info(f"Generating script for topic: {request.topic} | model: {settings.SCRIPT_WRITER_MODEL}")

    # Start LangSmith trace
    run_id = str(uuid.uuid4())
    start_time = time.time()
    
    if _tracer:
        try:
            _tracer.create_run(
                name="script-writer.generate",
                run_type="llm",
                run_id=run_id,
                metadata={
                    "service": "script-writer",
                    "topic": request.topic,
                    "model": settings.SCRIPT_WRITER_MODEL
                }
            )
        except Exception as e:
            logger.debug(f"LangSmith trace start failed: {e}")

    prompt = f"""
You are an expert technical director and script writer for mathematical and technical animations.
Create a highly detailed script and scene-by-scene breakdown for a Manim CE animation about: {request.topic}.

Break the topic down into 2-5 distinct scenes.
For each scene, provide:
1. A clear narration text that will be spoken via Text-to-Speech.
2. A detailed visual description of what should happen in the Manim CE animation. Be specific about shapes, text, formulas, and animations (e.g., FadeIn, Transform).
3. An estimated duration in seconds.

Return ONLY valid JSON in this exact format:
{{"title": "...", "scenes": [{{"scene_id": 1, "narration_text": "...", "visual_description": "...", "estimated_duration_seconds": 30}}]}}
"""

    try:
        # Trace LLM call
        llm_start = time.time()
        response = client.chat.completions.create(
            model=settings.SCRIPT_WRITER_MODEL,
            messages=[
                {"role": "system", "content": "You are an expert technical director for Manim animations. Always respond with valid JSON only."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            response_format={"type": "json_object"}
        )
        llm_duration = time.time() - llm_start
        
        # Log LLM trace
        if _tracer:
            try:
                _tracer.update_run(
                    run_id=run_id,
                    inputs={"prompt": prompt[:500]},
                    outputs={"response": response.choices[0].message.content[:500]},
                    metrics={"latency": llm_duration}
                )
            except Exception:
                pass

        script_data = ScriptResponse(**json.loads(response.choices[0].message.content))

        total_duration = time.time() - start_time
        
        # Final trace update
        if _tracer:
            try:
                _tracer.update_run(
                    run_id=run_id,
                    outputs={
                        "scenes": len(script_data.scenes),
                        "title": script_data.title
                    },
                    end_time=time.time(),
                    metrics={"total_latency": total_duration}
                )
            except Exception:
                pass

        logger.info(f"Script generated successfully with {len(script_data.scenes)} scenes.")
        return ScriptWriterResponse(script=script_data)

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
        logger.error(f"Error generating script: {str(e)}")
        raise e

@app.get("/health")
def health():
    return {"status": "ok"}
