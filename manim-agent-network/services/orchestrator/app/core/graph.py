from langgraph.graph import StateGraph, START, END
from shared.models.agent_state import LangGraphState
from shared.config import settings
from shared.schemas.requests import (
    ScriptWriterRequest, CodeGeneratorRequest,
    ValidatorRequest, VoiceoverRequest, AssemblerRequest,
    ImageFetcherRequest
)
from shared.schemas.common import ScenePlan, VISUAL_STYLES, TOPIC_STYLE_MAP
from shared.timeouts import assembler_http_timeout_s
import httpx
import asyncio
import logging
from typing import Literal

logger = logging.getLogger(__name__)


async def _post(url: str, json_data: dict, timeout: float | None = None) -> dict:
    async with httpx.AsyncClient(timeout=timeout or settings.SERVICE_HTTP_TIMEOUT_SECONDS) as client:
        response = await client.post(url, json=json_data)
        response.raise_for_status()
        return response.json()


async def _bounded_gather(coros: list, limit: int) -> list:
    """asyncio.gather, but never more than `limit` coroutines in flight.

    Caps orchestrator-side HTTP fan-out so 30-60 scenes don't all hit a service
    at once and sit blocked past the per-request HTTP timeout. Order preserved.
    """
    sem = asyncio.Semaphore(max(1, limit))

    async def _run(coro):
        async with sem:
            return await coro

    return await asyncio.gather(*(_run(c) for c in coros), return_exceptions=False)


async def script_writer_node(state: LangGraphState):
    # Resume-safe: a saved script means this job already passed this stage. Re-running
    # would regenerate a NON-DETERMINISTIC breakdown (different scene count/ids),
    # orphaning the render_paths keyed by the old ids. Keep the existing script.
    if state.get("script"):
        logger.info("Script already present — skipping Script Writer (resume)")
        return {"status": "script_generation"}
    logger.info("Executing Script Writer Node")
    try:
        data = await _post(f"{settings.SCRIPT_WRITER_URL}/generate", {
            "topic": state["topic"],
            "brief": state.get("brief"),
            "job_id": state["job_id"],
        })
        return {
            "script": data["script"],
            "script_meta": data.get("meta"),
            "status": "script_generation",
        }
    except Exception as e:
        error_msg = str(e) or f"{type(e).__name__}: (no message)"
        logger.error(f"Script Writer failed: {error_msg}")
        return {"status": "failed", "overall_error": error_msg}


async def _generate_one_scene(
    scene: dict, job_id: str, state: LangGraphState,
    all_scenes: list, scene_idx: int,
) -> tuple:
    """Generate code for a single scene. Returns (scene_id, code_path, error)."""
    scene_id = scene["scene_id"]

    # Build neighbor context (1-2 lines each; trimmed to 120 chars for prompt budget)
    n = len(all_scenes)
    prev_visual = all_scenes[scene_idx - 1].get("visual_description", "")[:120] if scene_idx > 0 else None
    next_visual = all_scenes[scene_idx + 1].get("visual_description", "")[:120] if scene_idx < n - 1 else None
    neighbor_context = {"prev_visual": prev_visual, "next_visual": next_visual}

    try:
        request_data = {
            "scene": scene,
            "job_id": job_id,
            "error_log": state.get("error_logs", {}).get(scene_id),
            "previous_code": state.get("previous_code", {}).get(scene_id),
            "render_mode": (state.get("brief") or {}).get("render_mode"),
            # Pre-fetched stock images for this scene (HF only; empty for Manim).
            "image_paths": state.get("image_paths", {}).get(scene_id),
            # Identity + context injected by art_director_node
            "job_style": state.get("job_style"),
            "neighbor_context": neighbor_context,
            # Per-sentence audio cues (voiceover runs before code-gen) so the LLM
            # times animation beats to the spoken words. Empty if voiceover gave none.
            "audio_cues": state.get("audio_segments", {}).get(scene_id),
        }
        res = await _post(f"{settings.CODE_GENERATOR_URL}/generate", request_data)
        logger.info(f"[PARALLEL] Code generated for scene {scene_id}: {res['code_path']}")
        return scene_id, res["code_path"], None
    except Exception as e:
        logger.error(f"[PARALLEL] Code generation failed for scene {scene_id}: {e}")
        return scene_id, None, str(e)


