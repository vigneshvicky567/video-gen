from fastapi import FastAPI, HTTPException
from shared.schemas.requests import AssemblerRequest
from shared.schemas.responses import AssemblerResponse
from shared.config import settings
from shared.log import get_logger, set_log_context, timed_block, log_subprocess, log_file, make_request_logging_middleware
import subprocess
import os

app = FastAPI(title="Assembler Service")
app.add_middleware(make_request_logging_middleware("assembler"))
logger = get_logger(__name__)

@app.post("/assemble", response_model=AssemblerResponse)
async def assemble_video(request: AssemblerRequest):
    set_log_context(job_id=request.job_id)
    logger.info("Assembly started", extra={"scene_count": len(request.render_paths)})

    output_dir = os.path.join(settings.WORKSPACE_DIR, "outputs")
    os.makedirs(output_dir, exist_ok=True)
    final_output_path = os.path.join(output_dir, f"{request.job_id}_final.mp4")
    temp_dir = os.path.join(settings.WORKSPACE_DIR, "temp", request.job_id)
    os.makedirs(temp_dir, exist_ok=True)
    merged_clips_paths = []

    try:
        sorted_scene_ids = sorted(list(request.render_paths.keys()))
        for scene_id in sorted_scene_ids:
            set_log_context(scene_id=scene_id)
            video_path = request.render_paths[scene_id]
            audio_path = request.audio_paths.get(scene_id)

            merged_clip_path = os.path.join(temp_dir, f"scene_{scene_id}_merged.mp4")

            if audio_path and os.path.exists(audio_path):
                cmd = ["ffmpeg", "-y", "-i", video_path, "-i", audio_path,
                       "-c:v", "copy", "-c:a", "aac", merged_clip_path]
            else:
                logger.warning("No audio for scene, copying video only")
                cmd = ["ffmpeg", "-y", "-i", video_path, "-c:v", "copy", merged_clip_path]

            with timed_block(logger, f"ffmpeg merge scene {scene_id}", scene_id=scene_id):
                result = subprocess.run(cmd, capture_output=True, text=True)
                log_subprocess(logger, cmd, result, label="ffmpeg-merge", scene_id=scene_id)
                if result.returncode != 0:
                    raise subprocess.CalledProcessError(result.returncode, cmd, result.stdout, result.stderr)

            log_file(logger, "written", merged_clip_path, scene_id=scene_id)
            merged_clips_paths.append(merged_clip_path)

        concat_file_path = os.path.join(temp_dir, "concat_list.txt")
        with open(concat_file_path, "w") as f:
            for clip_path in merged_clips_paths:
                f.write(f"file '{clip_path}'\n")

        concat_cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                      "-i", concat_file_path, "-c", "copy", final_output_path]

        with timed_block(logger, "ffmpeg concat", job_id=request.job_id):
            result = subprocess.run(concat_cmd, capture_output=True, text=True)
            log_subprocess(logger, concat_cmd, result, label="ffmpeg-concat")
            if result.returncode != 0:
                raise subprocess.CalledProcessError(result.returncode, concat_cmd, result.stdout, result.stderr)

        log_file(logger, "written", final_output_path)
        logger.info("Assembly complete", extra={"output": final_output_path})
        return AssemblerResponse(final_output_path=final_output_path)

    except subprocess.CalledProcessError as e:
        error_msg = e.stderr if isinstance(e.stderr, str) else (e.stderr or b"").decode()
        logger.error("FFmpeg failed", extra={"error": error_msg[:500]}, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Assembly failed: {error_msg}")
    except Exception as e:
        logger.error("Unexpected assembly error", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Assembly failed: {str(e)}")

@app.get("/health")
def health():
    return {"status": "ok"}
