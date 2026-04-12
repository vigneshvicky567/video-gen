from fastapi import FastAPI, BackgroundTasks
from shared.schemas.common import GenerationRequest, JobState
from shared.models.agent_state import LangGraphState
from app.core.graph import app_graph
import uuid
import logging

app = FastAPI(title="Orchestrator Service")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# In-memory store for demo. In production, use DB (e.g., PostgreSQL/Redis via shared/database)
jobs_db = {}

async def run_pipeline(job_id: str, topic: str):
    logger.info(f"Starting pipeline for job {job_id}")

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
        logger.info(f"Pipeline finished for job {job_id}. Final status: {final_state['status']}")
    except Exception as e:
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
