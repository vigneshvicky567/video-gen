from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
import re as _re
from shared.schemas.common import GenerationRequest, JobState, AnalyzeRequest, TopicAnalysis
from shared.models.agent_state import LangGraphState
from shared.config import settings
from shared.log import get_logger, set_log_context, clear_log_context, make_request_logging_middleware
from shared.timeouts import job_wallclock_timeout_s
from app.core.graph import app_graph
from app.db import db
from shared.llm_client import get_llm_client
from langsmith import traceable
from pydantic import BaseModel
from pathlib import Path
import httpx
import asyncio
import uuid
import time
import os

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
    # Either provider's key satisfies it — slots may route to NIM or Claude.
    if not settings.NVIDIA_API_KEY and not settings.ANTHROPIC_API_KEY:
        raise RuntimeError("No LLM key set: need NVIDIA_API_KEY or ANTHROPIC_API_KEY")


async def _resume_worker(jobs: list) -> None:
    """Resume orphaned jobs ONE AT A TIME.

    Resuming every orphan concurrently floods the downstream services (N jobs ×
    per-job fan-out of LLM/render calls) and can starve the event loop — observed
    stalling an in-flight job. Serial resume keeps the load of a restart equal to
    a single job. Newest first (list_running_jobs orders by updated_at DESC).
    """
    for job in jobs:
        st = job["state"]
        job_id = job["job_id"]
        # Assembly already completed but status was never written (crash between
        # assembler_node return and the final db.update_job call). Auto-heal:
        # mark completed/partial and skip re-driving the pipeline — but ONLY if the
        # file is actually present and non-empty. A truthy path pointing at a
        # missing/zero-byte file (crash mid-write, cleaned volume) must NOT be
        # healed to "completed"; fall through and re-drive the pipeline instead.
        final_path = st.get("final_output_path")
        if final_path and os.path.exists(final_path) and os.path.getsize(final_path) > 0:
            final_status = "partial" if st.get("dropped_scenes") else "completed"
            logger.info("Auto-healing assembled job with stale status",
                        extra={"job_id": job_id, "corrected_status": final_status})
            db.update_job(job_id, {**st, "status": final_status})
            _DRIVING.discard(job_id)  # Pre-claimed by _resume_running_jobs; release since we skip run_pipeline
            continue
        if final_path:
            logger.warning("Orphan job has final_output_path but file is missing/empty — re-driving",
                           extra={"job_id": job_id, "path": final_path})
        logger.info("Resuming orphaned job", extra={"job_id": job_id, "status": st.get("status")})
        # Reset retry state so scenes that hit the limit before the crash get
        # fresh attempts — same logic as the /resume endpoint. render_paths is
        # kept so already-rendered scenes are not re-done.
        st["retry_counts"] = {}
        st["infra_retry_counts"] = {}
        st["error_logs"] = {}
        st["code_paths"] = {}
        try:
            # _slot_preclaimed=True: _resume_running_jobs already added job_id to
            # _DRIVING before the event loop could accept /resume requests, so we
            # skip the internal check+add in run_pipeline.
            await run_pipeline(job_id, st.get("topic", ""), st.get("brief"),
                               resume_state=st, _slot_preclaimed=True)
        except Exception as e:
            logger.error("Resumed job failed", extra={"job_id": job_id, "error": str(e)})


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
    # Pre-claim _DRIVING for all orphaned jobs BEFORE yielding to the event loop.
    # Without this, a /resume request arriving between create_task() and the first
    # run_pipeline() execution would pass the _DRIVING guard and double-drive the job.
    for job in running:
        _DRIVING.add(job["job_id"])
    asyncio.create_task(_resume_worker(running))


