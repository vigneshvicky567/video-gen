from fastapi import FastAPI
from shared.schemas.requests import ValidatorRequest
from shared.schemas.responses import ValidatorResponse
from shared.config import settings
import asyncio
import os
import logging
import glob

app = FastAPI(title="Validator Service")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@app.post("/validate", response_model=ValidatorResponse)
async def validate_code(request: ValidatorRequest):
    logger.info(f"Validating Manim code for job {request.job_id}, scene {request.scene_id}")

    output_dir = os.path.join(settings.WORKSPACE_DIR, "temp", request.job_id, f"render_scene_{request.scene_id}")
    os.makedirs(output_dir, exist_ok=True)

    scene_class_name = f"Scene{request.scene_id}"

    # Run manim as a subprocess
    cmd = [
        "manim",
        "render",
        "-ql", # Low quality for fast rendering in dev, can change to -qh for high
        "--media_dir", output_dir,
        request.code_path,
        scene_class_name
    ]

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout=120)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            logger.error("Render timed out.")
            return ValidatorResponse(
                scene_id=request.scene_id,
                success=False,
                error_log="Manim render process timed out after 120 seconds."
            )

        stdout = stdout_bytes.decode()
        stderr = stderr_bytes.decode()

        if process.returncode == 0:
            logger.info(f"Render successful for scene {request.scene_id}")
            # Find the rendered mp4 file. Manim outputs to: media_dir/videos/filename/1080p60/SceneName.mp4
            # We use glob because the exact resolution folder depends on the -q flag
            search_path = os.path.join(output_dir, "videos", "*", "*", f"{scene_class_name}.mp4")
            mp4_files = glob.glob(search_path)

            if mp4_files:
                return ValidatorResponse(
                    scene_id=request.scene_id,
                    success=True,
                    render_path=mp4_files[0]
                )
            else:
                return ValidatorResponse(
                    scene_id=request.scene_id,
                    success=False,
                    error_log="Manim render command succeeded but .mp4 file was not found in expected directory structure."
                )
        else:
            logger.warning(f"Render failed for scene {request.scene_id}")
            error_log = stderr if stderr else stdout
            return ValidatorResponse(
                scene_id=request.scene_id,
                success=False,
                error_log=error_log[-2000:] # Return last 2000 chars to avoid prompt bloat
            )

    except asyncio.CancelledError:
        logger.error("Request cancelled, terminating subprocess.")
        if process:
            process.kill()
            await process.wait()
        raise

    except Exception as e:
        logger.error(f"Unexpected error during render: {str(e)}")
        return ValidatorResponse(
            scene_id=request.scene_id,
            success=False,
            error_log=str(e)
        )

@app.get("/health")
def health():
    return {"status": "ok"}
