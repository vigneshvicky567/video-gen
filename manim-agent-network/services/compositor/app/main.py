import asyncio
import json
import os
import shutil
import subprocess
import logging
import tempfile
import traceback
from pathlib import Path

from shared.proc import run_proc, ProcTimeout

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from shared.config import settings
from shared.schemas.requests import AssemblerRequest
from shared.schemas.responses import AssemblerResponse
from shared.timeouts import chunk_render_timeout_s
from shared.log import get_logger, set_log_context, timed_block, log_subprocess, log_file, make_request_logging_middleware

from .duration_prober import compute_scene_timings, probe_duration, freeze_pad_renders, AssemblyError
from .film_qa import run_film_qa
from .llm_composer import compose_html, build_vtt
from shared.render_errors import log_render_failure
from .html_validator import validate_composition
from .chunking import partition_timings, rebase_chunk, slot_seconds
from .postprocess import finalize_film

# Overridable for host-side testing; the Docker image installs hyperframes here.
HYPERFRAMES_CLI = os.getenv(
    "HYPERFRAMES_CLI", "/usr/local/lib/node_modules/hyperframes/dist/cli.js"
)

app = FastAPI(title="Compositor Service")
app.add_middleware(make_request_logging_middleware("compositor"))
logger = get_logger(__name__)

# Per-job assembly dedup: if /assemble arrives while one is already running for
# the same job_id, the second caller waits on the same asyncio.Future and gets
# the same result. This prevents chunk-file races when the orchestrator restarts
# mid-assembly and sends a second POST before the first finishes.
_ASSEMBLING: dict = {}   # job_id -> asyncio.Future[AssemblerResponse]
_ASSEMBLING_LOCK = asyncio.Lock()


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "compositor"}


class LintRequest(BaseModel):
    html_path: str


def _run_qa_subcommand(subcommand: str, td: str) -> str:
    """Run one HyperFrames QA subcommand and return its stdout, or "" on any
    failure. Covers both an exception (timeout, missing binary) AND the way
    an unknown subcommand actually fails on this CLI: it exits non-zero and
    prints the general help listing to stdout instead of raising, so there's
    no exception to catch there — the caller detects that case by finding no
    parseable JSON in the returned string. Never raises: QA is best-effort
    and must never fail scene lint, let alone assembly.
    """
    try:
        qa_result = subprocess.run(
            ["node", HYPERFRAMES_CLI, subcommand, td, "--json"],
            capture_output=True, text=True, timeout=120,
        )
        return qa_result.stdout or ""
    except Exception as exc:
        logger.warning(f"hyperframes {subcommand} (layout/contrast QA) failed to run: {exc}")
        return ""


def _parse_qa_json(stdout: str):
    """Parse a QA subcommand's stdout with the same find('{')-then-json.loads
    pattern used for `lint`/`check` output below. Returns None (not {}) when
    nothing parseable came back, so callers can tell "ran, zero findings"
    apart from "produced no usable output at all" (missing subcommand,
    crash, timeout) — the latter is what should trigger a fallback.
    """
    json_start = stdout.find("{")
    if json_start < 0:
        return None
    try:
        return json.loads(stdout[json_start:])
    except Exception:
        return None


def _contrast_entry_to_finding(entry: dict) -> dict:
    """Normalize one `validate --json` contrast-failure entry into the same
    code/severity/message/fixHint shape `check` and `inspect` findings use.

    `validate` (the pre-`check` WCAG audit, confirmed still present on the
    pinned hyperframes 0.6.97) reports failures as bare measurement dicts
    (ratio/fg/bg/selector/time) with no code or message of their own, unlike
    `inspect`'s `issues`, which already carry this shape natively.
    """
    return {
        "code": "contrast_wcag_aa_fail",
        "severity": "warning",
        "message": (
            f"WCAG AA contrast failure on \"{entry.get('selector', '?')}\" "
            f"at {entry.get('time', '?')}s (ratio {entry.get('ratio', '?')}, "
            f"fg {entry.get('fg', '?')} on bg {entry.get('bg', '?')})"
        ),
        "fixHint": "Increase foreground/background contrast to meet WCAG AA "
                   "(4.5:1 normal text, 3:1 large text).",
    }