# LangSmith tracing is enabled via env (LANGSMITH_TRACING=true + LANGSMITH_API_KEY).
# @traceable no-ops when those are unset, so this is safe to leave on always.
@traceable(run_type="chain", name="orchestrator.pipeline")
async def run_pipeline(job_id: str, topic: str, brief: dict | None = None,
                       resume_state: LangGraphState | None = None,
                       _slot_preclaimed: bool = False):
    set_log_context(job_id=job_id)
    # Guard against a second concurrent driver for the same job.
    # If the caller pre-claimed the slot (added to _DRIVING before scheduling),
    # skip the check+add here — the slot is already held.
    if not _slot_preclaimed:
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
        "retry_counts": {}, "infra_retry_counts": {}, "error_logs": {},
        "error_history": {}, "previous_code": {},
        "final_output_path": None, "overall_error": None,
        "brief": brief, "script_meta": None,
        "eta_seconds": None, "stage_timings": {}, "node_timings": [],
    }

    timeout_s = job_wallclock_timeout_s((brief or {}).get("target_duration_seconds"))

    # Ordered pipeline stages for ETA computation. Maps status name → position.
    _STAGE_ORDER = [
        "script_generation",
        "code_generation",
        "validation",
        "voiceover_and_images",
        "voiceover",
        "image_fetch",
        "assembly",
    ]
    # Normalise aliases: voiceover-only and image_fetch-only both stand in for
    # voiceover_and_images for ETA purposes (same position in the pipeline).
    _STAGE_ETA_KEY = {s: s for s in _STAGE_ORDER}
    _STAGE_ETA_KEY["voiceover"] = "voiceover_and_images"
    _STAGE_ETA_KEY["image_fetch"] = "voiceover_and_images"

    # Track the latest streamed state at run_pipeline scope so a timeout/crash
    # mid-stream can persist a 'failed' record that PRESERVES progress (script,
    # render_paths, ...) instead of clobbering it with the empty initial_state.
    # Copy so a node mutating state in-place before its first yield can't alias
    # back onto initial_state.
    last_state: LangGraphState = dict(initial_state)

    # Stage timing tracking (in-memory during the run).
    _stage_start: dict[str, float] = {}   # stage -> wall-clock start
    _stage_done: dict[str, float] = {}    # stage -> elapsed seconds
    _prev_status: str | None = None

    def _scene_count(st: dict) -> int:
        return len((st.get("script") or {}).get("scenes", []))

    def _compute_eta(st: dict) -> float | None:
        """Remaining seconds estimate from historical stage means + current progress."""
        current = st.get("status", "")
        n_scenes = _scene_count(st)
        now = time.time()

        # Position of current stage in the ordered list (use alias key).
        canonical = _STAGE_ETA_KEY.get(current, current)
        try:
            cur_idx = _STAGE_ORDER.index(canonical)
        except ValueError:
            return None  # pre-script or terminal status — no estimate

        # Remaining in the current stage: mean - already spent, floored at 0.
        eta = 0.0
        stage_elapsed = now - _stage_start.get(current, now)
        mean_cur = db.get_stage_mean(canonical, n_scenes)
        if mean_cur is not None:
            eta += max(0.0, mean_cur - stage_elapsed)

        # Full means for each stage not yet started.
        for stage in _STAGE_ORDER[cur_idx + 1:]:
            mean = db.get_stage_mean(stage, n_scenes)
            if mean is not None:
                eta += mean

        return eta if (mean_cur is not None or eta > 0) else None

    try:
        async def _run_streaming():
            nonlocal last_state, _prev_status
            async for state in app_graph.astream(initial_state, stream_mode="values"):
                last_state = state
                current_status = state.get("status", "")
                now = time.time()

                # Detect stage transition → record completed stage duration.
                if current_status != _prev_status:
                    if _prev_status and _prev_status in _stage_start:
                        _stage_done[_STAGE_ETA_KEY.get(_prev_status, _prev_status)] = (
                            now - _stage_start[_prev_status]
                        )
                    _stage_start[current_status] = now
                    _prev_status = current_status

                # Compute and inject backend ETA into every state write.
                eta = _compute_eta(state)
                enriched = {**state, "eta_seconds": eta, "stage_timings": dict(_stage_done)}
                db.update_job(job_id, enriched)
                last_state = enriched

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
        n_scenes = _scene_count(final_state)
        logger.info(
            "Pipeline finished",
            extra={"status": final_state["status"], "scenes": n_scenes,
                   "elapsed_s": round(elapsed, 2)},
        )

        # Persist per-stage actuals to stage_stats for future ETA predictions.
        # Record the final stage too (assembler → completed transition).
        if _prev_status and _prev_status in _stage_start:
            _stage_done[_STAGE_ETA_KEY.get(_prev_status, _prev_status)] = (
                time.time() - _stage_start[_prev_status]
            )
        for stage, elapsed_s in _stage_done.items():
            try:
                db.record_stage_timing(stage, elapsed_s, n_scenes)
            except Exception:
                pass  # never let stats writes crash a completed job

        return {"status": final_state.get("status"), "scenes": n_scenes,
                "elapsed_s": round(elapsed, 2)}
    except asyncio.CancelledError:
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
        # Do NOT re-raise: run_pipeline executes inside BackgroundTasks where an
        # exception has no handler — it would only produce an unhandled-task
        # traceback after the failure is already persisted above.
        return {"status": "failed", "reason": "wallclock_timeout"}
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error("Pipeline crashed", extra={"elapsed_s": round(elapsed, 2)}, exc_info=True)
        failed_state = {
            **last_state,
            "status": "failed",
            "overall_error": str(e),
        }
        db.update_job(job_id, failed_state)
        return {"status": "failed", "reason": "crash"}
    finally:
        _DRIVING.discard(job_id)
        _CANCEL.discard(job_id)
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

    # Pre-claim the driving slot BEFORE scheduling the background task.
    # Without this, a concurrent /resume (or startup re-drive) could pass the
    # _DRIVING guard in run_pipeline before the task starts executing.
    _DRIVING.add(job_id)
    background_tasks.add_task(run_pipeline, job_id, request.topic, brief,
                               _slot_preclaimed=True)

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
        if state.get("status") not in ("completed", "partial", "failed", "cancelled"):
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
    if state.get("status") not in ("failed", "partial", "cancelled", "starting", "pending", "code_generation",
                                   "image_fetch", "voiceover", "validation", "resuming",
                                   "assembly", "script_generation"):
        raise HTTPException(status_code=409, detail=f"Job is {state.get('status')}; cannot resume")

    # Pre-claim slot BEFORE scheduling — eliminates TOCTOU race where startup
    # _resume_running_jobs or a second /resume request slips past the guard above
    # before the background task actually starts executing run_pipeline.
    _DRIVING.add(job_id)

    state.pop("webhook_url", None)
    # Neutral status: the graph's resume-safe skips (script present, renders
    # present, audio present) decide where work actually restarts — faking a
    # mid-pipeline status here only confuses the stage tracker/ETA.
    state["status"] = "resuming"
    state["overall_error"] = None
    # Reset per-scene retry counters so every scene gets another full budget.
    # Without this, a job that exhausted all retries would immediately route to
    # "failed" again — code_generator_node filters out any exhausted scene,
    # validator has nothing, validation_router → failed. Same for code_paths:
    # stale failed-code entries prevent fresh generation. previous_code is KEPT —
    # it is the retry context that makes the next attempt better than the last.
    state["retry_counts"] = {}
    state["infra_retry_counts"] = {}
    state["error_logs"] = {}
    state["code_paths"] = {}
    db.update_job(job_id, state)

    background_tasks.add_task(
        run_pipeline, job_id, state.get("topic", ""), state.get("brief"), state,
        True  # _slot_preclaimed
    )
    return {"job_id": job_id, "message": "Resume started."}

