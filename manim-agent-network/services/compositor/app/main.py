import subprocess
import logging
import traceback
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from shared.config import settings
from shared.schemas.requests import AssemblerRequest
from shared.schemas.responses import AssemblerResponse
from shared.log import get_logger, set_log_context, timed_block, log_subprocess, log_file, make_request_logging_middleware

from .duration_prober import compute_scene_timings, AssemblyError
from .llm_composer import compose_html
from .html_validator import validate_composition

app = FastAPI(title="Compositor Service")
app.add_middleware(make_request_logging_middleware("compositor"))
logger = get_logger(__name__)


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "compositor"}


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
            "node", "/usr/local/lib/node_modules/hyperframes/dist/cli.js", "render",
            "--output", str(output_path),
            "--fps", "30",
            "--quality", "standard",
            "--workers", "1",
        ]

        with timed_block(logger, "HyperFrames render"):
            result = subprocess.run(
                render_command, capture_output=True, text=True,
                cwd=str(composition_dir), timeout=600,
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