async def art_director_node(state: LangGraphState):
    """Pick one visual style for the whole job — zero LLM calls, pure dict lookup.

    Resolution order:
    1. Already set (resume-safe skip).
    2. User picked a style via brief answers (question_id="style").
    3. Auto-pick from topic_classification in script_meta using TOPIC_STYLE_MAP.
    4. Fallback: "swiss_pulse".
    """
    if state.get("job_style"):
        logger.info("Art director: style already set (resume)")
        return {"job_style": state["job_style"]}

    style_key = "swiss_pulse"  # default

    # Check user brief for explicit style answer
    brief = state.get("brief") or {}
    if isinstance(brief, dict):
        answers = brief.get("answers") or []
        for ans in answers:
            qid = ans.get("question_id", "") if isinstance(ans, dict) else getattr(ans, "question_id", "")
            if qid == "style":
                selected = ans.get("selected", []) if isinstance(ans, dict) else getattr(ans, "selected", [])
                custom = ans.get("custom_text", "") if isinstance(ans, dict) else getattr(ans, "custom_text", "")
                raw = (selected[0] if selected else custom or "").lower().replace(" ", "_")
                if raw in VISUAL_STYLES:
                    style_key = raw
                break
        # Also check direct visual_style field
        if style_key == "swiss_pulse" and brief.get("visual_style"):
            raw = brief["visual_style"].lower().replace(" ", "_")
            if raw in VISUAL_STYLES:
                style_key = raw

    # Auto-pick from topic classification when no user preference
    if style_key == "swiss_pulse":
        topic_class = ""
        script_meta = state.get("script_meta") or {}
        if isinstance(script_meta, dict):
            topic_class = (script_meta.get("topic_classification") or "").lower()
        if not topic_class:
            topic_class = (state.get("topic") or "").lower()
        for keyword, mapped_key in TOPIC_STYLE_MAP:
            if keyword in topic_class:
                style_key = mapped_key
                break

    style = VISUAL_STYLES[style_key].model_dump()
    logger.info(f"Art director: picked style '{VISUAL_STYLES[style_key].name}' (key={style_key})")
    return {"job_style": style}


async def image_fetcher_node(state: LangGraphState):
    """Fetch stock images for HyperFrames scenes BEFORE code-gen so each scene can
    compose its own background imagery (Option B). Manim scenes stay image-free
    (vector/math). Resume-safe (skips if already fetched) and never fatal — images
    are an enhancement, so any failure degrades to no-images, not a job failure."""
    if state.get("image_paths"):
        return {"image_paths": state["image_paths"], "status": "image_fetch"}
    try:
        script = state["script"]
        job_id = state["job_id"]
        render_mode = (state.get("brief") or {}).get("render_mode", "hybrid").strip().lower()

        if render_mode == "manim":
            # Pure Manim job — no images needed at all.
            return {"image_paths": {}, "status": "image_fetch"}
        elif render_mode == "hyperframes":
            # All scenes forced to HF regardless of script-writer content_type tags.
            hf_scenes = script["scenes"]
        else:
            # Hybrid: only fetch for scenes the script-writer tagged as hyperframes.
            hf_scenes = [
                s for s in script["scenes"]
                if (s.get("content_type") or "").lower() == "hyperframes"
            ]

        if not hf_scenes:
            return {"image_paths": {}, "status": "image_fetch"}
        img_request = ImageFetcherRequest(job_id=job_id, scenes=hf_scenes)
        res = await _post(f"{settings.IMAGE_FETCHER_URL}/fetch", img_request.model_dump())
        image_paths = {int(k): v for k, v in res["image_paths"].items()}
        got = sum(1 for v in image_paths.values() if v)
        logger.info(f"Image fetch: {got}/{len(hf_scenes)} HF scenes got images")
        return {"image_paths": image_paths, "status": "image_fetch"}
    except Exception as e:
        logger.error(f"Image fetcher node failed (continuing without images): {e}")
        return {"image_paths": {}, "status": "image_fetch"}