@app.get("/jobs", response_model=list)
async def list_jobs(status: str | None = None, limit: int = 100):
    return db.list_jobs(status=status, limit=min(limit, 200))


class ChatTurn(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    question: str
    context: str = ""          # transcript excerpt for the section the viewer is on
    history: list[ChatTurn] = []
    job_topic: str | None = None


@app.post("/chat", response_model=dict)
async def chat(req: ChatRequest):
    """Grounded mini-chat for the watch page. The frontend sends the transcript
    slice for the section the viewer is watching (or a range they marked); the
    answer is grounded on THAT excerpt, not the whole film. Reuses the NIM client."""
    q = (req.question or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="Empty question")
    excerpt = (req.context or "").strip()
    system = (
        "You help a viewer understand the video they are watching. "
        f"The film is about: {req.job_topic or 'unknown topic'}.\n"
        "They are asking about THIS portion of the narration (the part on screen):\n"
        f'"""\n{excerpt or "(no transcript available for this section)"}\n"""\n'
        "Answer using this excerpt as the primary source; you may add brief general "
        "explanation to make it clear. If the excerpt does not cover the question, say "
        "you can only see the part they are currently watching and suggest they scrub to "
        "that moment or mark a range. Keep it to 2-4 plain sentences. No markdown headers."
    )
    messages = [{"role": "system", "content": system}]
    for t in req.history[-6:]:
        if t.role in ("user", "assistant") and t.content:
            messages.append({"role": t.role, "content": t.content})
    messages.append({"role": "user", "content": q})
    try:
        client = get_llm_client()
        resp = await client.chat.completions.acreate(
            model=settings.CHAT_MODEL, messages=messages,
            max_tokens=500, temperature=0.3,
        )
        reply = (resp.choices[0].message.content or "").strip()
    except Exception as e:
        logger.error("Chat failed", extra={"error": str(e)})
        raise HTTPException(status_code=502, detail="Chat backend error")
    return {"reply": reply or "(no answer)"}


def _safe_workspace_file(path_str: str) -> Path:
    """Resolve a workspace path, rejecting anything outside the workspace dir."""
    # Jail root must match where producers actually write (settings.WORKSPACE_DIR),
    # not a hardcoded "/workspace" — otherwise a relocated workspace 403s every file.
    workspace = Path(settings.WORKSPACE_DIR).resolve()
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


def _shift_vtt(content: str, offset_s: float) -> str:
    """Shift all VTT timestamps forward by offset_s seconds (intro prepended to final video)."""
    def _parse(ts: str) -> float:
        parts = ts.split(":")
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        return int(parts[0]) * 60 + float(parts[1])

    def _fmt(secs: float) -> str:
        h = int(secs // 3600); m = int((secs % 3600) // 60); s = secs % 60
        return f"{h:02d}:{m:02d}:{s:06.3f}"

    def _sub(m):
        return f"{_fmt(_parse(m.group(1)) + offset_s)} --> {_fmt(_parse(m.group(2)) + offset_s)}"

    TS = r"(\d+(?::\d+)?:\d+\.\d+)"
    return _re.sub(rf"{TS}\s*-->\s*{TS}", _sub, content)


@app.get("/captions/{job_id}")
async def get_captions(job_id: str):
    """Serve WebVTT shifted by intro_duration_seconds so captions sync with the final
    video (which has the intro clip prepended before the narration content)."""
    state = db.get_job(job_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Job not found")
    path = state.get("final_output_path")
    if not path:
        raise HTTPException(status_code=404, detail="Captions not ready")
    vtt_path = _safe_workspace_file(str(Path(path).with_name(f"{job_id}.vtt")))
    intro_offset = float(state.get("intro_duration_seconds") or 0)
    if intro_offset <= 0:
        return FileResponse(vtt_path, media_type="text/vtt", filename=f"{job_id}.vtt")
    try:
        content = Path(vtt_path).read_text(encoding="utf-8")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Caption file not found")
    shifted = _shift_vtt(content, intro_offset)
    return Response(content=shifted, media_type="text/vtt",
                    headers={"Content-Disposition": f'inline; filename="{job_id}.vtt"'})


@app.get("/thumbnail/{job_id}")
async def get_thumbnail(job_id: str):
    """Extract and cache a single JPEG frame from the final video, seeked past the
    intro so the library card shows real content. Generated once, served forever."""
    import subprocess, asyncio
    state = db.get_job(job_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Job not found")
    path = state.get("final_output_path")
    if not path:
        raise HTTPException(status_code=404, detail="Video not ready")
    video_path = Path(_safe_workspace_file(path))
    thumb_path = video_path.with_name(f"{job_id}_thumb.jpg")
    if not thumb_path.exists():
        intro_offset = float(state.get("intro_duration_seconds") or 0)
        seek_s = intro_offset + 5.0
        cmd = [
            "ffmpeg", "-y", "-ss", str(seek_s),
            "-i", str(video_path),
            "-vframes", "1", "-q:v", "4",
            "-vf", "scale=480:-2",
            str(thumb_path),
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            await asyncio.wait_for(proc.communicate(), timeout=30)
        except Exception as e:
            logger.warning("Thumbnail generation failed", extra={"job_id": job_id, "error": str(e)})
            raise HTTPException(status_code=500, detail="Thumbnail generation failed")
        if not thumb_path.exists():
            raise HTTPException(status_code=500, detail="Thumbnail generation failed")
    return FileResponse(str(thumb_path), media_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=31536000, immutable"})


@app.get("/video/{job_id}/scene/{scene_id}")
async def get_scene_video(job_id: str, scene_id: int):
    # scene_id typed int: render_paths is int-keyed (db revives JSON str keys);
    # a str path param could never match and every lookup 404'd.
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


# --- admin (no auth — dev only) ----------------------------------------------
@app.get("/admin/jobs")
def admin_jobs():
    return db.list_jobs(limit=200)


@app.get("/admin/analytics")
def admin_analytics():
    jobs = db.list_jobs(limit=1000)
    by_status: dict[str, int] = {}
    for j in jobs:
        s = j.get("status", "unknown")
        by_status[s] = by_status.get(s, 0) + 1
    return {"total": len(jobs), "by_status": by_status, "month": "", "minutes_used": 0, "minute_budget": 0}


@app.get("/admin/users")
def admin_users():
    return []


@app.get("/admin/cost")
def admin_cost():
    jobs = db.list_jobs(limit=1000)
    active = sum(1 for j in jobs if j.get("status") in ("running", "starting", "queued"))
    return {"month": "", "minutes_used": 0, "minute_budget": 0, "minutes_remaining": 0,
            "active_jobs": active, "global_concurrency_cap": 0, "daily_job_quota_default": 0}


# Serve the frontend (mounted last so API routes take precedence).
if Path("/frontend").is_dir():
    app.mount("/", StaticFiles(directory="/frontend", html=True), name="frontend")