@app.post("/lint")
async def lint_scene(request: LintRequest):
    """Run `hyperframes lint` plus rendered-pixel QA against a scene HTML file.

    Called by the validator for HyperFrames scenes so real lint findings
    (orphan timelines, opacity no-ops, repeat:-1, Math.random, ...) reach the
    code-generator's retry prompt instead of surfacing as a blank scene at
    render time. Permissive on tooling failure: if lint itself cannot run,
    returns ok=True so the pipeline degrades to the regex-level checks.

    Also runs headless-Chrome layout-overflow and WCAG-contrast QA, which
    static lint can't see. Tries the merged `hyperframes check` subcommand
    first; the compositor image pins hyperframes 0.6.97
    (infrastructure/docker/Dockerfile.compositor), which predates `check`, so
    there this falls back to the older split subcommands 0.6.97 does have —
    `inspect` (layout overflow) and `validate` (WCAG contrast) — normalizing
    both into the same finding shape. Its findings are QA signal, not lint
    errors: they are always folded into `warnings` (never `errors`/`ok`). If
    none of `check`/`inspect`/`validate` produce usable output at all (an
    even older or unrecognized CLI), that's logged once as a warning so the
    gap is visible to operators, and lint still proceeds normally — a QA-only
    subcommand can never fail scene lint or assembly.
    """
    src = Path(request.html_path)
    if not src.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {src}")

    def _run_lint_and_qa() -> tuple:
        with tempfile.TemporaryDirectory() as td:
            shutil.copyfile(src, Path(td) / "index.html")
            # Non-zero exit means findings exist, not a tool failure.
            result = subprocess.run(
                ["node", HYPERFRAMES_CLI, "lint", td, "--json"],
                capture_output=True, text=True, timeout=120,
            )

            # Layout/contrast QA: try the merged `check` subcommand first.
            check_stdout = _run_qa_subcommand("check", td)
            check_data = _parse_qa_json(check_stdout)
            if check_data is not None and ("layout" in check_data or "contrast" in check_data):
                qa_stdout = check_stdout
            else:
                # `check` unavailable on this CLI version (e.g. the pinned
                # 0.6.97) — fall back to inspect + validate. Both still work
                # (deprecated-alias style) on newer CLIs too, but only run
                # here, after `check` already failed, so the browser-QA pass
                # isn't paid for twice on a CLI that does have `check`.
                inspect_data = _parse_qa_json(_run_qa_subcommand("inspect", td))
                validate_data = _parse_qa_json(_run_qa_subcommand("validate", td))
                if inspect_data is None and validate_data is None:
                    logger.warning(
                        "HyperFrames layout/contrast QA unavailable: none of "
                        "`check`, `inspect`, `validate` produced parseable "
                        f"JSON on the installed CLI ({HYPERFRAMES_CLI}) — "
                        "the layout/contrast QA gate is not running for this scene."
                    )
                    qa_stdout = ""
                else:
                    layout_findings = (inspect_data or {}).get("issues", [])
                    contrast_findings = [
                        _contrast_entry_to_finding(e)
                        for e in (validate_data or {}).get("contrast", [])
                    ]
                    qa_stdout = json.dumps({
                        "layout": {"findings": layout_findings},
                        "contrast": {"findings": contrast_findings},
                    })
        return result.stdout or "", qa_stdout

    try:
        # Worker thread: validator lints scenes in parallel and a blocking
        # subprocess here would stall the event loop (and /health).
        import asyncio
        stdout, qa_stdout = await asyncio.to_thread(_run_lint_and_qa)
        json_start = stdout.find("{")
        data = json.loads(stdout[json_start:]) if json_start >= 0 else {}
    except Exception as exc:
        if settings.COMPOSITOR_FAIL_CLOSED:
            logger.error(f"hyperframes lint unavailable (fail-closed): {exc}")
            raise HTTPException(status_code=503, detail=f"lint unavailable: {exc}")
        logger.warning(f"hyperframes lint unavailable, skipping: {exc}")
        return {"ok": True, "errors": [], "warnings": [], "lint_ran": False}

    errors = []
    warnings = []
    for f in data.get("findings", []):
        line = f"{f.get('code')}: {f.get('message', '')}"
        if f.get("fixHint"):
            line += f" FIX: {f['fixHint']}"
        if f.get("severity") == "error":
            errors.append(line)
        elif f.get("severity") == "warning":
            warnings.append(line)

    # Layout-overflow / contrast QA (best-effort, never raises). Any finding
    # here — regardless of the CLI's own severity label — is recorded as a
    # warning only: there's no existing fail-closed policy for these (unlike
    # lint errors above), so we don't invent one.
    try:
        qa_json_start = qa_stdout.find("{")
        qa_data = json.loads(qa_stdout[qa_json_start:]) if qa_json_start >= 0 else {}
        for section in ("layout", "contrast"):
            for f in qa_data.get(section, {}).get("findings", []):
                line = f"{f.get('code')}: {f.get('message', '')}"
                if f.get("fixHint"):
                    line += f" FIX: {f['fixHint']}"
                warnings.append(line)
    except Exception as exc:
        logger.warning(f"hyperframes layout/contrast QA output unparseable, skipping QA findings: {exc}")

    return {"ok": not errors, "errors": errors, "warnings": warnings, "lint_ran": True}


