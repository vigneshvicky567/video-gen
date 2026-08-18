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
from shared.render_errors import log_render_failure
import httpx
import asyncio
import logging
import time
from typing import Literal

logger = logging.getLogger(__name__)


def _span(node: str, t0: float, scene_id=None, status: str = "ok", error=None) -> dict:
    now = time.time()
    ev = {"node": node, "start": round(t0, 3), "end": round(now, 3),
          "dur": round(now - t0, 3), "status": status}
    if scene_id is not None:
        ev["scene_id"] = scene_id
    if error:
        ev["error"] = str(error)[:300]
    return ev


class InfraUnavailable(Exception):
    """A downstream service is unreachable or 5xx-ing — transient infrastructure
    failure, distinct from a content failure (bad code / render error). Callers
    must NOT count these against the per-scene content retry budget."""


# Prefix used to tag infra failures inside error_logs so (a) failed_node can
# report them and (b) the code-gen retry prompt can filter them out — a
# "connection refused" string is noise, not feedback, to the LLM.
_INFRA_ERR_PREFIX = "[infra] "

_POST_INFRA_ATTEMPTS = 3


async def _post(url: str, json_data: dict, timeout: float | None = None) -> dict:
    """POST to a pipeline service, retrying transient infra errors with backoff.

    Connection errors, timeouts and 5xx responses are retried here (they mean
    the SERVICE is unhealthy, not the content); when the budget is exhausted an
    InfraUnavailable is raised so nodes can keep these failures out of the
    per-scene content retry budget. 4xx responses raise immediately — those are
    contract/content errors that a retry cannot fix.
    """
    last_exc: Exception | None = None
    for attempt in range(1, _POST_INFRA_ATTEMPTS + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout or settings.SERVICE_HTTP_TIMEOUT_SECONDS) as client:
                response = await client.post(url, json=json_data)
                if response.status_code >= 500:
                    raise InfraUnavailable(f"{url} returned {response.status_code}")
                response.raise_for_status()
                return response.json()
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout,
                httpx.RemoteProtocolError, InfraUnavailable) as e:
            last_exc = e
            if attempt < _POST_INFRA_ATTEMPTS:
                wait = attempt * 5
                logger.warning(f"Service call failed ({e}); retry {attempt}/{_POST_INFRA_ATTEMPTS} in {wait}s: {url}")
                await asyncio.sleep(wait)
                continue
    raise InfraUnavailable(f"service unavailable after {_POST_INFRA_ATTEMPTS} attempts: {url} ({last_exc})") from last_exc


def _scene_retryable(state: LangGraphState, scene_id: int) -> bool:
    """Single source of truth for 'may this scene get another attempt?'.

    Used by code_generator_node, validator_node, validation_router AND
    voiceover_node so the sites cannot drift (the old triplicated `< 5`
    literal could). voiceover_node shares this same budget: a scene whose
    narration fails burns the identical retry_counts/infra_retry_counts
    entry that code-gen/render failures burn, so once a scene's TTS
    exhausts the budget here, code_generator_node's own use of this
    predicate already skips it — no separate bookkeeping needed."""
    content_ok = (state.get("retry_counts") or {}).get(scene_id, 0) < settings.MAX_SCENE_RETRIES
    infra_ok = (state.get("infra_retry_counts") or {}).get(scene_id, 0) < settings.MAX_INFRA_RETRIES
    return content_ok and infra_ok


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
    t0 = time.time()
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
            "node_timings": (state.get("node_timings") or []) + [_span("script_writer_node", t0)],
        }
    except Exception as e:
        error_msg = str(e) or f"{type(e).__name__}: (no message)"
        logger.error(f"Script Writer failed: {error_msg}")
        return {
            "status": "failed", "overall_error": error_msg,
            "node_timings": (state.get("node_timings") or []) + [_span("script_writer_node", t0, status="error", error=error_msg)],
        }


