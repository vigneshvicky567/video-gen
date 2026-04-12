import os
import subprocess
from fastapi import FastAPI, HTTPException
from services.shared.models import AssembleRequest, AssembleResponse

app = FastAPI(title="Assembler Service")

WORKSPACE_DIR = "/workspace"

@app.post("/assemble", response_model=AssembleResponse)
async def assemble(request: AssembleRequest):
    if not request.scenes:
        raise HTTPException(status_code=400, detail="No scenes provided for assembly")

    scene_clips = []

    # 1. Merge audio and video for each scene individually
    for idx, scene in enumerate(request.scenes):
        v_path = scene.get('video_path')
        a_path = scene.get('audio_path')

        if not v_path or not os.path.exists(v_path):
            raise HTTPException(status_code=404, detail=f"Video path not found: {v_path}")
        if not a_path or not os.path.exists(a_path):
            raise HTTPException(status_code=404, detail=f"Audio path not found: {a_path}")

        merged_path = os.path.join(WORKSPACE_DIR, f"scene_{idx}_merged.mp4")

        # ffmpeg: -i video -i audio -c:v copy -c:a aac -shortest
        # This copies the video stream, encodes audio to AAC, and cuts the output at the length of the shortest stream (usually audio if we want it synced)
        # Actually for Manim, video might be shorter. Let's pad or just let them overlap normally.
        cmd = [
            "ffmpeg", "-y",
            "-i", v_path,
            "-i", a_path,
            "-c:v", "copy",
            "-c:a", "aac",
            merged_path
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=f"Failed to merge scene {idx}: {result.stderr}")

        scene_clips.append(merged_path)

    # 2. Concatenate all merged scenes
    final_output = os.path.join(WORKSPACE_DIR, "final_output.mp4")

    # Create concat file
    concat_file_path = os.path.join(WORKSPACE_DIR, "concat_list.txt")
    with open(concat_file_path, "w") as f:
        for clip in scene_clips:
            # ffmpeg concat requires format: file '/path/to/file'
            f.write(f"file '{clip}'\n")

    concat_cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", concat_file_path,
        "-c", "copy",
        final_output
    ]

    concat_result = subprocess.run(concat_cmd, capture_output=True, text=True)
    if concat_result.returncode != 0:
        raise HTTPException(status_code=500, detail=f"Failed to concatenate scenes: {concat_result.stderr}")

    return AssembleResponse(final_video_path=final_output)

@app.get("/health")
async def health():
    return {"status": "ok"}