def _render_command(output_path: Path) -> list:
    cmd = [
        "node", HYPERFRAMES_CLI, "render",
        "--output", str(output_path),
        "--fps", "30",
        "--quality", "high",
        "--workers", str(settings.COMPOSITOR_RENDER_WORKERS),
    ]
    # GPU flags: --browser-gpu = Chrome WebGL via EGL (hardware shaders/capture),
    # --gpu = ffmpeg NVENC H.264 encoding. Both require the NVIDIA runtime
    # (deploy.resources.reservations.devices in docker-compose). No-op / graceful
    # fallback if no GPU is present (HyperFrames falls back to SwiftShader/SW encode).
    if os.getenv("COMPOSITOR_GPU_RENDER", "1") != "0":
        cmd += ["--browser-gpu", "--gpu"]
    return cmd


def _run_render_subprocess(cmd: list, cwd: str, timeout_s: int):
    """Run HyperFrames with a process-TREE kill on timeout.

    subprocess.run(timeout=) only kills the parent process, not its workers.
    HyperFrames uses --workers N, so N worker node processes inherit the
    stdout/stderr pipe and keep it open after the parent is killed, causing
    communicate() to block forever. shared.proc.run_proc kills the whole tree
    (killpg on POSIX, taskkill /T on Windows) so the pipe is released — and it
    works on the win32 dev host where os.setsid/killpg don't exist.
    """
    try:
        return run_proc(cmd, timeout=timeout_s, cwd=cwd)
    except ProcTimeout:
        raise AssemblyError(
            f"HyperFrames chunk render timed out after {timeout_s}s "
            f"(killed entire process tree)"
        )


async def _render_project(comp_dir: Path, output_path: Path, timeout_s: int) -> None:
    """Render the composition rooted at comp_dir/index.html to output_path.

    Runs the blocking subprocess in a worker thread so the event loop (and
    /health, /lint) stay responsive during a multi-minute render.
    """
    cmd = _render_command(output_path)
    with timed_block(logger, "HyperFrames render"):
        result = await asyncio.to_thread(
            _run_render_subprocess, cmd, str(comp_dir), timeout_s
        )
    log_subprocess(logger, cmd, result, label="hyperframes")
    if result.returncode != 0:
        raise AssemblyError(
            f"HyperFrames render failed (rc={result.returncode}):\n"
            f"STDOUT: {result.stdout[:1000]}\n"
            f"STDERR: {result.stderr[:1000]}"
        )
    if not output_path.exists():
        raise AssemblyError(f"Output file missing after render: {output_path}")
    if output_path.stat().st_size == 0:
        raise AssemblyError(f"Output file is empty: {output_path}")


def _promote_to_index(html_path: str, comp_dir: Path) -> None:
    """Make html_path the project's single entry point (index.html)."""
    index_path = comp_dir / "index.html"
    src = Path(html_path)
    if src.resolve() == index_path.resolve():
        return
    if not src.exists():
        return  # nothing to move (e.g. compose_html already wrote index.html)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.unlink(missing_ok=True)
    src.rename(index_path)


