import os
import uuid
import httpx
import asyncio
from typing import Dict, Any, List
from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends
from pydantic import BaseModel
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from services.shared.models import PipelineState, SceneData
from services.shared.database import init_db, get_session, PipelineJob, DATABASE_URL


app = FastAPI(title="Orchestrator Service")

# Service URLs (mapped from docker-compose)
SERVICES = {
    "script_writer": "http://script_writer:8001",
    "manim_generator": "http://manim_generator:8002",
    "validator": "http://validator:8003",
    "voiceover": "http://voiceover:8004",
    "assembler": "http://assembler:8005",
    "quality_review": "http://quality_review:8006",
}

class GenerationRequest(BaseModel):
    prompt: str

# ---------------------------------------------------------
# LangGraph Nodes Definition
# ---------------------------------------------------------

async def node_script_writer(state: PipelineState) -> PipelineState:
    print(f"-> node_script_writer for: {state.user_prompt}")
    async with httpx.AsyncClient(timeout=120) as client:
        try:
            resp = await client.post(f"{SERVICES['script_writer']}/generate_script", json={"prompt": state.user_prompt})
            resp.raise_for_status()
            data = resp.json()
            # Convert dicts back to SceneData objects
            scenes = [SceneData(**s) for s in data.get("scenes", [])]
            state.scenes = scenes
            state.status = "script_generated"
        except Exception as e:
            state.global_errors.append(f"ScriptWriter failed: {str(e)}")
            state.status = "failed"
    return state

async def node_generate_code(state: PipelineState) -> PipelineState:
    print(f"-> node_generate_code. Scenes count: {len(state.scenes)}")

    async def process_scene(scene: SceneData, client: httpx.AsyncClient):
        if scene.status == "validated":
            return scene

        try:
            payload = {
                "scene_id": scene.scene_id,
                "description": scene.description,
                "narration": scene.narration,
                "previous_script_path": scene.script_path,
                "error_logs": scene.errors[-1] if scene.errors else None
            }
            resp = await client.post(f"{SERVICES['manim_generator']}/generate_code", json=payload)
            resp.raise_for_status()
            scene.script_path = resp.json().get("script_path")
            scene.status = "code_generated"
        except Exception as e:
            scene.errors.append(f"CodeGen failed: {str(e)}")
        return scene

    async with httpx.AsyncClient(timeout=120) as client:
        tasks = [process_scene(scene, client) for scene in state.scenes]
        state.scenes = await asyncio.gather(*tasks)

    # Check for any failures
    if any("CodeGen failed" in str(e) for s in state.scenes for e in s.errors):
        state.status = "failed"
    else:
        state.status = "code_generation_complete"

    return state

async def node_validate(state: PipelineState) -> PipelineState:
    print("-> node_validate")

    async def validate_scene(scene: SceneData, client: httpx.AsyncClient):
        if scene.status == "validated":
            return scene

        scene.retry_count += 1
        try:
            payload = {
                "scene_id": scene.scene_id,
                "script_path": scene.script_path
            }
            resp = await client.post(f"{SERVICES['validator']}/validate_code", json=payload)
            resp.raise_for_status()
            result = resp.json()

            if result.get("success"):
                scene.rendered_video_path = result.get("video_path")
                scene.status = "validated"
            else:
                scene.errors.append(result.get("error_log", "Unknown render error"))
                scene.status = "validation_failed"

        except Exception as e:
            scene.errors.append(f"Validator failed: {str(e)}")
            scene.status = "validation_failed"

        return scene

    async with httpx.AsyncClient(timeout=300) as client:
        tasks = [validate_scene(scene, client) for scene in state.scenes]
        state.scenes = await asyncio.gather(*tasks)

    all_valid = all(scene.status == "validated" for scene in state.scenes)
    if not all_valid:
        state.status = "validation_failed"
    else:
        state.status = "validated"

    return state

async def node_voiceover(state: PipelineState) -> PipelineState:
    print("-> node_voiceover")

    async def process_voiceover(scene: SceneData, client: httpx.AsyncClient):
        try:
            payload = {
                "scene_id": scene.scene_id,
                "narration": scene.narration
            }
            resp = await client.post(f"{SERVICES['voiceover']}/generate_audio", json=payload)
            resp.raise_for_status()
            scene.voiceover_audio_path = resp.json().get("audio_path")
        except Exception as e:
            scene.errors.append(f"Voiceover failed for {scene.scene_id}: {str(e)}")
        return scene

    async with httpx.AsyncClient(timeout=120) as client:
        tasks = [process_voiceover(scene, client) for scene in state.scenes]
        state.scenes = await asyncio.gather(*tasks)

    if any("Voiceover failed" in str(e) for s in state.scenes for e in s.errors):
        state.status = "failed"
    else:
        state.status = "voiceover_complete"

    return state

    state.status = "voiceover_complete"
    return state

