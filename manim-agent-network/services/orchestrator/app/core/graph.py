from langgraph.graph import StateGraph, START, END
from shared.models.agent_state import LangGraphState
from shared.config import settings
from shared.schemas.requests import (
    ScriptWriterRequest, CodeGeneratorRequest,
    ValidatorRequest, VoiceoverRequest, AssemblerRequest
)
from shared.schemas.common import ScenePlan
import httpx
import logging
from typing import Literal

logger = logging.getLogger(__name__)

async def _post(url: str, json_data: dict) -> dict:
    async with httpx.AsyncClient(timeout=settings.SERVICE_HTTP_TIMEOUT_SECONDS) as client:
        response = await client.post(url, json=json_data)
        response.raise_for_status()
        return response.json()

async def script_writer_node(state: LangGraphState):
    logger.info("Executing Script Writer Node")
    try:
        data = await _post(f"{settings.SCRIPT_WRITER_URL}/generate", {"topic": state["topic"]})
        return {"script": data["script"], "status": "script_generation"}
    except Exception as e:
        logger.error(f"Script Writer failed: {e}")
        return {"status": "failed", "overall_error": str(e)}

async def code_generator_node(state: LangGraphState):
    logger.info("Executing Code Generator Node")
    try:
        script = state["script"]
        job_id = state["job_id"]

        new_code_paths = state.get("code_paths", {})

        # In a real massively parallel setup, we might use asyncio.gather here.
        # For LangGraph simple nodes, iterating is fine.
        for scene in script["scenes"]:
            scene_id = scene["scene_id"]

            # Check if this scene needs generation (either first time, or retry)
            if scene_id not in state.get("render_paths", {}) and state.get("retry_counts", {}).get(scene_id, 0) < 3:

                request_data = {
                    "scene": scene,
                    "job_id": job_id,
                    "error_log": state.get("error_logs", {}).get(scene_id),
                    "previous_code": state.get("previous_code", {}).get(scene_id)
                }

                res = await _post(f"{settings.CODE_GENERATOR_URL}/generate", request_data)

                new_code_paths[scene_id] = res["code_path"]

                # Keep track of the generated code to feed back on failure
                with open(res["code_path"], "r") as f:
                    code_content = f.read()

                if "previous_code" not in state:
                    state["previous_code"] = {}
                state["previous_code"][scene_id] = code_content

        return {"code_paths": new_code_paths, "status": "code_generation"}
    except Exception as e:
        logger.error(f"Code Generator failed: {e}")
        return {"status": "failed", "overall_error": str(e)}

async def validator_node(state: LangGraphState):
    logger.info("Executing Validator Node")
    try:
        job_id = state["job_id"]

        new_render_paths = state.get("render_paths", {})
        new_error_logs = state.get("error_logs", {})
        new_retry_counts = state.get("retry_counts", {})

        for scene_id, code_path in state["code_paths"].items():
            if scene_id not in new_render_paths:
                # If we've maxed out retries, skip
                if new_retry_counts.get(scene_id, 0) >= 3:
                    logger.error(f"Scene {scene_id} maxed out retries.")
                    continue

                req = {
                    "job_id": job_id,
                    "scene_id": scene_id,
                    "code_path": code_path
                }
                res = await _post(f"{settings.VALIDATOR_URL}/validate", req)

                if res["success"]:
                    new_render_paths[scene_id] = res["render_path"]
                    # Clear error log if success
                    if scene_id in new_error_logs:
                        del new_error_logs[scene_id]
                else:
                    new_error_logs[scene_id] = res["error_log"]
                    new_retry_counts[scene_id] = new_retry_counts.get(scene_id, 0) + 1

        return {
            "render_paths": new_render_paths,
            "error_logs": new_error_logs,
            "retry_counts": new_retry_counts,
            "status": "validation"
        }
    except Exception as e:
        logger.error(f"Validator failed: {e}")
        return {"status": "failed", "overall_error": str(e)}

def validation_router(state: LangGraphState) -> Literal["code_generator_node", "voiceover_node", "failed"]:
    # If any overall error, fail
    if state.get("overall_error"):
        return "failed"

    script = state.get("script")
    render_paths = state.get("render_paths", {})
    retry_counts = state.get("retry_counts", {})

    all_success = True
    needs_retry = False

    for scene in script["scenes"]:
        scene_id = scene["scene_id"]
        if scene_id not in render_paths:
            all_success = False
            if retry_counts.get(scene_id, 0) < 3:
                needs_retry = True

    if all_success:
        return "voiceover_node"
    elif needs_retry:
        return "code_generator_node"
    else:
        # Some scenes failed and maxed out retries
        return "failed"

async def voiceover_node(state: LangGraphState):
    logger.info("Executing Voiceover Node")
    try:
        job_id = state["job_id"]
        script = state["script"]
        new_audio_paths = state.get("audio_paths", {})

        for scene in script["scenes"]:
            scene_id = scene["scene_id"]
            if scene_id not in new_audio_paths:
                req = {
                    "job_id": job_id,
                    "scene_id": scene_id,
                    "narration_text": scene["narration_text"]
                }
                res = await _post(f"{settings.VOICEOVER_URL}/generate", req)
                new_audio_paths[scene_id] = res["audio_path"]

        return {"audio_paths": new_audio_paths, "status": "voiceover"}
    except Exception as e:
        logger.error(f"Voiceover failed: {e}")
        return {"status": "failed", "overall_error": str(e)}

async def assembler_node(state: LangGraphState):
    logger.info("Executing Assembler Node")
    try:
        req = {
            "job_id": state["job_id"],
            "render_paths": state["render_paths"],
            "audio_paths": state["audio_paths"]
        }
        res = await _post(f"{settings.ASSEMBLER_URL}/assemble", req)
        return {"final_output_path": res["final_output_path"], "status": "completed"}
    except Exception as e:
        logger.error(f"Assembler failed: {e}")
        return {"status": "failed", "overall_error": str(e)}


# Build the Graph
workflow = StateGraph(LangGraphState)

workflow.add_node("script_writer_node", script_writer_node)
workflow.add_node("code_generator_node", code_generator_node)
workflow.add_node("validator_node", validator_node)
workflow.add_node("voiceover_node", voiceover_node)
workflow.add_node("assembler_node", assembler_node)
# Simple dummy node for failure state
workflow.add_node("failed", lambda s: {"status": "failed"})

workflow.add_edge(START, "script_writer_node")

# If script writing fails, go to end, else code gen
workflow.add_conditional_edges("script_writer_node", lambda s: "failed" if s.get("overall_error") else "code_generator_node")

workflow.add_edge("code_generator_node", "validator_node")

# Routing after validation: loop back, continue, or fail
workflow.add_conditional_edges("validator_node", validation_router)

workflow.add_edge("voiceover_node", "assembler_node")
workflow.add_edge("assembler_node", END)
workflow.add_edge("failed", END)

app_graph = workflow.compile()
