import asyncio
import json
import os
import shutil
import subprocess
import logging
import tempfile
import traceback
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from shared.config import settings
from shared.schemas.requests import AssemblerRequest
from shared.schemas.responses import AssemblerResponse
from shared.timeouts import chunk_render_timeout_s
from shared.log import get_logger, set_log_context, timed_block, log_subprocess, log_file, make_request_logging_middleware

from .duration_prober import compute_scene_timings, probe_duration, AssemblyError
from .llm_composer import compose_html
from .html_validator import validate_composition
from .chunking import partition_timings, rebase_chunk, slot_seconds

# Overridable for host-side testing; the Docker image installs hyperframes here.
HYPERFRAMES_CLI = os.getenv(
    "HYPERFRAMES_CLI", "/usr/local/lib/node_modules/hyperframes/dist/cli.js"
)

app = FastAPI(title="Compositor Service")
app.add_middleware(make_request_logging_middleware("compositor"))
logger = get_logger(__name__)


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "compositor"}


class LintRequest(BaseModel):
    html_path: str


@app.post("/lint")
async def lint_scene(request: LintRequest):
    """Run `hyperframes lint` against a single scene HTML file.

    Called by the validator for HyperFrames scenes so real lint findings
    (orphan timelines, opacity no-ops, repeat:-1, Math.random, ...) reach the
    code-generator's retry prompt instead of surfacing as a blank scene at
    render time. Permissive on tooling failure: if lint itself cannot run,
    returns ok=True so the pipeline degrades to the regex-level checks.
    """
    src = Path(request.html_path)
    if not src.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {src}")

    def _run_lint() -> str:
        with tempfile.TemporaryDirectory() as td:
            shutil.copyfile(src, Path(td) / "index.html")
            # Non-zero exit means findings exist, not a tool failure.
            result = subprocess.run(
                ["node", HYPERFRAMES_CLI, "lint", td, "--json"],
                capture_output=True, text=True, timeout=120,
            )
        return result.stdout or ""

    try:
        # Worker thread: validator lints scenes in parallel and a blocking
        # subprocess here would stall the event loop (and /health).
        import asyncio
        stdout = await asyncio.to_thread(_run_lint)
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

    return {"ok": not errors, "errors": errors, "warnings": warnings, "lint_ran": True}


def _render_command(output_path: Path) -> list:
    # EXACT verified hyperframes flags only — there are no time-window flags.
    return [
        "node", HYPERFRAMES_CLI, "render",
        "--output", str(output_path),
        "--fps", "30",
        "--quality", "standard",
        "--workers", "1",
    ]


async def _render_project(comp_dir: Path, output_path: Path, timeout_s: int) -> None:
    """Render the composition rooted at comp_dir/index.html to output_path.

    Runs the blocking subprocess in a worker thread so the event loop (and
    /health, /lint) stay responsive during a multi-minute render.
    """
    cmd = _render_command(output_path)
    with timed_block(logger, "HyperFrames render"):
        result = await asyncio.to_thread(
            subprocess.run, cmd,
            capture_output=True, text=True, cwd=str(comp_dir), timeout=timeout_s,
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
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=60,
        )
        return bool(result.stdout.strip())
    except Exception:
        return True  # assume audio; concat -c copy will surface a real mismatch


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
            "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-shortest", "-c:v", "copy", "-c:a", "aac", str(out),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
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

    chunk_paths = _normalize_audio_streams(chunk_paths)

    concat_list = chunk_dir / "concat.txt"
    concat_list.write_text("".join(f"file '{p.name}'\n" for p in chunk_paths), encoding="utf-8")
    concat_cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_list), "-c", "copy", str(output_path),
    ]
    with timed_block(logger, "ffmpeg concat"):
        result = await asyncio.to_thread(
            subprocess.run, concat_cmd,
            capture_output=True, text=True, cwd=str(chunk_dir), timeout=600,
        )
    log_subprocess(logger, concat_cmd, result, label="ffmpeg-concat")
    if result.returncode != 0 or not output_path.exists() or output_path.stat().st_size == 0:
        raise AssemblyError(f"Concat failed (rc={result.returncode}): {result.stderr[:800]}")

    # Sanity: joined duration should match the sum of chunk durations within 2%.
    expected = sum(probe_duration(str(p)) for p in chunk_paths)
    actual = probe_duration(str(output_path))
    if expected > 0 and abs(actual - expected) / expected > 0.02:
        logger.warning("Concat duration drift", extra={"expected_s": round(expected, 2),
                                                        "actual_s": round(actual, 2)})


@app.post("/assemble", response_model=AssemblerResponse)
async def assemble(request: AssemblerRequest):
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

        total_s = max(
            (t.start_time_seconds + slot_seconds(t) for t in scene_timings),
            default=0.0,
        )

        if total_s <= settings.COMPOSITOR_CHUNK_THRESHOLD_SECONDS:
            # Single-pass path (short videos): compose -> validate -> render.
            with timed_block(logger, "compose HTML"):
                html_path = compose_html(
                    script_title=request.script_title,
                    scene_timings=scene_timings,
                    image_paths=request.image_paths,
                    job_id=request.job_id,
                    scene_plans=request.scene_plans,
                )
            log_file(logger, "written", html_path)

            with timed_block(logger, "validate HTML"):
                validate_composition(html_path)
            logger.info("HTML validation passed")

            _promote_to_index(html_path, comp_dir)
            await _render_project(comp_dir, output_path, chunk_render_timeout_s(total_s))
        else:
            # Long-form: render in chunks and concat (the CLI has no windowing).
            logger.info("Long composition -> chunked render", extra={"total_s": round(total_s, 1)})
            await _assemble_chunked(request, scene_timings, comp_dir, output_path)

        log_file(logger, "output", str(output_path))
        logger.info("Assembly complete", extra={"output": str(output_path),
                                                 "size_bytes": output_path.stat().st_size})
        return AssemblerResponse(final_output_path=str(output_path))

    except AssemblyError as e:
        logger.error(f"AssemblyError: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"Unexpected compositor error: {e}\n{tb}")
        raise HTTPException(status_code=500, detail=f"{str(e)}\n{tb}")


@app.exception_handler(AssemblyError)
async def assembly_error_handler(request, exc: AssemblyError):
    return JSONResponse(status_code=500, content={"detail": str(exc)})
