from fastapi import FastAPI, BackgroundTasks, HTTPException
from shared.schemas.common import GenerationRequest, JobState
from shared.models.agent_state import LangGraphState
from shared.config import settings
from shared.log import get_logger, set_log_context, clear_log_context, make_request_logging_middleware
from app.core.graph import app_graph
from app.db import db
import asyncio
import uuid
import os
import time

app = FastAPI(title="Orchestrator Service")
app.add_middleware(make_request_logging_middleware("orchestrator"))
logger = get_logger(__name__)


@app.on_event("startup")
async def _validate_config() -> None:
    # Fail fast on missing credentials rather than 401-ing under load.
    if not settings.NVIDIA_API_KEY:
        raise RuntimeError("NVIDIA_API_KEY is required but not set")

_tracer = None
if os.getenv("LANGSMITH_API_KEY"):
    try:
        import langsmith
        langsmith_client = langsmith.Client()
        _tracer = langsmith_client
        logger.info("LangSmith tracing enabled")
    except ImportError:
        logger.warning("langsmith not installed, tracing disabled")

async def run_pipeline(job_id: str, topic: str):
    set_log_context(job_id=job_id)
    logger.info("Pipeline starting", extra={"topic": topic})

    run_id = str(uuid.uuid4())
    start_time = time.time()

    if _tracer:
        try:
            _tracer.create_run(
                name="orchestrator.pipeline", run_type="chain", run_id=run_id,
                metadata={"service": "orchestrator", "job_id": job_id, "topic": topic}
            )
        except Exception as e:
            logger.debug(f"LangSmith trace start failed: {e}")

    initial_state: LangGraphState = {
        "job_id": job_id, "topic": topic, "status": "pending",
        "script": None, "code_paths": {}, "render_paths": {}, "audio_paths": {},
        "image_paths": {},
        "retry_counts": {}, "error_logs": {}, "previous_code": {},
        "final_output_path": None, "overall_error": None,
    }

    try:
        final_state = await asyncio.wait_for(
            app_graph.ainvoke(initial_state),
            timeout=settings.JOB_WALLCLOCK_TIMEOUT_SECONDS,
        )
        db.update_job(job_id, final_state)
        elapsed = time.time() - start_time
        scene_count = len((final_state.get("script") or {}).get("scenes", []))
        logger.info(
            "Pipeline finished",
            extra={"status": final_state["status"], "scenes": scene_count, "elapsed_s": round(elapsed, 2)},
        )
        if _tracer:
            try:
                _tracer.update_run(run_id=run_id,
                    outputs={"status": final_state.get("status"), "scenes": scene_count},
                    end_time=time.time(), metrics={"total_latency": elapsed})
            except Exception:
                pass
    except asyncio.TimeoutError:
        elapsed = time.time() - start_time
        logger.error("Pipeline timed out", extra={"elapsed_s": round(elapsed, 2),
                     "timeout_s": settings.JOB_WALLCLOCK_TIMEOUT_SECONDS})
        initial_state["status"] = "failed"
        initial_state["overall_error"] = (
            f"Job exceeded wall-clock timeout of {settings.JOB_WALLCLOCK_TIMEOUT_SECONDS}s"
        )
        db.update_job(job_id, initial_state)
        if _tracer:
            try:
                _tracer.update_run(run_id=run_id, error="wall-clock timeout",
                    end_time=time.time(), metrics={"total_latency": elapsed})
            except Exception:
                pass
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error("Pipeline crashed", extra={"elapsed_s": round(elapsed, 2)}, exc_info=True)
        if _tracer:
            try:
                _tracer.update_run(run_id=run_id, error=str(e),
                    end_time=time.time(), metrics={"total_latency": elapsed})
            except Exception:
                pass
        initial_state["status"] = "failed"
        initial_state["overall_error"] = str(e)
        db.update_job(job_id, initial_state)
    finally:
        clear_log_context()


@app.post("/generate", response_model=dict)
async def start_generation(request: GenerationRequest, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())

    # Durable initial record so /job survives an orchestrator restart.
    db.create_job(job_id, request.topic, {
        "job_id": job_id,
        "topic": request.topic,
        "status": "starting",
    })

    # Start LangGraph pipeline in background
    background_tasks.add_task(run_pipeline, job_id, request.topic)

    return {"job_id": job_id, "message": "Generation started."}

@app.get("/job/{job_id}", response_model=dict)
async def get_job_status(job_id: str):
    state = db.get_job(job_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return state

@app.get("/health")
def health():
    return {"status": "ok"}
