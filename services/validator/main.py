import os
import asyncio
from fastapi import FastAPI, HTTPException
from services.shared.models import ValidationRequest, ValidationResponse

app = FastAPI(title="Validator Service")

WORKSPACE_DIR = "/workspace"

@app.post("/validate_code", response_model=ValidationResponse)
async def validate_code(request: ValidationRequest):
    # Setup paths
    scene_dir = os.path.join(WORKSPACE_DIR, request.scene_id)
    os.makedirs(scene_dir, exist_ok=True)

    script_path = request.script_path

    if not os.path.exists(script_path):
        return ValidationResponse(
            success=False,
            video_path=None,
            error_log=f"Script file not found: {script_path}"
        )

    output_dir = os.path.join(scene_dir, "media")

    # Build manim command
    # -qm: medium quality, --media_dir: output directory, -o: output filename
    cmd = [
        "manim", "render",
        "-qm",
        "--media_dir", output_dir,
        "-o", "output.mp4",
        script_path,
        "GeneratedScene" # We strictly told the Generator to use this name
    ]

    try:
        # Run subprocess asynchronously
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=300)
            returncode = process.returncode
            stdout = stdout.decode()
            stderr = stderr.decode()
        except asyncio.TimeoutError:
            process.kill()
            await process.communicate()
            return ValidationResponse(
                success=False,
                video_path=None,
                error_log="Manim rendering timed out after 300 seconds."
            )
        except asyncio.CancelledError:
            process.terminate()
            raise

        # Expected output path relative to media_dir
        # Structure is media/videos/scene/720p30/output.mp4
        expected_video_path = os.path.join(output_dir, "videos", "scene", "720p30", "output.mp4")

        if returncode == 0 and os.path.exists(expected_video_path):
            return ValidationResponse(
                success=True,
                video_path=expected_video_path,
                error_log=None
            )
        else:
            # Render failed or file missing
            error_log = f"Return Code: {returncode}\n"
            error_log += f"STDOUT:\n{stdout[-1000:]}\n" # Take last 1000 chars to avoid massive logs
            error_log += f"STDERR:\n{stderr[-1000:]}"

            return ValidationResponse(
                success=False,
                video_path=None,
                error_log=error_log
            )

    except Exception as e:
        return ValidationResponse(
            success=False,
            video_path=None,
            error_log=f"System error during execution: {str(e)}"
        )

@app.get("/health")
async def health():
    return {"status": "ok"}
