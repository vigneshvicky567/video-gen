from fastapi import FastAPI
from shared.schemas.requests import ScriptWriterRequest
from shared.schemas.responses import ScriptWriterResponse
from shared.schemas.common import ScriptResponse, AnalyzeRequest, TopicAnalysis
from shared.config import settings
from shared.llm_client import get_llm_client
from shared.log import get_logger, set_log_context, timed_block, log_llm_call, make_request_logging_middleware
from .analyzer import analyze_topic
from . import council
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
        except Exception as _trace_exc:
            logger.debug(f"LangSmith trace failed: {_trace_exc}")

    brief = request.brief.model_dump() if request.brief else None

    try:
        script_data, meta = await council.generate_script(request.topic, brief, client)

        total_duration = time.time() - start_time
        if _tracer:
            try:
                _tracer.update_run(run_id=run_id,
                    outputs={"scenes": len(script_data.scenes), "title": script_data.title,
                             "mode": meta.get("mode")},
                    end_time=time.time(), metrics={"total_latency": total_duration})
            except Exception as _trace_exc:
                logger.debug(f"LangSmith trace failed: {_trace_exc}")

        logger.info(
            "Script generated",
            extra={"title": script_data.title, "scenes": len(script_data.scenes),
                   "mode": meta.get("mode"),
                   "audit": meta.get("duration_audit"),
                   "types": [s.content_type for s in script_data.scenes]},
        )
        for s in script_data.scenes:
            logger.info("  scene plan", extra={"scene_id": s.scene_id, "type": s.content_type,
                                               "duration_s": s.estimated_duration_seconds,
                                               "narration_preview": s.narration_text[:60]})

        return ScriptWriterResponse(script=script_data, meta=meta)

    except Exception as e:
        total_duration = time.time() - start_time
        if _tracer:
            try:
                _tracer.update_run(run_id=run_id, error=str(e),
                    end_time=time.time(), metrics={"total_latency": total_duration})
            except Exception as _trace_exc:
                logger.debug(f"LangSmith trace failed: {_trace_exc}")
        logger.error(f"Error generating script: {str(e)}")
        raise e


@app.post("/analyze", response_model=TopicAnalysis)
async def analyze(request: AnalyzeRequest):
    """Pre-submit topic analysis: feasibility + questionnaire. Stateless, no job."""
    set_log_context(job_id="")
    logger.info("Analyzing topic", extra={"topic": request.topic})
    return await analyze_topic(request.topic, client)


@app.get("/health")
def health():
    return {"status": "ok"}
