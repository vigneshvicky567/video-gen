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
from shared.log import get_logger, set_log_context, timed_block, log_subprocess, log_file, make_request_logging_middleware

from .duration_prober import compute_scene_timings, AssemblyError
from .llm_composer import compose_html
from .html_validator import validate_composition

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

        # Step 2: Generate HyperFrames HTML composition
        with timed_block(logger, "compose HTML"):
            html_path = compose_html(
                script_title=request.script_title,
                scene_timings=scene_timings,
                image_paths=request.image_paths,
                job_id=request.job_id,
                scene_plans=request.scene_plans,
            )
        log_file(logger, "written", html_path)

        # Step 3: Validate HTML
        with timed_block(logger, "validate HTML"):
            validate_composition(html_path)
        logger.info("HTML validation passed")

        # Step 4: Render with HyperFrames
        output_path = Path(settings.WORKSPACE_DIR) / "outputs" / f"{request.job_id}_final.mp4"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        composition_dir = Path(html_path).parent
        index_path = composition_dir / "index.html"

        if Path(html_path).name != "index.html" and Path(html_path).exists():
            Path(html_path).rename(index_path)
        elif not index_path.exists() and Path(html_path).exists():
            Path(html_path).rename(index_path)

        render_command = [
            "node", HYPERFRAMES_CLI, "render",
            "--output", str(output_path),
            "--fps", "30",
            "--quality", "standard",
            "--workers", "1",
        ]

        # 600s proved too tight: a successful 8-scene run takes ~500s of
        # software rendering on this host; a cold cache pushed it over.
        with timed_block(logger, "HyperFrames render"):
            result = subprocess.run(
                render_command, capture_output=True, text=True,
                cwd=str(composition_dir), timeout=1800,
            )
        log_subprocess(logger, render_command, result, label="hyperframes")

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
