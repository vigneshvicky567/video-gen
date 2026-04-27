from fastapi import FastAPI, BackgroundTasks
from shared.schemas.common import GenerationRequest, JobState
from shared.models.agent_state import LangGraphState
from app.core.graph import app_graph
import uuid
import logging
import os
import time

# LangSmith Tracing
app = FastAPI(title="Orchestrator Service")
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

# In-memory store for demo. In production, use DB (e.g., PostgreSQL/Redis via shared/database)
jobs_db = {}

async def run_pipeline(job_id: str, topic: str):
    logger.info(f"Starting pipeline for job {job_id}")
    
    # Start LangSmith trace
    run_id = str(uuid.uuid4())
    start_time = time.time()
    
    if _tracer:
        try:
            _tracer.create_run(
                name="orchestrator.pipeline",
                run_type="chain",
                run_id=run_id,
                metadata={
                    "service": "orchestrator",
                    "job_id": job_id,
                    "topic": topic
                }
            )
        except Exception as e:
            logger.debug(f"LangSmith trace start failed: {e}")

    initial_state: LangGraphState = {
        "job_id": job_id,
        "topic": topic,
        "status": "pending",
        "script": None,
        "code_paths": {},
        "render_paths": {},
        "audio_paths": {},
        "retry_counts": {},
        "error_logs": {},
        "previous_code": {},
        "final_output_path": None,
        "overall_error": None
    }

    try:
        # We use ainvoke for asynchronous execution of the graph
        final_state = await app_graph.ainvoke(initial_state)
        jobs_db[job_id] = final_state
        
        total_duration = time.time() - start_time
        
        # Final trace update
        if _tracer:
            try:
                _tracer.update_run(
                    run_id=run_id,
                    outputs={
                        "status": final_state.get("status"),
                        "scenes": len(final_state.get("script", {}).get("scenes", [])) if final_state.get("script") else 0
                    },
                    end_time=time.time(),
                    metrics={"total_latency": total_duration}
                )
            except Exception:
                pass
        
        logger.info(f"Pipeline finished for job {job_id}. Final status: {final_state['status']}")
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
        
        logger.error(f"Pipeline crashed for job {job_id}: {e}")
        initial_state["status"] = "failed"
        initial_state["overall_error"] = str(e)
        jobs_db[job_id] = initial_state


@app.post("/generate", response_model=dict)
async def start_generation(request: GenerationRequest, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())

    # Initialize state
    jobs_db[job_id] = {
        "job_id": job_id,
        "topic": request.topic,
        "status": "starting"
    }

    # Start LangGraph pipeline in background
    background_tasks.add_task(run_pipeline, job_id, request.topic)

    return {"job_id": job_id, "message": "Generation started."}

@app.get("/job/{job_id}", response_model=dict)
async def get_job_status(job_id: str):
    if job_id not in jobs_db:
        return {"error": "Job not found"}
    return jobs_db[job_id]

@app.get("/health")
def health():
    return {"status": "ok"}
