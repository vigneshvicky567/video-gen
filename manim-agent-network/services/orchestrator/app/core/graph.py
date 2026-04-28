from langgraph.graph import StateGraph, START, END
from shared.models.agent_state import LangGraphState
from shared.config import settings
from shared.schemas.requests import (
    ScriptWriterRequest, CodeGeneratorRequest,
    ValidatorRequest, VoiceoverRequest, AssemblerRequest,
    ImageFetcherRequest
)
from shared.schemas.common import ScenePlan
import httpx
import asyncio
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
        error_msg = str(e) or f"{type(e).__name__}: (no message)"
        logger.error(f"Script Writer failed: {error_msg}")
        return {"status": "failed", "overall_error": error_msg}


async def _generate_one_scene(scene: dict, job_id: str, state: LangGraphState) -> tuple:
    """Generate code for a single scene. Returns (scene_id, code_path, error)."""
    scene_id = scene["scene_id"]
    try:
        request_data = {
            "scene": scene,
            "job_id": job_id,
            "error_log": state.get("error_logs", {}).get(scene_id),
            "previous_code": state.get("previous_code", {}).get(scene_id)
        }
        res = await _post(f"{settings.CODE_GENERATOR_URL}/generate", request_data)
        logger.info(f"[PARALLEL] Code generated for scene {scene_id}: {res['code_path']}")
        return scene_id, res["code_path"], None
    except Exception as e:
        logger.error(f"[PARALLEL] Code generation failed for scene {scene_id}: {e}")
        return scene_id, None, str(e)


async def code_generator_node(state: LangGraphState):
    logger.info("Executing Code Generator Node (PARALLEL)")
    try:
        script = state["script"]
        job_id = state["job_id"]
        render_paths = state.get("render_paths", {})
        retry_counts = state.get("retry_counts", {})
        new_code_paths = dict(state.get("code_paths", {}))
        new_previous_code = dict(state.get("previous_code", {}))

        # Collect scenes that need (re)generation
        scenes_to_generate = [
            scene for scene in script["scenes"]
            if scene["scene_id"] not in render_paths
            and retry_counts.get(scene["scene_id"], 0) < 3
        ]

        if not scenes_to_generate:
            logger.info("No scenes need code generation.")
            return {"code_paths": new_code_paths, "status": "code_generation"}

        logger.info(f"Generating code for {len(scenes_to_generate)} scenes in parallel...")

        # Run all scenes in parallel
        tasks = [_generate_one_scene(scene, job_id, state) for scene in scenes_to_generate]
        results = await asyncio.gather(*tasks, return_exceptions=False)

        for scene_id, code_path, error in results:
            if code_path:
                new_code_paths[scene_id] = code_path
                # Read generated code for retry context
                try:
                    with open(code_path, "r") as f:
                        new_previous_code[scene_id] = f.read()
                except Exception:
                    pass
            else:
                logger.error(f"Scene {scene_id} code generation failed: {error}")

        return {
            "code_paths": new_code_paths,
            "previous_code": new_previous_code,
            "status": "code_generation"
        }
    except Exception as e:
        logger.error(f"Code Generator node failed: {e}")
        return {"status": "failed", "overall_error": str(e) or f"{type(e).__name__}"}


async def _validate_one_scene(scene_id: int, code_path: str, job_id: str) -> tuple:
    """Validate a single scene. Returns (scene_id, render_path, error_log)."""
    try:
        req = {"job_id": job_id, "scene_id": scene_id, "code_path": code_path}
        res = await _post(f"{settings.VALIDATOR_URL}/validate", req)
        if res["success"]:
            logger.info(f"[PARALLEL] Scene {scene_id} validated OK: {res['render_path']}")
            return scene_id, res["render_path"], None
        else:
            logger.warning(f"[PARALLEL] Scene {scene_id} validation failed")
            return scene_id, None, res["error_log"]
    except Exception as e:
        logger.error(f"[PARALLEL] Validator error for scene {scene_id}: {e}")
        return scene_id, None, str(e)


