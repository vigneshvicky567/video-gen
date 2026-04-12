import os
import subprocess
from fastapi import FastAPI, HTTPException
from services.shared.models import ValidationRequest, ValidationResponse

app = FastAPI(title="Validator Service")

WORKSPACE_DIR = "/workspace"

@app.post("/validate_code", response_model=ValidationResponse)
async def validate_code(request: ValidationRequest):
    # Setup paths
    scene_dir = os.path.join(WORKSPACE_DIR, request.scene_id)
    os.makedirs(scene_dir, exist_ok=True)

    script_path = os.path.join(scene_dir, "scene.py")
    output_dir = os.path.join(scene_dir, "media")

    # Write the generated code to file
    with open(script_path, "w") as f:
        f.write(request.manim_code)

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
        # Run subprocess
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300 # 5 min timeout
        )

        # Expected output path relative to media_dir
        # Structure is media/videos/scene/720p30/output.mp4
        expected_video_path = os.path.join(output_dir, "videos", "scene", "720p30", "output.mp4")

        if result.returncode == 0 and os.path.exists(expected_video_path):
            return ValidationResponse(
                success=True,
                video_path=expected_video_path,
                error_log=None
            )
        else:
            # Render failed or file missing
            error_log = f"Return Code: {result.returncode}\n"
            error_log += f"STDOUT:\n{result.stdout[-1000:]}\n" # Take last 1000 chars to avoid massive logs
            error_log += f"STDERR:\n{result.stderr[-1000:]}"

            return ValidationResponse(
                success=False,
                video_path=None,
                error_log=error_log
            )

    except subprocess.TimeoutExpired:
        return ValidationResponse(
            success=False,
            video_path=None,
            error_log="Manim rendering timed out after 300 seconds."
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
