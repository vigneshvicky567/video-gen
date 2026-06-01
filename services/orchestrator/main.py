import os
import httpx
from typing import Dict, Any, List
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from langgraph.graph import StateGraph, START, END

from services.shared.models import PipelineState, SceneData

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
    async with httpx.AsyncClient(timeout=120) as client:
        for idx, scene in enumerate(state.scenes):
            if scene.status == "validated":
                continue # Skip if already good

            try:
                payload = {
                    "scene_id": scene.scene_id,
                    "description": scene.description,
                    "narration": scene.narration,
                    "previous_code": scene.manim_code,
                    "error_logs": scene.errors[-1] if scene.errors else None
                }
                resp = await client.post(f"{SERVICES['manim_generator']}/generate_code", json=payload)
                resp.raise_for_status()
                scene.manim_code = resp.json().get("manim_code")
                scene.status = "code_generated"
            except Exception as e:
                scene.errors.append(f"CodeGen failed: {str(e)}")
                state.status = "failed"
                break

    if state.status != "failed":
        state.status = "code_generation_complete"
    return state

async def node_validate(state: PipelineState) -> PipelineState:
    print("-> node_validate")
    async with httpx.AsyncClient(timeout=300) as client:
        all_valid = True
        for scene in state.scenes:
            if scene.status == "validated":
                continue

            scene.retry_count += 1
            try:
                payload = {
                    "scene_id": scene.scene_id,
                    "manim_code": scene.manim_code
                }
                resp = await client.post(f"{SERVICES['validator']}/validate_code", json=payload)
                resp.raise_for_status()
                result = resp.json()

                if result.get("success"):
                    scene.rendered_video_path = result.get("video_path")
                    scene.status = "validated"
                else:
                    all_valid = False
                    scene.errors.append(result.get("error_log", "Unknown render error"))
                    scene.status = "validation_failed"

            except Exception as e:
                all_valid = False
                scene.errors.append(f"Validator failed: {str(e)}")
                scene.status = "validation_failed"

        if not all_valid:
            state.status = "validation_failed"
        else:
            state.status = "validated"
    return state

async def node_voiceover(state: PipelineState) -> PipelineState:
    print("-> node_voiceover")
    async with httpx.AsyncClient(timeout=120) as client:
        for scene in state.scenes:
            try:
                payload = {
                    "scene_id": scene.scene_id,
                    "narration": scene.narration
                }
                resp = await client.post(f"{SERVICES['voiceover']}/generate_audio", json=payload)
                resp.raise_for_status()
                scene.voiceover_audio_path = resp.json().get("audio_path")
            except Exception as e:
                state.global_errors.append(f"Voiceover failed for {scene.scene_id}: {str(e)}")
                state.status = "failed"
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

# In-memory store for status polling
jobs: Dict[str, PipelineState] = {}
import uuid

async def run_pipeline(job_id: str, prompt: str):
    initial_state = PipelineState(user_prompt=prompt)
    jobs[job_id] = initial_state

    # Run the langgraph agent
    # We use agent_app.ainvoke since our nodes are async
    try:
        final_state = await agent_app.ainvoke(initial_state)
        jobs[job_id] = final_state
    except Exception as e:
        jobs[job_id].status = "failed"
        jobs[job_id].global_errors.append(str(e))


@app.post("/generate")
async def start_generation(request: GenerationRequest, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())
    background_tasks.add_task(run_pipeline, job_id, request.prompt)
    return {"job_id": job_id, "status": "processing"}

@app.get("/status/{job_id}")
async def get_status(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return jobs[job_id]

@app.get("/health")
async def health():
    return {"status": "ok"}
