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
from langsmith import traceable
from pathlib import Path
import httpx
import asyncio
import uuid
import time

app = FastAPI(title="Orchestrator Service")
app.add_middleware(make_request_logging_middleware("orchestrator"))
logger = get_logger(__name__)

# Job IDs with a live run_pipeline driver in THIS process. Prevents a job from
# being driven twice at once (e.g. the resume endpoint + the startup orphan
# scanner both firing on the same job), which races the graph and bounces status.
_DRIVING: set[str] = set()

# Job IDs the user asked to stop. The streaming loop checks this between graph
# nodes and aborts cleanly, persisting progress so the job can be resumed later.
_CANCEL: set[str] = set()


@app.on_event("startup")
async def _validate_config() -> None:
    # Fail fast on missing credentials rather than 401-ing under load.
    if not settings.NVIDIA_API_KEY:
        raise RuntimeError("NVIDIA_API_KEY is required but not set")


async def _resume_worker(jobs: list) -> None:
    """Resume orphaned jobs ONE AT A TIME.

    Resuming every orphan concurrently floods the downstream services (N jobs ×
    per-job fan-out of LLM/render calls) and can starve the event loop — observed
    stalling an in-flight job. Serial resume keeps the load of a restart equal to
    a single job. Newest first (list_running_jobs orders by updated_at DESC).
    """
    for job in jobs:
        st = job["state"]
        logger.info("Resuming orphaned job", extra={"job_id": job["job_id"], "status": st.get("status")})
        try:
            await run_pipeline(job["job_id"], st.get("topic", ""), st.get("brief"), resume_state=st)
        except Exception as e:
            logger.error("Resumed job failed", extra={"job_id": job["job_id"], "error": str(e)})


@app.on_event("startup")
async def _resume_running_jobs() -> None:
    """Re-launch jobs orphaned by a restart.

    Every graph node persists state to SQLite, but the asyncio task that drives
    the pipeline lives only in this process — a restart strands any in-flight job
    in its last-saved status. On boot, re-fire run_pipeline from that saved state;
    the nodes skip already-finished scenes so it picks up where it stopped.
    """
    try:
        running = db.list_running_jobs()
    except Exception as e:
        logger.error("Resume scan failed", extra={"error": str(e)})
        return
    if not running:
        return
    logger.info("Resuming orphaned jobs serially", extra={"count": len(running)})
    # One background driver processes the queue serially — never blocks startup,
    # never floods the fleet.
    asyncio.create_task(_resume_worker(running))


# LangSmith tracing is enabled via env (LANGSMITH_TRACING=true + LANGSMITH_API_KEY).
# @traceable no-ops when those are unset, so this is safe to leave on always.
@traceable(run_type="chain", name="orchestrator.pipeline")
async def run_pipeline(job_id: str, topic: str, brief: dict | None = None,
                       resume_state: LangGraphState | None = None):
    set_log_context(job_id=job_id)
    # Guard against a second concurrent driver for the same job.
    if job_id in _DRIVING:
        logger.warning("Pipeline already running for this job — skipping duplicate driver")
        return {"status": "already_running"}
    _DRIVING.add(job_id)
    logger.info("Pipeline starting", extra={"topic": topic, "resumed": resume_state is not None})

    start_time = time.time()

    # Resume from a persisted mid-flight state (orchestrator restart) or start
    # fresh. The graph nodes skip any scene already in render_paths/audio_paths,
    # so re-streaming a saved state fast-forwards to the first unfinished scene.
    initial_state: LangGraphState = resume_state or {
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
                # User pressed Stop: halt between nodes, preserving progress so the
                # job can be resumed. Raise CancelledError to unwind the stream.
                if job_id in _CANCEL:
                    _CANCEL.discard(job_id)
                    logger.info("Pipeline cancelled by user")
                    raise asyncio.CancelledError()
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
        # Returned value is captured as the trace's outputs by @traceable.
        return {"status": final_state.get("status"), "scenes": scene_count,
                "elapsed_s": round(elapsed, 2)}
    except asyncio.CancelledError:
        # User-initiated stop. Persist a 'cancelled' record that KEEPS progress
        # (renders/audio) so Resume can pick it back up. Don't re-raise — this is
        # a clean, expected stop, not a crash.
        logger.info("Pipeline stopped (cancelled)")
        db.update_job(job_id, {**last_state, "status": "cancelled",
                               "overall_error": "Stopped by user."})
        return {"status": "cancelled"}
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
        # Re-raise so the trace records the failure, not a silent success.
        raise
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error("Pipeline crashed", extra={"elapsed_s": round(elapsed, 2)}, exc_info=True)
        failed_state = {
            **last_state,
            "status": "failed",
            "overall_error": str(e),
        }
        db.update_job(job_id, failed_state)
        raise
    finally:
        _DRIVING.discard(job_id)
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

    # Carry the per-job render mode in the brief so it rides through job state
    # into the code-generator node without touching run_pipeline's signature.
    if request.render_mode:
        brief = dict(brief or {})
        brief["render_mode"] = request.render_mode

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


@app.post("/job/{job_id}/cancel", response_model=dict)
async def cancel_job(job_id: str):
    """Stop a running job. The streaming loop checks _CANCEL between graph nodes
    and halts cleanly, persisting progress so the job can be resumed."""
    state = db.get_job(job_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job_id not in _DRIVING:
        # No live driver — just mark it cancelled if it's still in a running state.
        if state.get("status") not in ("completed", "failed", "cancelled"):
            db.update_job(job_id, {**state, "status": "cancelled",
                                   "overall_error": "Stopped by user."})
        return {"job_id": job_id, "message": "Job not actively running; marked cancelled."}
    _CANCEL.add(job_id)
    return {"job_id": job_id, "message": "Stop requested."}


@app.delete("/job/{job_id}", response_model=dict)
async def delete_job(job_id: str):
    """Hard-delete a job record. Refuses if the job is actively running."""
    state = db.get_job(job_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job_id in _DRIVING:
        raise HTTPException(status_code=409, detail="Job is running; stop it first")
    db.delete_job(job_id)
    return {"job_id": job_id, "message": "Deleted."}


@app.post("/job/{job_id}/resume", response_model=dict)
async def resume_job(job_id: str, background_tasks: BackgroundTasks):
    """Re-run a failed/stalled job from its persisted state.

    The graph nodes skip scenes already in render_paths/audio_paths, so resuming
    re-does only unfinished work. Re-enter at 'validation' (a no-op when renders
    exist) so the run routes straight to whatever stage actually failed. Audio is
    KEPT — voiceover now runs pre-code and skips scenes already voiced, so clearing
    it just forces a needless re-narration of the whole film on every resume.
    """
    state = db.get_job(job_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Job not found")
    # Never double-drive: refuse if a driver is already live for this job, or if
    # the persisted status is a mid-pipeline running state.
    if job_id in _DRIVING:
        raise HTTPException(status_code=409, detail="Job is already running")
    if state.get("status") not in ("failed", "cancelled", "starting", "pending", "code_generation",
                                   "image_fetch", "voiceover", "validation", "voiceover_and_images",
                                   "assembly", "script_generation"):
        raise HTTPException(status_code=409, detail=f"Job is {state.get('status')}; cannot resume")

    state.pop("webhook_url", None)
    state["status"] = "validation"
    state["overall_error"] = None
    db.update_job(job_id, state)

    background_tasks.add_task(
        run_pipeline, job_id, state.get("topic", ""), state.get("brief"), state
    )
    return {"job_id": job_id, "message": "Resume started."}

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
