"""Compositor service main FastAPI application."""

import subprocess
import logging
import traceback
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from shared.config import settings
from shared.schemas.requests import AssemblerRequest
from shared.schemas.responses import AssemblerResponse

from .duration_prober import compute_scene_timings, AssemblyError
from .llm_composer import compose_html
from .html_validator import validate_composition

app = FastAPI(title="Compositor Service")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "compositor"}


@app.post("/assemble", response_model=AssemblerResponse)
async def assemble(request: AssemblerRequest):
    try:
        logger.info(f"=== ASSEMBLY START job={request.job_id} ===")
        logger.info(f"render_paths: {request.render_paths}")
        logger.info(f"audio_paths:  {request.audio_paths}")
        logger.info(f"scene_plans:  {[s.get('scene_id') if isinstance(s, dict) else s.scene_id for s in (request.scene_plans or [])]}")

        # Step 1: Compute scene timings
        logger.info("Step 1: Computing scene timings...")
        scene_timings = compute_scene_timings(
            request.render_paths,
            request.audio_paths,
            request.scene_plans,
        )
        for t in scene_timings:
            logger.info(f"  Scene {t.scene_id}: video={t.actual_video_duration_seconds}s audio={t.actual_audio_duration_seconds}s start={t.start_time_seconds}s path={t.render_path}")

        # Step 2: Generate HyperFrames HTML composition
        logger.info("Step 2: Generating HyperFrames HTML composition...")
        html_path = compose_html(
            script_title=request.script_title,
            scene_timings=scene_timings,
            image_paths=request.image_paths,
            job_id=request.job_id,
            scene_plans=request.scene_plans,
        )
        logger.info(f"HTML composition saved: {html_path}")

        # Step 3: Validate HTML
        logger.info("Step 3: Validating HTML composition...")
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

        logger.info(f"Step 4: Running: {' '.join(render_command)}")
        logger.info(f"  cwd: {composition_dir}")

        result = subprocess.run(
            render_command,
            capture_output=True,
            text=True,
            cwd=str(composition_dir),
            timeout=600,
        )

        logger.info(f"HyperFrames returncode: {result.returncode}")
        if result.stdout:
            logger.info(f"STDOUT:\n{result.stdout[:3000]}")
        if result.stderr:
            logger.info(f"STDERR:\n{result.stderr[:3000]}")

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

        logger.info(f"=== ASSEMBLY COMPLETE: {output_path} ({output_path.stat().st_size} bytes) ===")
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