async def _generate_one_scene(
    scene: dict, job_id: str, state: LangGraphState,
    all_scenes: list, scene_idx: int,
) -> tuple:
    """Generate code for a single scene.

    Returns (scene_id, code_path, error, span, is_infra) — is_infra marks a
    service-unavailable failure that must not burn the content retry budget."""
    t0 = time.time()
    scene_id = scene["scene_id"]

    # Build neighbor context (1-2 lines each; trimmed to 120 chars for prompt budget)
    n = len(all_scenes)
    prev_visual = all_scenes[scene_idx - 1].get("visual_description", "")[:120] if scene_idx > 0 else None
    next_visual = all_scenes[scene_idx + 1].get("visual_description", "")[:120] if scene_idx < n - 1 else None
    neighbor_context = {"prev_visual": prev_visual, "next_visual": next_visual}

    # Infra-tagged errors are transport noise, not feedback — keep them out of
    # the LLM retry prompt.
    error_log = state.get("error_logs", {}).get(scene_id)
    if error_log and error_log.startswith(_INFRA_ERR_PREFIX):
        error_log = None

    # Full failure trail (last 4): attempt 5 should learn from attempts 1-4,
    # not just the latest error — repeated-mistake loops were common.
    history = [h for h in (state.get("error_history", {}) or {}).get(scene_id, [])
               if isinstance(h, dict) and not str(h.get("error", "")).startswith(_INFRA_ERR_PREFIX)]

    try:
        request_data = {
            "scene": scene,
            "job_id": job_id,
            "error_log": error_log,
            "error_history": history[-4:] or None,
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
        code_path = res.get("code_path")
        if not code_path:
            # Contract violation: 200 with no code_path.
            err = f"code-generator returned no code_path (keys: {sorted(res)})"
            logger.error(f"[PARALLEL] {err} for scene {scene_id}")
            return scene_id, None, err, _span("code_generator_node", t0, scene_id=scene_id, status="error", error=err), False
        logger.info(f"[PARALLEL] Code generated for scene {scene_id}: {code_path}")
        return scene_id, code_path, None, _span("code_generator_node", t0, scene_id=scene_id), False
    except InfraUnavailable as e:
        logger.error(f"[PARALLEL] Code generation infra failure for scene {scene_id}: {e}")
        return scene_id, None, str(e), _span("code_generator_node", t0, scene_id=scene_id, status="error", error=e), True
    except Exception as e:
        logger.error(f"[PARALLEL] Code generation failed for scene {scene_id}: {e}")
        return scene_id, None, str(e), _span("code_generator_node", t0, scene_id=scene_id, status="error", error=e), False


async def art_director_node(state: LangGraphState):
    """Pick one visual style for the whole job — zero LLM calls, pure dict lookup.

    Resolution order:
    1. Already set (resume-safe skip).
    2. User picked a style via brief answers (question_id="style").
    3. Auto-pick from topic_classification in script_meta using TOPIC_STYLE_MAP.
    4. Fallback: "swiss_pulse".
    """
    t0 = time.time()
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
    return {"job_style": style, "node_timings": (state.get("node_timings") or []) + [_span("art_director_node", t0)]}


async def image_fetcher_node(state: LangGraphState):
    """Fetch stock images for HyperFrames scenes BEFORE code-gen so each scene can
    compose its own background imagery (Option B). Manim scenes stay image-free
    (vector/math). Resume-safe (skips if already fetched) and never fatal — images
    are an enhancement, so any failure degrades to no-images, not a job failure."""
    t0 = time.time()
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
        return {"image_paths": image_paths, "status": "image_fetch",
                "node_timings": (state.get("node_timings") or []) + [_span("image_fetcher_node", t0)]}
    except Exception as e:
        logger.error(f"Image fetcher node failed (continuing without images): {e}")
        return {"image_paths": {}, "status": "image_fetch",
                "node_timings": (state.get("node_timings") or []) + [_span("image_fetcher_node", t0, status="error", error=e)]}


async def code_generator_node(state: LangGraphState):
    logger.info("Executing Code Generator Node (PARALLEL)")
    try:
        script = state["script"]
        job_id = state["job_id"]
        render_paths = state.get("render_paths", {})
        new_code_paths = dict(state.get("code_paths", {}))
        new_previous_code = dict(state.get("previous_code", {}))
        new_retry_counts = dict(state.get("retry_counts", {}))
        new_infra_counts = dict(state.get("infra_retry_counts", {}))
        new_error_logs = dict(state.get("error_logs", {}))
        new_error_history = {k: list(v) for k, v in (state.get("error_history", {}) or {}).items()}

        # Collect scenes that need (re)generation
        scenes_to_generate = [
            scene for scene in script["scenes"]
            if scene["scene_id"] not in render_paths
            and _scene_retryable(state, scene["scene_id"])
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

        spans = []
        infra_failures = 0
        for scene_id, code_path, error, span, is_infra in results:
            spans.append(span)
            if code_path:
                new_code_paths[scene_id] = code_path
                new_error_logs.pop(scene_id, None)
                # Read generated code for retry context
                try:
                    with open(code_path, "r") as f:
                        new_previous_code[scene_id] = f.read()
                except Exception as read_err:
                    # Don't leave a STALE previous round's code in the retry
                    # context — the LLM would "fix" code it didn't produce.
                    logger.warning(f"Could not read generated code for scene {scene_id} "
                                   f"({code_path}): {read_err}; dropping retry context")
                    new_previous_code.pop(scene_id, None)
            elif is_infra:
                # Service outage: burns the (separate) infra budget only, so a
                # brief 502 window can't permanently fail the job.
                infra_failures += 1
                new_infra_counts[scene_id] = new_infra_counts.get(scene_id, 0) + 1
                new_error_logs[scene_id] = _INFRA_ERR_PREFIX + (error or "service unavailable")
            else:
                # Count code-gen failures against the retry cap. Without this the
                # scene never enters code_paths, the validator never bumps its
                # count, and validation_router loops back forever (GraphRecursionError).
                logger.error(f"Scene {scene_id} code generation failed: {error}")
                new_retry_counts[scene_id] = new_retry_counts.get(scene_id, 0) + 1
                new_error_logs[scene_id] = error or "code generation failed"
                new_error_history.setdefault(scene_id, []).append({
                    "attempt": new_retry_counts[scene_id], "source": "codegen",
                    "error": (error or "code generation failed")[:400],
                })
                log_render_failure(
                    job_id=job_id, scene_id=scene_id,
                    content_type=next((s.get("content_type") for s in scenes_to_generate if s["scene_id"] == scene_id), None),
                    attempt=new_retry_counts[scene_id], error_text=error or "code generation failed",
                    code_text=new_previous_code.get(scene_id), model=settings.CODE_GENERATOR_MODEL, source="codegen",
                )
                # Drop the stale code from the previous round, otherwise the
                # validator re-renders the exact code that already failed —
                # a wasted render (up to minutes) plus a double retry bump.
                new_code_paths.pop(scene_id, None)

        if infra_failures == len(results) and results:
            # Total outage: every scene failed on transport. Fail fast with a
            # clear reason instead of looping the graph — the job stays resumable.
            return {
                "retry_counts": new_retry_counts,
                "infra_retry_counts": new_infra_counts,
                "error_logs": new_error_logs,
                "status": "failed",
                "overall_error": f"code-generator unavailable: {new_error_logs.get(results[0][0], 'transport failure')}",
                "node_timings": (state.get("node_timings") or []) + spans,
            }

        return {
            "code_paths": new_code_paths,
            "previous_code": new_previous_code,
            "retry_counts": new_retry_counts,
            "infra_retry_counts": new_infra_counts,
            "error_logs": new_error_logs,
            "error_history": new_error_history,
            "status": "code_generation",
            "node_timings": (state.get("node_timings") or []) + spans,
        }
    except Exception as e:
        logger.error(f"Code Generator node failed: {e}")
        return {"status": "failed", "overall_error": str(e) or f"{type(e).__name__}"}


async def _validate_one_scene(scene_id: int, code_path: str, job_id: str,
                              content_type: str | None = None,
                              scene_plan: dict | None = None) -> tuple:
    """Validate a single scene.

    Returns (scene_id, render_path, error_log, span, is_infra) — is_infra marks
    a service-unavailable failure that must not burn the content retry budget."""
    t0 = time.time()
    try:
        req = {"job_id": job_id, "scene_id": scene_id, "code_path": code_path,
               "content_type": content_type,
               # Scene intent → the validator's vision quality gate scores the
               # rendered frames against what the scene is supposed to teach.
               "narration_text": (scene_plan or {}).get("narration_text"),
               "visual_description": (scene_plan or {}).get("visual_description"),
               # Slot budget → the validator rejects renders that overshoot it
               # (dead-air gap: silent static video after narration ends).
               "expected_duration_seconds": (scene_plan or {}).get("estimated_duration_seconds")}
        res = await _post(f"{settings.VALIDATOR_URL}/validate", req)
        if res.get("success") and res.get("render_path"):
            logger.info(f"[PARALLEL] Scene {scene_id} validated OK: {res['render_path']}")
            return scene_id, res["render_path"], None, _span("validator_node", t0, scene_id=scene_id), False
        else:
            logger.warning(f"[PARALLEL] Scene {scene_id} validation failed")
            err = res.get("error_log") or "validation failed (no error_log in response)"
            return scene_id, None, err, _span("validator_node", t0, scene_id=scene_id, status="error"), False
    except InfraUnavailable as e:
        logger.error(f"[PARALLEL] Validator infra failure for scene {scene_id}: {e}")
        return scene_id, None, str(e), _span("validator_node", t0, scene_id=scene_id, status="error", error=e), True
    except Exception as e:
        logger.error(f"[PARALLEL] Validator error for scene {scene_id}: {e}")
        return scene_id, None, str(e), _span("validator_node", t0, scene_id=scene_id, status="error", error=e), False


async def validator_node(state: LangGraphState):
    logger.info("Executing Validator Node (PARALLEL)")
    try:
        job_id = state["job_id"]
        new_render_paths = dict(state.get("render_paths", {}))
        new_error_logs = dict(state.get("error_logs", {}))
        new_retry_counts = dict(state.get("retry_counts", {}))
        new_infra_counts = dict(state.get("infra_retry_counts", {}))
        new_error_history = {k: list(v) for k, v in (state.get("error_history", {}) or {}).items()}

        # Collect scenes that need validation
        scenes_to_validate = [
            (scene_id, code_path)
            for scene_id, code_path in state["code_paths"].items()
            if scene_id not in new_render_paths
            and _scene_retryable(state, scene_id)
        ]

        if not scenes_to_validate:
            logger.info("No scenes need validation.")
            return {
                "render_paths": new_render_paths,
                "error_logs": new_error_logs,
                "retry_counts": new_retry_counts,
                "infra_retry_counts": new_infra_counts,
                "status": "validation"
            }

        logger.info(f"Validating {len(scenes_to_validate)} scenes in parallel...")

        # Bound in-flight validations to the validator's render capacity so
        # queued requests don't burn their HTTP clock waiting behind renders.
        # Pass the script-writer's authoritative content_type so the validator
        # routes without sniffing file contents.
        plan_by_id = {s["scene_id"]: s for s in state["script"]["scenes"]}
        tasks = [_validate_one_scene(sid, cpath, job_id,
                                     (plan_by_id.get(sid) or {}).get("content_type"),
                                     plan_by_id.get(sid))
                 for sid, cpath in scenes_to_validate]
        results = await _bounded_gather(tasks, settings.VALIDATOR_MAX_CONCURRENT_RENDERS or 2)

        spans = []
        infra_failures = 0
        for scene_id, render_path, error_log, span, is_infra in results:
            spans.append(span)
            if render_path:
                new_render_paths[scene_id] = render_path
                new_error_logs.pop(scene_id, None)
            elif is_infra:
                infra_failures += 1
                new_infra_counts[scene_id] = new_infra_counts.get(scene_id, 0) + 1
                new_error_logs[scene_id] = _INFRA_ERR_PREFIX + (error_log or "service unavailable")
            else:
                new_error_logs[scene_id] = error_log
                new_retry_counts[scene_id] = new_retry_counts.get(scene_id, 0) + 1
                new_error_history.setdefault(scene_id, []).append({
                    "attempt": new_retry_counts[scene_id], "source": "render",
                    "error": (error_log or "render failed")[:400],
                })
                log_render_failure(
                    job_id=job_id, scene_id=scene_id,
                    content_type=next((s.get("content_type") for s in state["script"]["scenes"] if s["scene_id"] == scene_id), None),
                    attempt=new_retry_counts[scene_id], error_text=error_log or "render failed",
                    code_text=(state.get("previous_code") or {}).get(scene_id),
                    model=settings.CODE_GENERATOR_MODEL, source="render",
                )

        if infra_failures == len(results) and results and not new_render_paths:
            # Validator fully down and nothing rendered yet — fail fast, resumable.
            return {
                "retry_counts": new_retry_counts,
                "infra_retry_counts": new_infra_counts,
                "error_logs": new_error_logs,
                "status": "failed",
                "overall_error": f"validator unavailable: {new_error_logs.get(results[0][0], 'transport failure')}",
                "node_timings": (state.get("node_timings") or []) + spans,
            }

        return {
            "render_paths": new_render_paths,
            "error_logs": new_error_logs,
            "retry_counts": new_retry_counts,
            "infra_retry_counts": new_infra_counts,
            "error_history": new_error_history,
            "status": "validation",
            "node_timings": (state.get("node_timings") or []) + spans,
        }
    except Exception as e:
        logger.error(f"Validator node failed: {e}")
        return {"status": "failed", "overall_error": str(e)}


def validation_router(state: LangGraphState) -> Literal["code_generator_node", "assembler_node", "failed"]:
    if state.get("overall_error") is not None:
        return "failed"

    script = state.get("script")
    if not script or not script.get("scenes"):
        # Contract violation (state corrupted / partial resume) — never crash the
        # router with a TypeError; route to the failure sink with a clear reason.
        logger.error("validation_router: no script in state — failing job")
        return "failed"
    render_paths = state.get("render_paths", {})

    all_success = True
    needs_retry = False

    for scene in script["scenes"]:
        scene_id = scene["scene_id"]
        if scene_id not in render_paths:
            all_success = False
            if _scene_retryable(state, scene_id):  # same predicate as both nodes
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
    """Generate voiceover for one scene.

    Returns (scene_id, audio_path, segments, error, span, is_infra) — mirrors
    _generate_one_scene / _validate_one_scene's tuple shape (trailing is_infra
    flag) so a failed scene's error and infra-vs-content classification can be
    folded into the SAME retry bookkeeping code-gen/render use. segments is the
    per-sentence cue sheet [{text,start,duration}] or None."""
    t0 = time.time()
    scene_id = scene["scene_id"]
    if scene_id in existing:
        # resume: keep existing audio + state segments
        return scene_id, existing[scene_id], None, None, None, False
    try:
        req = {
            "job_id": job_id,
            "scene_id": scene_id,
            "narration_text": scene["narration_text"]
        }
        res = await _post(f"{settings.VOICEOVER_URL}/generate", req)
        audio_path = res.get("audio_path")
        if not audio_path:
            # Contract violation: 200 with no audio_path (mirrors code-gen's
            # "200 with no code_path" handling below) — treated as a real,
            # retryable failure, never a silent pass to a soundless scene.
            err = f"voiceover returned no audio_path (keys: {sorted(res)})"
            logger.error(f"[PARALLEL] {err} for scene {scene_id}")
            return (scene_id, None, None, err,
                    _span("voiceover_node", t0, scene_id=scene_id, status="error", error=err), False)
        provider = res.get("provider_used", "unknown")
        fallback = " (fallback)" if res.get("fallback_used") else ""
        segs = res.get("segments")
        logger.info(f"[PARALLEL] Voiceover done for scene {scene_id}: {provider}{fallback} "
                    f"({len(segs or [])} cues)")
        return scene_id, audio_path, segs, None, _span("voiceover_node", t0, scene_id=scene_id), False
    except InfraUnavailable as e:
        logger.error(f"[PARALLEL] Voiceover infra failure for scene {scene_id}: {e}")
        return (scene_id, None, None, str(e),
                _span("voiceover_node", t0, scene_id=scene_id, status="error", error=e), True)
    except Exception as e:
        logger.error(f"[PARALLEL] Voiceover failed for scene {scene_id}: {e}")
        return (scene_id, None, None, str(e),
                _span("voiceover_node", t0, scene_id=scene_id, status="error", error=e), False)


async def voiceover_node(state: LangGraphState):
    """Voiceover — runs BEFORE code-gen so each scene's per-sentence cue sheet
    (audio_segments) is available to time animation beats to the spoken words.
    Voices ALL scenes (render hasn't happened yet).

    A scene whose narration fails is RETRYABLE against the exact same
    per-scene budget code-gen/render failures use: retry_counts /
    infra_retry_counts, gated by _scene_retryable (MAX_SCENE_RETRIES /
    MAX_INFRA_RETRIES). Unlike code_generator_node <-> validator_node, this
    node has no conditional edge looping back to itself (voiceover runs once,
    pre-code), so the retry rounds are driven by a local loop here instead of
    graph re-entry — but the bookkeeping is identical, which is what makes the
    rest of the pipeline handle an exhausted scene for free: once this loop
    burns a scene's shared budget down to zero, code_generator_node's own
    `_scene_retryable` check already excludes that scene from code-gen, so it
    never renders and validation_router's existing graceful-degradation path
    drops it (or fails the job if nothing rendered) exactly like a code-gen/
    render failure. No scene can reach the assembler with a missing audio_path
    while narration was still retryable, and an exhausted scene's failure is
    recorded in error_logs/error_history (source="voiceover") so it is visible
    in job state/warnings/failed_node's message instead of passing silently."""
    logger.info("Executing Voiceover Node (PARALLEL, pre-code for A/V sync)")
    try:
        job_id = state["job_id"]
        script = state["script"]
        scenes = script["scenes"]

        new_audio_paths = dict(state.get("audio_paths", {}))
        new_segments = dict(state.get("audio_segments", {}))
        new_retry_counts = dict(state.get("retry_counts", {}))
        new_infra_counts = dict(state.get("infra_retry_counts", {}))
        new_error_logs = dict(state.get("error_logs", {}))
        new_error_history = {k: list(v) for k, v in (state.get("error_history", {}) or {}).items()}
        vo_spans = []

        # Partial state view for _scene_retryable — new_retry_counts/new_infra_counts
        # are mutated in place below, so this always reflects the latest budget.
        budget_state = {"retry_counts": new_retry_counts, "infra_retry_counts": new_infra_counts}

        pending = [s for s in scenes
                   if s["scene_id"] not in new_audio_paths and _scene_retryable(budget_state, s["scene_id"])]

        round_num = 0
        while pending:
            round_num += 1
            logger.info(f"Voiceover round {round_num}: retrying {len(pending)} scene(s) "
                        f"{[s['scene_id'] for s in pending]}")
            vo_tasks = [_generate_voiceover(scene, job_id, new_audio_paths) for scene in pending]
            vo_results = await _bounded_gather(vo_tasks, settings.ORCH_VOICEOVER_CONCURRENCY)

            for scene_id, audio_path, segments, error, span, is_infra in vo_results:
                if span:
                    vo_spans.append(span)
                if audio_path:
                    new_audio_paths[scene_id] = audio_path
                    new_error_logs.pop(scene_id, None)
                    if segments:                       # don't clobber resume-preserved cues
                        new_segments[scene_id] = segments
                elif is_infra:
                    # Service outage: burns the (separate) infra budget only, so a
                    # brief 502 window can't permanently fail the scene. Mirrors
                    # code_generator_node/validator_node.
                    new_infra_counts[scene_id] = new_infra_counts.get(scene_id, 0) + 1
                    new_error_logs[scene_id] = _INFRA_ERR_PREFIX + (error or "service unavailable")
                else:
                    new_retry_counts[scene_id] = new_retry_counts.get(scene_id, 0) + 1
                    new_error_logs[scene_id] = error or "voiceover failed"
                    new_error_history.setdefault(scene_id, []).append({
                        "attempt": new_retry_counts[scene_id], "source": "voiceover",
                        "error": (error or "voiceover failed")[:400],
                    })

            # Re-filter against the just-updated budget — a scene only stays
            # pending if it's still missing audio AND still retryable; this is
            # guaranteed to shrink to empty since every failure branch above
            # increments one of the two counters _scene_retryable checks.
            pending = [s for s in pending
                       if s["scene_id"] not in new_audio_paths and _scene_retryable(budget_state, s["scene_id"])]

        failed_scenes = sorted(s["scene_id"] for s in scenes if s["scene_id"] not in new_audio_paths)

        if failed_scenes and not new_audio_paths:
            return {
                "audio_paths": new_audio_paths,
                "retry_counts": new_retry_counts,
                "infra_retry_counts": new_infra_counts,
                "error_logs": new_error_logs,
                "error_history": new_error_history,
                "status": "failed",
                "overall_error": f"Voiceover failed for ALL scenes: {failed_scenes}",
                "node_timings": (state.get("node_timings") or []) + vo_spans,
            }
        if failed_scenes:
            logger.warning(
                f"Voiceover exhausted retry budget for scenes {failed_scenes}; "
                f"these scenes will be excluded downstream (code_generator_node's "
                f"_scene_retryable check already sees their spent budget) so no "
                f"soundless scene reaches the assembler — "
                f"continuing with {len(new_audio_paths)}/{len(scenes)} narrated scenes"
            )

        return {
            "audio_paths": new_audio_paths,
            "audio_segments": new_segments,
            "retry_counts": new_retry_counts,
            "infra_retry_counts": new_infra_counts,
            "error_logs": new_error_logs,
            "error_history": new_error_history,
            "status": "voiceover",
            "node_timings": (state.get("node_timings") or []) + vo_spans,
        }
    except Exception as e:
        logger.error(f"Voiceover node failed: {e}")
        return {"status": "failed", "overall_error": str(e)}


async def assembler_node(state: LangGraphState):
    t0 = time.time()
    logger.info("Executing Assembler Node")
    # Emit status="assembly" immediately so the stage tracker in run_pipeline records
    # assembly time separately from validation time. Without this, the entire assembly
    # duration gets attributed to the "validation" stage (last emitted status).
    yield {**state, "status": "assembly"}
    try:
        req = {
            "job_id": state["job_id"],
            "render_paths": state["render_paths"],
            "audio_paths": state["audio_paths"],
            "scene_plans": state["script"]["scenes"],
            "image_paths": state.get("image_paths", {}),
            "script_title": state["script"].get("title", ""),
            "job_style": state.get("job_style"),
            "audio_segments": state.get("audio_segments", {}),
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
        dropped_scenes = set(
            s["scene_id"] for s in state["script"]["scenes"] if s["scene_id"] not in render_paths
        )
        res = await _post(
            f"{settings.ASSEMBLER_URL}/assemble", req,
            timeout=assembler_http_timeout_s(planned_total),
        )
        # The assembler may also drop scenes it couldn't compose (e.g. a HyperFrames
        # scene whose CSS wouldn't compile) — fold those in so they're reported too.
        dropped_scenes |= set(res.get("dropped_scene_ids", []) or [])
        dropped_scenes = sorted(dropped_scenes)

        # Post-assembly film QA: the compositor scanned the final film and
        # flagged scenes whose slot is black/static/silent (scene_id -> critique,
        # keys arrive as JSON strings). Send them back through the SAME code-gen
        # retry loop a render failure uses — but at most ONE film-QA-triggered
        # round per scene (checked via error_history source="film_qa"), so
        # re-assembly can't ping-pong forever on a scene QA keeps disliking.
        for issue in res.get("qa_film_issues") or []:
            logger.error(f"film QA film-level issue (not scene-retryable): {issue}")
        qa_flagged = {int(k): v for k, v in (res.get("qa_flagged") or {}).items()}
        history = state.get("error_history", {}) or {}
        qa_retry = [
            sid for sid in sorted(qa_flagged)
            if _scene_retryable(state, sid)
            and not any(h.get("source") == "film_qa" for h in history.get(sid, []))
        ]
        if qa_retry:
            new_retry_counts = dict(state.get("retry_counts", {}))
            new_error_logs = dict(state.get("error_logs", {}))
            new_error_history = {k: list(v) for k, v in history.items()}
            for sid in qa_retry:
                new_retry_counts[sid] = new_retry_counts.get(sid, 0) + 1
                new_error_logs[sid] = qa_flagged[sid]
                new_error_history.setdefault(sid, []).append({
                    "attempt": new_retry_counts[sid], "source": "film_qa",
                    "error": qa_flagged[sid][:400],
                })
                log_render_failure(
                    job_id=state["job_id"], scene_id=sid,
                    content_type=next((s.get("content_type", "manim")
                                       for s in state["script"]["scenes"]
                                       if s["scene_id"] == sid), "manim"),
                    attempt=new_retry_counts[sid], error_text=qa_flagged[sid],
                    code_text=(state.get("previous_code") or {}).get(sid),
                    model=settings.CODE_GENERATOR_MODEL, source="film_qa",
                )
            logger.warning(f"film QA: regenerating scenes {qa_retry} and re-assembling")
            yield {"render_paths": {k: v for k, v in state["render_paths"].items()
                                    if k not in qa_retry},
                   "retry_counts": new_retry_counts,
                   "error_logs": new_error_logs,
                   "error_history": new_error_history,
                   "qa_retry_scenes": qa_retry,
                   "status": "validation",
                   "node_timings": (state.get("node_timings") or []) + [_span("assembler_node", t0, status="qa_retry")]}
            return
        if qa_flagged:
            logger.warning(
                f"film QA flagged scenes {sorted(qa_flagged)} but their retry "
                f"budget (or one-round film-QA budget) is spent — shipping as-is")
        # "completed" only when every scene made it into the cut. If the validator
        # dropped some (code-gen exhausted retries) OR the assembler had to drop a
        # bad scene, the film is a degraded subset — report "partial" so the API/UI
        # don't claim a full "ready" film. Resumable.
        final_status = "partial" if dropped_scenes else "completed"
        yield {"final_output_path": res["final_output_path"],
               "intro_duration_seconds": res.get("intro_duration_seconds", 0.0),
               "dropped_scenes": dropped_scenes, "status": final_status,
               # Surface unfixable QA critiques in error_logs; clear the retry
               # route flag so stale state can't re-fire the QA loop.
               "error_logs": {**(state.get("error_logs") or {}), **qa_flagged},
               "qa_retry_scenes": [],
               "node_timings": (state.get("node_timings") or []) + [_span("assembler_node", t0)]}
    except Exception as e:
        logger.error(f"Assembler failed: {e}")
        yield {"status": "failed", "overall_error": str(e),
               "node_timings": (state.get("node_timings") or []) + [_span("assembler_node", t0, status="error", error=e)]}


def assembler_router(state: LangGraphState) -> str:
    """Loop film-QA-flagged scenes back through code-gen -> validator ->
    assembler; otherwise the film is shipped (or the assembler failed) — END
    either way, exactly like the old unconditional assembler -> END edge."""
    if state.get("overall_error"):
        return END
    return "code_generator_node" if state.get("qa_retry_scenes") else END


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
# Film QA loop-back: flagged scenes re-enter the code-gen <-> validator retry
# cycle, then re-assemble; qa_retry_scenes==[] (the shipped/failed paths) ends.
workflow.add_conditional_edges("assembler_node", assembler_router,
    {"code_generator_node": "code_generator_node", END: END})
workflow.add_edge("failed",         END)

app_graph = workflow.compile()