async def node_assemble(state: PipelineState) -> PipelineState:
    print("-> node_assemble")
    async with httpx.AsyncClient(timeout=300) as client:
        try:
            payload = {
                "scenes": [
                    {"video_path": s.rendered_video_path, "audio_path": s.voiceover_audio_path}
                    for s in state.scenes
                ]
            }
            resp = await client.post(f"{SERVICES['assembler']}/assemble", json=payload)
            resp.raise_for_status()
            state.final_video_path = resp.json().get("final_video_path")
            state.status = "assembled"
        except Exception as e:
            state.global_errors.append(f"Assemble failed: {str(e)}")
            state.status = "failed"
    return state

async def node_quality_review(state: PipelineState) -> PipelineState:
    print("-> node_quality_review")
    async with httpx.AsyncClient(timeout=60) as client:
        try:
            payload = {"video_path": state.final_video_path}
            resp = await client.post(f"{SERVICES['quality_review']}/review", json=payload)
            resp.raise_for_status()
            result = resp.json()
            if result.get("is_valid"):
                state.status = "completed"
            else:
                state.global_errors.extend(result.get("issues", []))
                state.status = "failed"
        except Exception as e:
            state.global_errors.append(f"Review failed: {str(e)}")
            state.status = "failed"
    return state

# ---------------------------------------------------------
# Graph Routing Logic
# ---------------------------------------------------------

def route_after_script(state: PipelineState):
    if state.status == "failed": return END
    return "generate_code"

def route_after_codegen(state: PipelineState):
    if state.status == "failed": return END
    return "validate"

def route_after_validate(state: PipelineState):
    if state.status == "validated":
        return "voiceover"

    # Retry loop logic
    for scene in state.scenes:
        if scene.status == "validation_failed" and scene.retry_count >= 3:
            state.global_errors.append(f"Max retries exceeded for scene {scene.scene_id}")
            return END

    return "generate_code" # Self-healing loop

def route_after_voiceover(state: PipelineState):
    if state.status == "failed": return END
    return "assemble"

def route_after_assemble(state: PipelineState):
    if state.status == "failed": return END
    return "quality_review"


# Build the Graph
workflow = StateGraph(PipelineState)

workflow.add_node("script_writer", node_script_writer)
workflow.add_node("generate_code", node_generate_code)
workflow.add_node("validate", node_validate)
workflow.add_node("voiceover", node_voiceover)
workflow.add_node("assemble", node_assemble)
workflow.add_node("quality_review", node_quality_review)

workflow.add_edge(START, "script_writer")
workflow.add_conditional_edges("script_writer", route_after_script)
workflow.add_conditional_edges("generate_code", route_after_codegen)
workflow.add_conditional_edges("validate", route_after_validate)
workflow.add_conditional_edges("voiceover", route_after_voiceover)
workflow.add_conditional_edges("assemble", route_after_assemble)
workflow.add_edge("quality_review", END)

agent_app = workflow.compile()

# ---------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------


@app.on_event("startup")
async def on_startup():
    await init_db()

async def run_pipeline(job_id: str, prompt: str):
    initial_state = PipelineState(user_prompt=prompt)

    # Run the langgraph agent with postgres checkpointer
    try:
        async with AsyncPostgresSaver.from_conn_string(DATABASE_URL) as checkpointer:
            await checkpointer.setup()
            agent_app_with_cp = workflow.compile(checkpointer=checkpointer)

            # The config must contain a thread_id to identify this run
            config = {"configurable": {"thread_id": job_id}}
            final_state = await agent_app_with_cp.ainvoke(initial_state, config)

            # Update DB with final state
            async for session in get_session():
                stmt = select(PipelineJob).where(PipelineJob.job_id == job_id)
                result = await session.execute(stmt)
                job = result.scalar_one_or_none()
                if job:
                    job.status = final_state.get("status", "completed")
                    job.scenes = [s.dict() for s in final_state.get("scenes", [])]
                    job.global_errors = final_state.get("global_errors", [])
                    job.final_video_path = final_state.get("final_video_path")
                    session.add(job)
                    await session.commit()
                break # Only need one session

    except Exception as e:
        # Update DB on failure
        async for session in get_session():
            stmt = select(PipelineJob).where(PipelineJob.job_id == job_id)
            result = await session.execute(stmt)
            job = result.scalar_one_or_none()
            if job:
                job.status = "failed"
                if job.global_errors is None:
                    job.global_errors = []
                job.global_errors.append(str(e))
                session.add(job)
                await session.commit()
            break



@app.post("/generate")
async def start_generation(
    request: GenerationRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session)
):
    job_id = str(uuid.uuid4())

    # Save initial job to DB
    new_job = PipelineJob(
        job_id=job_id,
        prompt=request.prompt,
        status="processing"
    )
    session.add(new_job)
    await session.commit()

    background_tasks.add_task(run_pipeline, job_id, request.prompt)
    return {"job_id": job_id, "status": "processing"}

@app.get("/status/{job_id}")
async def get_status(job_id: str, session: AsyncSession = Depends(get_session)):
    stmt = select(PipelineJob).where(PipelineJob.job_id == job_id)
    result = await session.execute(stmt)
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "job_id": job.job_id,
        "prompt": job.prompt,
        "status": job.status,
        "scenes": job.scenes,
        "global_errors": job.global_errors,
        "final_video_path": job.final_video_path
    }

@app.get("/health")
async def health():
    return {"status": "ok"}