async def code_generator_node(state: LangGraphState):
    logger.info("Executing Code Generator Node (PARALLEL)")
    try:
        script = state["script"]
        job_id = state["job_id"]
        render_paths = state.get("render_paths", {})
        retry_counts = state.get("retry_counts", {})
        new_code_paths = dict(state.get("code_paths", {}))
        new_previous_code = dict(state.get("previous_code", {}))
        new_retry_counts = dict(retry_counts)
        new_error_logs = dict(state.get("error_logs", {}))

        # Collect scenes that need (re)generation
        scenes_to_generate = [
            scene for scene in script["scenes"]
            if scene["scene_id"] not in render_paths
            and retry_counts.get(scene["scene_id"], 0) < 5
        ]

        if not scenes_to_generate:
            logger.info("No scenes need code generation.")
            return {"code_paths": new_code_paths, "status": "code_generation"}

        logger.info(f"Generating code for {len(scenes_to_generate)} scenes in parallel...")

        # Build index map so each scene gets its correct position in the full list
        # (needed for neighbor context — scenes_to_generate may be a subset on retry).
        all_scenes = script["scenes"]
        scene_idx_map = {s["scene_id"]: i for i, s in enumerate(all_scenes)}

        # Run scenes in parallel, bounded so 30-60 scenes don't swamp code-gen.
        # Voiceover already ran UPSTREAM (voiceover_node before this node), so each
        # scene's audio cue sheet is in state.audio_segments and rides into the
        # code-gen request via _generate_one_scene — the LLM times beats to speech.
        tasks = [
            _generate_one_scene(scene, job_id, state, all_scenes, scene_idx_map[scene["scene_id"]])
            for scene in scenes_to_generate
        ]
        results = await _bounded_gather(tasks, settings.ORCH_CODEGEN_CONCURRENCY)

        for scene_id, code_path, error in results:
            if code_path:
                new_code_paths[scene_id] = code_path
                new_error_logs.pop(scene_id, None)
                # Read generated code for retry context
                try:
                    with open(code_path, "r") as f:
                        new_previous_code[scene_id] = f.read()
                except Exception:
                    pass
            else:
                # Count code-gen failures against the retry cap. Without this the
                # scene never enters code_paths, the validator never bumps its
                # count, and validation_router loops back forever (GraphRecursionError).
                logger.error(f"Scene {scene_id} code generation failed: {error}")
                new_retry_counts[scene_id] = new_retry_counts.get(scene_id, 0) + 1
                new_error_logs[scene_id] = error or "code generation failed"
                # Drop the stale code from the previous round, otherwise the
                # validator re-renders the exact code that already failed —
                # a wasted render (up to minutes) plus a double retry bump.
                new_code_paths.pop(scene_id, None)

        return {
            "code_paths": new_code_paths,
            "previous_code": new_previous_code,
            "retry_counts": new_retry_counts,
            "error_logs": new_error_logs,
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
            and new_retry_counts.get(scene_id, 0) < 5
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

        # Bound in-flight validations to the validator's render capacity so
        # queued requests don't burn their HTTP clock waiting behind renders.
        tasks = [_validate_one_scene(sid, cpath, job_id) for sid, cpath in scenes_to_validate]
        results = await _bounded_gather(tasks, settings.VALIDATOR_MAX_CONCURRENT_RENDERS or 2)

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


def validation_router(state: LangGraphState) -> Literal["code_generator_node", "assembler_node", "failed"]:
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
            if retry_counts.get(scene_id, 0) < 5:  # match code_generator_node limit
                needs_retry = True

    if all_success:
        return "assembler_node"
    elif needs_retry:
        return "code_generator_node"
    elif render_paths:
        # Graceful degradation: some scenes exhausted their retries, but at least
        # one rendered. Drop the unrenderable scenes and assemble what we have
        # instead of failing the entire job. Voiceover already ran (pre-code) and
        # the compositor keys off render_paths, so dropped scenes are excluded.
        failed = sorted(s["scene_id"] for s in script["scenes"] if s["scene_id"] not in render_paths)
        logger.warning(
            f"Proceeding with {len(render_paths)}/{len(script['scenes'])} scenes; "
            f"dropping unrenderable scenes {failed}"
        )
        return "assembler_node"
    else:
        return "failed"


async def _generate_voiceover(scene: dict, job_id: str, existing: dict) -> tuple:
    """Generate voiceover for one scene. Returns (scene_id, audio_path, segments).
    segments is the per-sentence cue sheet [{text,start,duration}] or None."""
    scene_id = scene["scene_id"]
    if scene_id in existing:
        return scene_id, existing[scene_id], None  # resume: keep existing audio + state segments
    try:
        req = {
            "job_id": job_id,
            "scene_id": scene_id,
            "narration_text": scene["narration_text"]
        }
        res = await _post(f"{settings.VOICEOVER_URL}/generate", req)
        provider = res.get("provider_used", "unknown")
        fallback = " (fallback)" if res.get("fallback_used") else ""
        segs = res.get("segments")
        logger.info(f"[PARALLEL] Voiceover done for scene {scene_id}: {provider}{fallback} "
                    f"({len(segs or [])} cues)")
        return scene_id, res["audio_path"], segs
    except Exception as e:
        logger.error(f"[PARALLEL] Voiceover failed for scene {scene_id}: {e}")
        return scene_id, None, None


async def voiceover_node(state: LangGraphState):
    """Voiceover — runs BEFORE code-gen so each scene's per-sentence cue sheet
    (audio_segments) is available to time animation beats to the spoken words.
    Voices ALL scenes (render hasn't happened yet); audio for a scene later
    dropped by the validator is harmless (the compositor keys off render_paths)."""
    logger.info("Executing Voiceover Node (PARALLEL, pre-code for A/V sync)")
    try:
        job_id = state["job_id"]
        script = state["script"]
        existing_audio = state.get("audio_paths", {})
        scenes = script["scenes"]

        vo_tasks = [_generate_voiceover(scene, job_id, existing_audio) for scene in scenes]
        vo_results = await _bounded_gather(vo_tasks, settings.ORCH_VOICEOVER_CONCURRENCY)

        new_audio_paths = dict(existing_audio)
        new_segments = dict(state.get("audio_segments", {}))
        failed_scenes = []
        for scene_id, audio_path, segments in vo_results:
            if audio_path:
                new_audio_paths[scene_id] = audio_path
                if segments:                       # don't clobber resume-preserved cues
                    new_segments[scene_id] = segments
            else:
                failed_scenes.append(scene_id)

        if failed_scenes and not new_audio_paths:
            return {
                "audio_paths": new_audio_paths,
                "status": "failed",
                "overall_error": f"Voiceover failed for ALL scenes: {failed_scenes}",
            }
        if failed_scenes:
            logger.warning(
                f"Voiceover failed for scenes {failed_scenes}; "
                f"continuing with {len(new_audio_paths)}/{len(scenes)} narrated scenes"
            )

        return {
            "audio_paths": new_audio_paths,
            "audio_segments": new_segments,
            "status": "voiceover",
        }
    except Exception as e:
        logger.error(f"Voiceover node failed: {e}")
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
            "job_style": state.get("job_style"),
        }
        # Scale the HTTP timeout to the planned output length — a 30-min render
        # legitimately outlasts the default 900s service timeout. Estimate the
        # composed length the same way the compositor slots scenes: max(est, words/wps).
        render_paths = state.get("render_paths", {})
        wps = settings.SCRIPT_WORDS_PER_SECOND
        planned_total = sum(
            max(s["estimated_duration_seconds"], len((s.get("narration_text") or "").split()) / wps)
            for s in state["script"]["scenes"]
            if s["scene_id"] in render_paths
        )
        # Scenes the validator couldn't render are excluded here (compositor keys
        # off render_paths). Persist the list for the API response — this used to
        # live in the voiceover node, which now runs pre-render and can't know it.
        dropped_scenes = sorted(
            s["scene_id"] for s in state["script"]["scenes"] if s["scene_id"] not in render_paths
        )
        res = await _post(
            f"{settings.ASSEMBLER_URL}/assemble", req,
            timeout=assembler_http_timeout_s(planned_total),
        )
        return {"final_output_path": res["final_output_path"],
                "intro_duration_seconds": res.get("intro_duration_seconds", 0.0),
                "dropped_scenes": dropped_scenes, "status": "completed"}
    except Exception as e:
        logger.error(f"Assembler failed: {e}")
        return {"status": "failed", "overall_error": str(e)}