async def validator_node(state: LangGraphState):
    logger.info("Executing Validator Node (PARALLEL)")
    try:
        job_id = state["job_id"]
        new_render_paths = dict(state.get("render_paths", {}))
        new_error_logs = dict(state.get("error_logs", {}))
        new_retry_counts = dict(state.get("retry_counts", {}))

        # Collect scenes that need validation
        scenes_to_validate = [
            (scene_id, code_path)
            for scene_id, code_path in state["code_paths"].items()
            if scene_id not in new_render_paths
            and new_retry_counts.get(scene_id, 0) < 3
        ]

        if not scenes_to_validate:
            logger.info("No scenes need validation.")
            return {
                "render_paths": new_render_paths,
                "error_logs": new_error_logs,
                "retry_counts": new_retry_counts,
                "status": "validation"
            }

        logger.info(f"Validating {len(scenes_to_validate)} scenes in parallel...")

        tasks = [_validate_one_scene(sid, cpath, job_id) for sid, cpath in scenes_to_validate]
        results = await asyncio.gather(*tasks, return_exceptions=False)

        for scene_id, render_path, error_log in results:
            if render_path:
                new_render_paths[scene_id] = render_path
                new_error_logs.pop(scene_id, None)
            else:
                new_error_logs[scene_id] = error_log
                new_retry_counts[scene_id] = new_retry_counts.get(scene_id, 0) + 1

        return {
            "render_paths": new_render_paths,
            "error_logs": new_error_logs,
            "retry_counts": new_retry_counts,
            "status": "validation"
        }
    except Exception as e:
        logger.error(f"Validator node failed: {e}")
        return {"status": "failed", "overall_error": str(e)}


def validation_router(state: LangGraphState) -> Literal["code_generator_node", "voiceover_node", "failed"]:
    if state.get("overall_error") is not None:
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
        return "voiceover_node"   # mapped to voiceover_and_images_node in add_conditional_edges
    elif needs_retry:
        return "code_generator_node"
    else:
        return "failed"


async def _generate_voiceover(scene: dict, job_id: str, existing: dict) -> tuple:
    """Generate voiceover for a single scene."""
    scene_id = scene["scene_id"]
    if scene_id in existing:
        return scene_id, existing[scene_id]
    try:
        req = {
            "job_id": job_id,
            "scene_id": scene_id,
            "narration_text": scene["narration_text"]
        }
        res = await _post(f"{settings.VOICEOVER_URL}/generate", req)
        provider = res.get("provider_used", "unknown")
        fallback = " (fallback)" if res.get("fallback_used") else ""
        logger.info(f"[PARALLEL] Voiceover done for scene {scene_id}: {provider}{fallback}")
        return scene_id, res["audio_path"]
    except Exception as e:
        logger.error(f"[PARALLEL] Voiceover failed for scene {scene_id}: {e}")
        return scene_id, None


async def voiceover_node(state: LangGraphState):
    logger.info("Executing Voiceover Node (PARALLEL)")
    try:
        job_id = state["job_id"]
        script = state["script"]
        existing = state.get("audio_paths", {})

        tasks = [_generate_voiceover(scene, job_id, existing) for scene in script["scenes"]]
        results = await asyncio.gather(*tasks, return_exceptions=False)

        new_audio_paths = dict(existing)
        for scene_id, audio_path in results:
            if audio_path:
                new_audio_paths[scene_id] = audio_path
            else:
                return {"status": "failed", "overall_error": f"Voiceover failed for scene {scene_id}"}

        return {"audio_paths": new_audio_paths, "status": "voiceover"}
    except Exception as e:
        logger.error(f"Voiceover node failed: {e}")
        return {"status": "failed", "overall_error": str(e)}


