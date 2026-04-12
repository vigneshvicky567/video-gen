from fastapi import FastAPI, BackgroundTasks, Depends
from shared.schemas.common import GenerationRequest, JobState
from shared.models.agent_state import LangGraphState
from services.orchestrator.app.core.graph import app_graph
import uuid
import logging
from shared.database.core import get_session, init_db
from shared.database.models import JobRecord
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from contextlib import asynccontextmanager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield

app = FastAPI(title="Orchestrator Service", lifespan=lifespan)


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
        "previous_code_paths": {},
        "final_output_path": None,
        "overall_error": None
    }

    from shared.database.core import async_session_maker
    async with async_session_maker() as session:
        try:
            # We use ainvoke for asynchronous execution of the graph
            final_state = await app_graph.ainvoke(initial_state)

            # Update DB
            record = await session.get(JobRecord, job_id)
            if record:
                record.status = final_state['status']
                record.state = final_state
                if final_state.get('overall_error'):
                    record.overall_error = final_state['overall_error']
                await session.commit()

            logger.info(f"Pipeline finished for job {job_id}. Final status: {final_state['status']}")
        except Exception as e:
            logger.error(f"Pipeline crashed for job {job_id}: {e}")
            record = await session.get(JobRecord, job_id)
            if record:
                 record.status = "failed"
                 record.overall_error = str(e)
                 initial_state["status"] = "failed"
                 initial_state["overall_error"] = str(e)
                 record.state = initial_state
                 await session.commit()


@app.post("/generate", response_model=dict)
async def start_generation(
    request: GenerationRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session)
):
    job_id = str(uuid.uuid4())

    # Initialize state in DB
    job_record = JobRecord(
        job_id=job_id,
        topic=request.topic,
        status="starting",
        state={}
    )
    session.add(job_record)
    await session.commit()

    # Start LangGraph pipeline in background
    background_tasks.add_task(run_pipeline, job_id, request.topic)

    return {"job_id": job_id, "message": "Generation started."}

@app.get("/job/{job_id}", response_model=dict)
async def get_job_status(job_id: str, session: AsyncSession = Depends(get_session)):
    record = await session.get(JobRecord, job_id)
    if not record:
        return {"error": "Job not found"}
    return {"job_id": record.job_id, "status": record.status, "topic": record.topic, "state": record.state, "overall_error": record.overall_error}

@app.get("/health")
def health():
    return {"status": "ok"}
