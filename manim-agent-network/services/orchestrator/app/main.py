from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from shared.schemas.common import GenerationRequest, JobState, AnalyzeRequest, TopicAnalysis
from shared.models.agent_state import LangGraphState
from shared.config import settings
from shared.log import get_logger, set_log_context, clear_log_context, make_request_logging_middleware
from shared.timeouts import job_wallclock_timeout_s
from app.core.graph import app_graph
from app.db import db
from pathlib import Path
import httpx
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

async def run_pipeline(job_id: str, topic: str, brief: dict | None = None):
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
        "brief": brief, "script_meta": None,
    }

    timeout_s = job_wallclock_timeout_s((brief or {}).get("target_duration_seconds"))

    # Track the latest streamed state at run_pipeline scope so a timeout/crash
    # mid-stream can persist a 'failed' record that PRESERVES progress (script,
    # render_paths, ...) instead of clobbering it with the empty initial_state.
    # Copy so a node mutating state in-place before its first yield can't alias
    # back onto initial_state.
    last_state: LangGraphState = dict(initial_state)

    try:
        async def _run_streaming():
            # Persist state after every graph node so /job/{id} reflects live progress.
            nonlocal last_state
            async for state in app_graph.astream(initial_state, stream_mode="values"):
                last_state = state
                db.update_job(job_id, state)
            return last_state

        final_state = await asyncio.wait_for(
            _run_streaming(),
            timeout=timeout_s,
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
                     "timeout_s": timeout_s})
        failed_state = {
            **last_state,
            "status": "failed",
            "overall_error": f"Job exceeded wall-clock timeout of {timeout_s}s",
        }
        db.update_job(job_id, failed_state)
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
        failed_state = {
            **last_state,
            "status": "failed",
            "overall_error": str(e),
        }
        db.update_job(job_id, failed_state)
    finally:
        clear_log_context()


@app.post("/analyze", response_model=TopicAnalysis)
async def analyze_topic_endpoint(request: AnalyzeRequest):
    """Stateless proxy to the script-writer analyzer. Creates NO job row.

    The browser only reaches the orchestrator origin, so the public endpoint
    lives here while the LLM call lives in the script-writer container.
    """
    async with httpx.AsyncClient(timeout=90.0) as client:
        resp = await client.post(
            f"{settings.SCRIPT_WRITER_URL}/analyze", json=request.model_dump()
        )
        resp.raise_for_status()
        return resp.json()


@app.post("/generate", response_model=dict)
async def start_generation(request: GenerationRequest, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())

    # Brief is optional — legacy {"topic": "..."} bodies stay valid forever.
    brief = request.brief.model_dump() if request.brief else None
    if brief and brief.get("max_duration_seconds"):
        # Fail-soft clamp, never 422: respect the analyzer's ceiling.
        brief["target_duration_seconds"] = min(
            brief["target_duration_seconds"], brief["max_duration_seconds"]
        )

    # Durable initial record so /job survives an orchestrator restart.
    db.create_job(job_id, request.topic, {
        "job_id": job_id,
        "topic": request.topic,
        "status": "starting",
        "brief": brief,
    })

    # Start LangGraph pipeline in background
    background_tasks.add_task(run_pipeline, job_id, request.topic, brief)

    return {"job_id": job_id, "message": "Generation started."}

@app.get("/job/{job_id}", response_model=dict)
async def get_job_status(job_id: str):
    state = db.get_job(job_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return state

@app.get("/jobs", response_model=list)
async def list_jobs(status: str | None = None, limit: int = 100):
    return db.list_jobs(status=status, limit=min(limit, 200))


def _safe_workspace_file(path_str: str) -> Path:
    """Resolve a workspace path, rejecting anything outside /workspace."""
    workspace = Path("/workspace").resolve()
    resolved = Path(path_str).resolve()
    if not resolved.is_relative_to(workspace):
        raise HTTPException(status_code=403, detail="Path outside workspace")
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return resolved


@app.get("/video/{job_id}")
async def get_video(job_id: str):
    state = db.get_job(job_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Job not found")
    path = state.get("final_output_path")
    if not path:
        raise HTTPException(status_code=404, detail="Video not ready")
    return FileResponse(_safe_workspace_file(path), media_type="video/mp4",
                        filename=f"{job_id}.mp4")


@app.get("/video/{job_id}/scene/{scene_id}")
async def get_scene_video(job_id: str, scene_id: str):
    state = db.get_job(job_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Job not found")
    path = (state.get("render_paths") or {}).get(scene_id)
    if not path:
        raise HTTPException(status_code=404, detail="Scene render not found")
    return FileResponse(_safe_workspace_file(path), media_type="video/mp4")


_SERVICE_HEALTH_URLS = {
    "orchestrator": None,  # self
    "script-writer": settings.SCRIPT_WRITER_URL,
    "code-generator": settings.CODE_GENERATOR_URL,
    "validator": settings.VALIDATOR_URL,
    "voiceover": settings.VOICEOVER_URL,
    "compositor": settings.ASSEMBLER_URL,
    "image-fetcher": settings.IMAGE_FETCHER_URL,
}


@app.get("/services/health")
async def services_health():
    """Proxy health checks so the browser can see the whole fleet from one origin."""
    async def check(name: str, base_url: str | None):
        if base_url is None:
            return name, {"status": "ok", "latency_ms": 0}
        start = time.time()
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{base_url}/health")
            ok = resp.status_code == 200
            return name, {
                "status": "ok" if ok else "degraded",
                "latency_ms": round((time.time() - start) * 1000),
            }
        except Exception:
            return name, {"status": "down", "latency_ms": None}

    results = await asyncio.gather(*(check(n, u) for n, u in _SERVICE_HEALTH_URLS.items()))
    return dict(results)


@app.get("/health")
def health():
    return {"status": "ok"}


# Serve the frontend (mounted last so API routes take precedence).
if Path("/frontend").is_dir():
    app.mount("/", StaticFiles(directory="/frontend", html=True), name="frontend")