async def voiceover_and_images_node(state: LangGraphState):
    """Run voiceover and image fetching in parallel — they're independent."""
    logger.info("Executing Voiceover + Image Fetcher in PARALLEL")
    try:
        job_id = state["job_id"]
        script = state["script"]
        existing_audio = state.get("audio_paths", {})

        # Voiceover tasks — all scenes in parallel
        vo_tasks = [_generate_voiceover(scene, job_id, existing_audio) for scene in script["scenes"]]

        # Image fetcher task
        img_request = ImageFetcherRequest(job_id=job_id, scenes=script["scenes"])
        img_task = _post(f"{settings.IMAGE_FETCHER_URL}/fetch", img_request.model_dump())

        # Run both concurrently
        vo_results, img_res = await asyncio.gather(
            asyncio.gather(*vo_tasks, return_exceptions=False),
            img_task,
            return_exceptions=False
        )

        # Process voiceover results
        new_audio_paths = dict(existing_audio)
        for scene_id, audio_path in vo_results:
            if audio_path:
                new_audio_paths[scene_id] = audio_path
            else:
                return {"status": "failed", "overall_error": f"Voiceover failed for scene {scene_id}"}

        # Process image results
        merged_image_paths = {**state.get("image_paths", {})}
        for k, v in img_res["image_paths"].items():
            merged_image_paths[int(k)] = v

        return {
            "audio_paths": new_audio_paths,
            "image_paths": merged_image_paths,
            "status": "voiceover_and_images"
        }
    except Exception as e:
        logger.error(f"Voiceover+Images node failed: {e}")
        return {"status": "failed", "overall_error": str(e)}


async def image_fetcher_node(state: LangGraphState):
    logger.info("Executing Image Fetcher Node")
    try:
        request = ImageFetcherRequest(
            job_id=state["job_id"],
            scenes=state["script"]["scenes"]
        )
        res = await _post(
            f"{settings.IMAGE_FETCHER_URL}/fetch",
            request.model_dump()
        )
        merged_image_paths = {**state.get("image_paths", {})}
        for k, v in res["image_paths"].items():
            merged_image_paths[int(k)] = v
        return {"image_paths": merged_image_paths, "status": "image_fetching"}
    except Exception as e:
        logger.error(f"Image Fetcher failed: {e}")
        return {"status": "failed", "overall_error": str(e)}


async def assembler_node(state: LangGraphState):
    logger.info("Executing Assembler Node")
    try:
        req = {
            "job_id": state["job_id"],
            "render_paths": state["render_paths"],
            "audio_paths": state["audio_paths"],
            "scene_plans": state["script"]["scenes"],
            "image_paths": state.get("image_paths", {}),
            "script_title": state["script"].get("title", ""),
        }
        res = await _post(f"{settings.ASSEMBLER_URL}/assemble", req)
        return {"final_output_path": res["final_output_path"], "status": "completed"}
    except Exception as e:
        logger.error(f"Assembler failed: {e}")
        return {"status": "failed", "overall_error": str(e)}


# Build the Graph
workflow = StateGraph(LangGraphState)

workflow.add_node("script_writer_node",        script_writer_node)
workflow.add_node("code_generator_node",       code_generator_node)
workflow.add_node("validator_node",            validator_node)
workflow.add_node("voiceover_and_images_node", voiceover_and_images_node)
workflow.add_node("assembler_node",            assembler_node)
workflow.add_node("failed",                    lambda s: {"status": "failed"})

workflow.add_edge(START, "script_writer_node")
workflow.add_conditional_edges(
    "script_writer_node",
    lambda s: "failed" if s.get("overall_error") is not None else "code_generator_node"
)
workflow.add_edge("code_generator_node", "validator_node")
workflow.add_conditional_edges("validator_node", validation_router,
    {
        "code_generator_node": "code_generator_node",
        "voiceover_node":      "voiceover_and_images_node",
        "failed":              "failed"
    }
)
workflow.add_conditional_edges(
    "voiceover_and_images_node",
    lambda s: "failed" if s.get("overall_error") else "assembler_node"
)
workflow.add_edge("assembler_node", END)
workflow.add_edge("failed",         END)

app_graph = workflow.compile()
