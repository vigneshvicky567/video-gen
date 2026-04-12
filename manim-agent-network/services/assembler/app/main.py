from fastapi import FastAPI, HTTPException
from shared.schemas.requests import AssemblerRequest
from shared.schemas.responses import AssemblerResponse
from shared.config import settings
import subprocess
import os
import logging

app = FastAPI(title="Assembler Service")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@app.post("/assemble", response_model=AssemblerResponse)
async def assemble_video(request: AssemblerRequest):
    logger.info(f"Assembling video for job {request.job_id}")

    output_dir = os.path.join(settings.WORKSPACE_DIR, "outputs")
    os.makedirs(output_dir, exist_ok=True)
    final_output_path = os.path.join(output_dir, f"{request.job_id}_final.mp4")

    # temp dir for intermediate merged clips
    temp_dir = os.path.join(settings.WORKSPACE_DIR, "temp", request.job_id)
    merged_clips_paths = []

    try:
        # Step 1: Merge video and audio for each scene independently
        sorted_scene_ids = sorted(list(request.render_paths.keys()))
        for scene_id in sorted_scene_ids:
            video_path = request.render_paths[scene_id]
            audio_path = request.audio_paths.get(scene_id)

            merged_clip_path = os.path.join(temp_dir, f"scene_{scene_id}_merged.mp4")

            if audio_path and os.path.exists(audio_path):
                # FFmpeg: merge video and audio, pad/trim audio to fit video, or vice versa
                # Here we use -shortest to end encoding when the shortest stream ends,
                # but usually we want to pad the video if audio is longer, or pad audio if video is longer.
                # A robust approach: scale them to match or just take the longest.
                # For simplicity, we just combine them.
                cmd = [
                    "ffmpeg", "-y",
                    "-i", video_path,
                    "-i", audio_path,
                    "-c:v", "copy",
                    "-c:a", "aac",
                    merged_clip_path
                ]
            else:
                # No audio, just copy video
                cmd = [
                    "ffmpeg", "-y",
                    "-i", video_path,
                    "-c:v", "copy",
                    merged_clip_path
                ]

            subprocess.run(cmd, check=True, capture_output=True)
            merged_clips_paths.append(merged_clip_path)

        # Step 2: Concatenate all merged clips into the final video
        concat_file_path = os.path.join(temp_dir, "concat_list.txt")
        with open(concat_file_path, "w") as f:
            for clip_path in merged_clips_paths:
                f.write(f"file '{clip_path}'\n")

        concat_cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_file_path,
            "-c", "copy",
            final_output_path
        ]

        subprocess.run(concat_cmd, check=True, capture_output=True)

        logger.info(f"Assembly completed successfully. Output at {final_output_path}")
        return AssemblerResponse(final_output_path=final_output_path)

    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.decode('utf-8') if e.stderr else str(e)
        logger.error(f"FFmpeg error: {error_msg}")
        raise HTTPException(status_code=500, detail=f"Assembly failed: {error_msg}")
    except Exception as e:
        logger.error(f"Unexpected assembly error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Assembly failed: {str(e)}")

@app.get("/health")
def health():
    return {"status": "ok"}