def _has_audio_stream(path: Path) -> bool:
    """True iff ffprobe positively reports an audio stream.

    Probe FAILURE returns False (not True): 'unknown' must not be certified as
    'has audio' — a wrong True here silently corrupts the -c copy concat with a
    stream-layout mismatch. False routes the chunk through silent-audio muxing,
    which is always safe.
    """
    try:
        result = run_proc(
            ["ffprobe", "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
            timeout=60,
        )
        if result.returncode != 0:
            logger.warning("ffprobe failed checking audio; treating as no-audio",
                           extra={"path": str(path), "stderr": (result.stderr or "")[:200]})
            return False
        return bool(result.stdout.strip())
    except Exception as e:
        logger.warning("ffprobe error checking audio; treating as no-audio",
                       extra={"path": str(path), "error": str(e)[:200]})
        return False


def _normalize_audio_streams(chunk_paths: list) -> list:
    """Concat with -c copy requires a consistent stream layout. If some chunks
    have audio and some don't (a chunk whose scenes all lost TTS), mux silent
    audio into the audioless ones. Returns the (possibly replaced) path list.
    """
    has_audio = [_has_audio_stream(p) for p in chunk_paths]
    if all(has_audio) or not any(has_audio):
        return chunk_paths  # uniform — nothing to do

    fixed: list = []
    for path, ok in zip(chunk_paths, has_audio):
        if ok:
            fixed.append(path)
            continue
        out = path.with_name(path.stem + "_aud.mp4")
        cmd = [
            "ffmpeg", "-y", "-i", str(path),
            "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-shortest", "-c:v", "copy", "-c:a", "aac", str(out),
        ]
        result = run_proc(cmd, timeout=300)
        if result.returncode != 0 or not out.exists():
            raise AssemblyError(f"Failed to add silent audio to {path.name}: {result.stderr[:500]}")
        fixed.append(out)
    return fixed


async def _assemble_chunked(request: AssemblerRequest, scene_timings: list,
                            comp_dir: Path, output_path: Path) -> None:
    """Render a long composition as sequential chunks, then ffmpeg-concat them."""
    chunks = partition_timings(
        scene_timings,
        settings.COMPOSITOR_CHUNK_MAX_SCENES,
        settings.COMPOSITOR_CHUNK_MAX_SECONDS,
    )
    logger.info("Chunked render", extra={"chunks": len(chunks),
                                         "scenes": len(scene_timings)})
    chunk_dir = comp_dir / "chunks"
    chunk_dir.mkdir(parents=True, exist_ok=True)
    chunk_paths: list = []

    for k, chunk in enumerate(chunks):
        rebased = rebase_chunk(chunk)
        html_path = compose_html(
            script_title=request.script_title,
            scene_timings=rebased,
            image_paths=request.image_paths,
            job_id=request.job_id,
            scene_plans=request.scene_plans,
            job_style=request.job_style,
        )
        validate_composition(html_path)
        _promote_to_index(html_path, comp_dir)  # one Chromium at a time -> safe to reuse index.html
        out_k = chunk_dir / f"chunk_{k:03d}.mp4"
        dur_k = sum(slot_seconds(t) for t in chunk)
        logger.info("Rendering chunk", extra={"chunk": k, "scenes": len(chunk), "approx_s": round(dur_k, 1)})
        try:
            await _render_project(comp_dir, out_k, chunk_render_timeout_s(dur_k))
        except AssemblyError as e:
            raise AssemblyError(f"chunk {k + 1}/{len(chunks)} failed: {e}")
        chunk_paths.append(out_k)

    # _normalize_audio_streams runs blocking ffprobe/ffmpeg — keep it off the
    # event loop so /health and concurrent requests stay responsive.
    chunk_paths = await asyncio.to_thread(_normalize_audio_streams, chunk_paths)

    concat_list = chunk_dir / "concat.txt"
    # Absolute paths (escaped for the concat demuxer) — no cwd coupling; the
    # list stays valid even if the working directory or chunk dir moves.
    def _concat_line(p: Path) -> str:
        return "file '{}'\n".format(str(p.resolve()).replace("'", r"'\''"))
    concat_list.write_text("".join(_concat_line(p) for p in chunk_paths), encoding="utf-8")
    concat_cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_list), "-c", "copy", str(output_path),
    ]
    # -c copy concat is I/O-bound: scale the budget with film length instead of
    # a flat 600s that a 2h film can legitimately exceed.
    total_s = sum(slot_seconds(t) for chunk in chunks for t in chunk)
    concat_timeout = max(600, int(120 + 2 * total_s))
    with timed_block(logger, "ffmpeg concat"):
        result = await asyncio.to_thread(
            run_proc, concat_cmd, concat_timeout,
        )
    log_subprocess(logger, concat_cmd, result, label="ffmpeg-concat")
    if result.returncode != 0 or not output_path.exists() or output_path.stat().st_size == 0:
        raise AssemblyError(f"Concat failed (rc={result.returncode}): {result.stderr[:800]}")

    # Sanity: joined duration should match the sum of chunk durations within 2%.
    # probe_duration runs a blocking ffprobe subprocess per path — offload the
    # whole check to a thread so the event loop (/health, /lint) stays responsive.
    def _probe_concat_durations() -> tuple:
        return (sum(probe_duration(str(p)) for p in chunk_paths),
                probe_duration(str(output_path)))
    expected, actual = await asyncio.to_thread(_probe_concat_durations)
    if expected > 0 and abs(actual - expected) / expected > 0.02:
        logger.warning("Concat duration drift", extra={"expected_s": round(expected, 2),
                                                        "actual_s": round(actual, 2)})