def failed_node(state: LangGraphState):
    """Terminal failure sink. Backfills overall_error when the route here was a
    decision (validation_router exhausting retries with nothing rendered) rather
    than a node that already set a message — so the API never reports a bare
    "failed" status with no reason."""
    if state.get("overall_error"):
        return {"status": "failed"}

    error_logs = state.get("error_logs", {})
    script = state.get("script") or {}
    unrendered = sorted(
        s["scene_id"] for s in script.get("scenes", [])
        if s["scene_id"] not in state.get("render_paths", {})
    )
    if error_logs:
        detail = "; ".join(f"scene {sid}: {error_logs[sid]}" for sid in sorted(error_logs))
        msg = f"All scenes exhausted retries. {detail}"
    elif unrendered:
        msg = f"Pipeline failed: scenes {unrendered} never rendered."
    else:
        msg = "Pipeline failed for an unknown reason."
    logger.error(msg)
    return {"status": "failed", "overall_error": msg}


# Build the Graph
workflow = StateGraph(LangGraphState)

workflow.add_node("script_writer_node",  script_writer_node)
workflow.add_node("art_director_node",    art_director_node)
workflow.add_node("voiceover_node",       voiceover_node)
workflow.add_node("image_fetcher_node",   image_fetcher_node)
workflow.add_node("code_generator_node",  code_generator_node)
workflow.add_node("validator_node",       validator_node)
workflow.add_node("assembler_node",       assembler_node)
workflow.add_node("failed",               failed_node)

# Pipeline order: script -> art_director (style) -> VOICEOVER (pre-code, so each
# scene's per-sentence cue sheet feeds code-gen for A/V sync) -> image_fetcher
# (HF backgrounds) -> code_generator <-> validator (render+retry) -> assembler.
workflow.add_edge(START, "script_writer_node")
workflow.add_conditional_edges(
    "script_writer_node",
    lambda s: "failed" if s.get("overall_error") is not None else "art_director_node"
)
workflow.add_edge("art_director_node", "voiceover_node")
workflow.add_conditional_edges(
    "voiceover_node",
    lambda s: "failed" if s.get("overall_error") else "image_fetcher_node"
)
workflow.add_edge("image_fetcher_node", "code_generator_node")
workflow.add_edge("code_generator_node", "validator_node")
workflow.add_conditional_edges("validator_node", validation_router,
    {
        "code_generator_node": "code_generator_node",
        "assembler_node":      "assembler_node",
        "failed":              "failed"
    }
)
workflow.add_edge("assembler_node", END)
workflow.add_edge("failed",         END)

app_graph = workflow.compile()
