from fastapi import FastAPI
from shared.schemas.requests import ScriptWriterRequest
from shared.schemas.responses import ScriptWriterResponse
from shared.schemas.common import ScriptResponse, AnalyzeRequest, TopicAnalysis
from shared.config import settings
from shared.llm_client import get_llm_client
from shared.log import get_logger, set_log_context, timed_block, log_llm_call, make_request_logging_middleware
from .analyzer import analyze_topic
from . import council
from langsmith import traceable
import json

app = FastAPI(title="Script Writer Service")
app.add_middleware(make_request_logging_middleware("script-writer"))
logger = get_logger(__name__)

client = get_llm_client()
logger.info("Script Writer ready", extra={"model": settings.SCRIPT_WRITER_MODEL})


@app.post("/generate", response_model=ScriptWriterResponse)
@traceable(run_type="chain", name="script-writer.generate")
async def generate_script(request: ScriptWriterRequest):
    set_log_context(job_id=getattr(request, "job_id", ""))
    logger.info("Generating script", extra={"topic": request.topic, "model": settings.SCRIPT_WRITER_MODEL})

    brief = request.brief.model_dump() if request.brief else None

    try:
        script_data, meta = await council.generate_script(request.topic, brief, client)

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
        logger.error(f"Error generating script: {str(e)}")
        raise e


@app.post("/analyze", response_model=TopicAnalysis)
@traceable(run_type="chain", name="script-writer.analyze")
async def analyze(request: AnalyzeRequest):
    """Pre-submit topic analysis: feasibility + questionnaire. Stateless, no job."""
    set_log_context(job_id="")
    logger.info("Analyzing topic", extra={"topic": request.topic})
    return await analyze_topic(request.topic, client)


@app.get("/health")
def health():
    return {"status": "ok"}