@app.post("/assemble", response_model=AssemblerResponse)
async def assemble(request: AssemblerRequest):
    async with _ASSEMBLING_LOCK:
        if request.job_id in _ASSEMBLING:
            existing_fut = _ASSEMBLING[request.job_id]
            logger.info("Assembly already in progress — waiting on existing run",
                        extra={"job_id": request.job_id})
        else:
            existing_fut = None
            # get_running_loop (not the deprecated get_event_loop) — the future
            # must be bound to THIS loop or waiters can hang cross-loop.
            _ASSEMBLING[request.job_id] = asyncio.get_running_loop().create_future()

    if existing_fut is not None:
        # Wait for the running assembly; re-raise its exception if it failed.
        # shield: this waiter's disconnect must not cancel the shared future.
        # wait_for: a wedged owner can't hang waiters past the assembly ceiling.
        return await asyncio.wait_for(asyncio.shield(existing_fut),
                                      timeout=settings.ASSEMBLER_TIMEOUT_MAX_SECONDS)

    try:
        set_log_context(job_id=request.job_id)
        logger.info("Assembly start", extra={
            "render_paths": len(request.render_paths),
            "audio_paths": len(request.audio_paths),
            "scenes": [s.get("scene_id") if isinstance(s, dict) else s.scene_id for s in (request.scene_plans or [])],
        })

        # Step 1: Compute scene timings
        with timed_block(logger, "compute scene timings"):
            scene_timings = compute_scene_timings(
                request.render_paths, request.audio_paths, request.scene_plans,
            )
        for t in scene_timings:
            logger.info("scene timing", extra={"scene_id": t.scene_id,
                                                "video_s": t.actual_video_duration_seconds,
                                                "audio_s": t.actual_audio_duration_seconds,
                                                "start_s": t.start_time_seconds,
                                                "path": t.render_path})

        output_path = Path(settings.WORKSPACE_DIR) / "outputs" / f"{request.job_id}_final.mp4"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        comp_dir = Path(settings.WORKSPACE_DIR) / "temp" / request.job_id

        # Freeze-pad any video render whose narration outlasts it, so the Manim
        # clip holds its last frame instead of vanishing mid-narration. Slot
        # length (max of video/audio) is unchanged, so timings below still hold.
        with timed_block(logger, "freeze-pad short renders"):
            scene_timings = freeze_pad_renders(scene_timings, comp_dir / "padded")

        # Soft captions: WebVTT sidecar timed to the real per-sentence TTS segments
        # (falls back to word-count windows per scene if a scene has no segments).
        # Served by the orchestrator at /captions/{job}; toggled by the player CC
        # button. Best-effort — a VTT failure must never fail the film.
        try:
            vtt = build_vtt(scene_timings, request.audio_segments, request.scene_plans)
            vtt_path = output_path.with_name(f"{request.job_id}.vtt")
            vtt_path.write_text(vtt, encoding="utf-8")
            log_file(logger, "captions vtt", str(vtt_path))
        except Exception as e:  # noqa: BLE001 — captions are non-critical
            logger.warning("VTT generation failed; soft captions skipped", extra={"error": str(e)})

        def _plan_field(plan, key, default=None):
            return plan.get(key, default) if isinstance(plan, dict) else getattr(plan, key, default)
        hf_ids = {
            int(_plan_field(p, "scene_id"))
            for p in (request.scene_plans or [])
            if str(_plan_field(p, "content_type", "manim")).lower() == "hyperframes"
            and _plan_field(p, "scene_id") is not None
        }

        async def _render_active(active):
            """Compose + render a given set of scene timings (single-pass or chunked)."""
            total = max((t.start_time_seconds + slot_seconds(t) for t in active), default=0.0)
            if total <= settings.COMPOSITOR_CHUNK_THRESHOLD_SECONDS:
                with timed_block(logger, "compose HTML"):
                    html_path = compose_html(
                        script_title=request.script_title,
                        scene_timings=active,
                        image_paths=request.image_paths,
                        job_id=request.job_id,
                        scene_plans=request.scene_plans,
                        job_style=request.job_style,
                    )
                log_file(logger, "written", html_path)
                with timed_block(logger, "validate HTML"):
                    validate_composition(html_path)
                logger.info("HTML validation passed")
                _promote_to_index(html_path, comp_dir)
                await _render_project(comp_dir, output_path, chunk_render_timeout_s(total))
            else:
                logger.info("Long composition -> chunked render", extra={"total_s": round(total, 1)})
                await _assemble_chunked(request, active, comp_dir, output_path)

        # Fault-tolerant render. HyperFrames scenes are LLM-authored HTML/CSS and
        # are the fragile part — one scene whose CSS won't compile fails the whole
        # master render. So: try the full film; on failure, drop the HF scenes and
        # ship the manim/video scenes as a partial cut. Never hard-fail the job on
        # one bad scene. (Manim scenes are pre-rendered mp4s — robust.)
        dropped: list[int] = []
        try:
            await _render_active(scene_timings)
        except AssemblyError as e1:
            droppable = [t for t in scene_timings if int(t.scene_id) in hf_ids]
            survivors = [t for t in scene_timings if int(t.scene_id) not in hf_ids]
            if not droppable or not survivors:
                raise  # nothing fragile to drop, or nothing would be left — give up cleanly
            # Bisect: try dropping one HF scene at a time so a single bad scene
            # doesn't evict all HF scenes from the film. Every attempt re-renders
            # the remaining film, so the recovery budget is CAPPED — past it we
            # go straight to Manim-only instead of paying O(n) full renders.
            _MAX_DROP_ATTEMPTS = 3
            active = list(scene_timings)
            recovered = False
            for i, bad in enumerate(droppable):
                if i >= _MAX_DROP_ATTEMPTS:
                    logger.warning("Drop-bisect budget exhausted",
                                   extra={"attempts": i, "remaining_hf": len(droppable) - i})
                    break
                candidate = [t for t in active if int(t.scene_id) != int(bad.scene_id)]
                if not candidate:
                    break
                try:
                    await _render_active(candidate)
                    dropped.append(int(bad.scene_id))
                    logger.warning("Dropped one HF scene; render recovered",
                                   extra={"dropped_scene": bad.scene_id})
                    active = candidate
                    recovered = True
                    break  # render succeeded — stop dropping
                except AssemblyError:
                    dropped.append(int(bad.scene_id))
                    active = candidate  # this one also bad; keep removing
            if not recovered:
                # Individual drops failed or budget ran out — fall back to Manim-only
                dropped = sorted(int(t.scene_id) for t in droppable)
                logger.warning("Master render failed; retrying without HyperFrames scenes",
                               extra={"dropped": dropped, "error": str(e1)[:300]})
                await _render_active(survivors)
            # Record each dropped HF scene for fine-tuning (best-effort, never raises).
            for _sid in dropped:
                log_render_failure(job_id=request.job_id, scene_id=_sid,
                                   content_type="hyperframes", attempt=None,
                                   error_text=str(e1), model=settings.CODE_GENERATOR_MODEL,
                                   source="hf_render")

        # Post-assembly film QA: scan the raw film (pre-intro/music, so scene
        # starts still match the timing records and narration silence isn't
        # masked by the music bed) for scenes that came out black/static/silent,
        # and vision-diagnose the flagged ones. Best-effort: a QA failure never
        # fails an assembly that already produced a film.
        qa_flagged: dict = {}
        qa_film_issues: list = []
        if settings.FILM_QA_ENABLED:
            # Dropped scenes aren't in the film — repack survivor start times
            # the same way the render packed their slots.
            active_qa, acc = [], 0.0
            for t in scene_timings:
                if int(t.scene_id) in set(dropped):
                    continue
                active_qa.append(t.model_copy(update={"start_time_seconds": round(acc, 3)}))
                acc += slot_seconds(t)
            try:
                with timed_block(logger, "film QA (black/freeze/silence scan)"):
                    qa_flagged, qa_film_issues = await run_film_qa(
                        str(output_path), active_qa, request.scene_plans)
            except Exception as e:  # noqa: BLE001 — QA is best-effort
                logger.warning("film QA failed; skipping", extra={"error": str(e)[:300]})
            if qa_flagged:
                logger.warning("film QA flagged scenes", extra={
                    "scenes": sorted(qa_flagged),
                    "critiques": {k: v[:200] for k, v in qa_flagged.items()}})

        # Final-cut polish: music bed + intro/outro concat (no-op if no assets).
        # Mutates output_path in place, so final_output_path stays stable.
        intro_seconds = 0.0
        with timed_block(logger, "final-cut polish (music/intro/outro)"):
            _, intro_seconds = finalize_film(output_path, comp_dir / "polish")

        log_file(logger, "output", str(output_path))

        # Delete the compositor's OWN scratch output now that the final video is
        # confirmed on disk. comp_dir also holds render_scene_*/, scene_*.html and
        # scene_*_audio.wav — the canonical per-scene artifacts code-generator and
        # voiceover write, which /job/{id}/resume reuses to skip already-done work
        # for "partial" jobs. Deleting the whole comp_dir here used to wipe those
        # out too, so any later resume hit FileNotFoundError trying to reuse a
        # render that a prior successful assembly had already vaporized. Only the
        # composer's own scratch subpaths are disposable — everything else stays.
        for scratch in ("index.html", "compositions", "chunks", "padded", "polish"):
            p = comp_dir / scratch
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                p.unlink(missing_ok=True)
        logger.info("Cleaned compositor scratch output", extra={"comp_dir": str(comp_dir)})

        logger.info("Assembly complete", extra={"output": str(output_path),
                                                 "size_bytes": output_path.stat().st_size,
                                                 "intro_s": intro_seconds,
                                                 "dropped_scene_ids": dropped})
        result = AssemblerResponse(final_output_path=str(output_path),
                                   intro_duration_seconds=intro_seconds,
                                   dropped_scene_ids=dropped,
                                   qa_flagged=qa_flagged,
                                   qa_film_issues=qa_film_issues)
        async with _ASSEMBLING_LOCK:
            fut = _ASSEMBLING.pop(request.job_id, None)
        if fut and not fut.done():
            fut.set_result(result)
        return result

    except AssemblyError as e:
        logger.error(f"AssemblyError: {e}")
        exc = HTTPException(status_code=500, detail=str(e))
        async with _ASSEMBLING_LOCK:
            fut = _ASSEMBLING.pop(request.job_id, None)
        if fut and not fut.done():
            fut.set_exception(exc)
        raise exc
    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"Unexpected compositor error: {e}\n{tb}")
        exc = HTTPException(status_code=500, detail=f"{str(e)}\n{tb}")
        async with _ASSEMBLING_LOCK:
            fut = _ASSEMBLING.pop(request.job_id, None)
        if fut and not fut.done():
            fut.set_exception(exc)
        raise exc
    finally:
        # Leak guard for every OTHER exit path — above all CancelledError (the
        # owning request disconnected between creating the future and reaching a
        # pop site). An orphaned unresolved future would make every later
        # /assemble for this job await it forever. No-op when success/except
        # paths already popped it.
        async with _ASSEMBLING_LOCK:
            fut = _ASSEMBLING.pop(request.job_id, None)
        if fut and not fut.done():
            fut.cancel()


@app.exception_handler(AssemblyError)
async def assembly_error_handler(request, exc: AssemblyError):
    return JSONResponse(status_code=500, content={"detail": str(exc)})
