import os
import json
import subprocess
from fastapi import FastAPI, HTTPException
from services.shared.models import ReviewRequest, ReviewResponse

app = FastAPI(title="Quality Review Service")

@app.post("/review", response_model=ReviewResponse)
async def review(request: ReviewRequest):
    if not os.path.exists(request.video_path):
        return ReviewResponse(is_valid=False, duration=0.0, issues=["Video file does not exist"])

    issues = []
    duration = 0.0

    # Use ffprobe to get media info
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        request.video_path
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)

        # Check streams
        streams = data.get("streams", [])
        has_video = any(s.get("codec_type") == "video" for s in streams)
        has_audio = any(s.get("codec_type") == "audio" for s in streams)

        if not has_video:
            issues.append("Missing video stream")
        if not has_audio:
            issues.append("Missing audio stream")

        # Get duration
        format_info = data.get("format", {})
        duration_str = format_info.get("duration", "0")
        duration = float(duration_str)

        if duration <= 0:
            issues.append("Video has zero duration")

    except subprocess.CalledProcessError as e:
        issues.append(f"ffprobe execution failed: {str(e)}")
    except Exception as e:
        issues.append(f"Analysis error: {str(e)}")

    is_valid = len(issues) == 0

    return ReviewResponse(
        is_valid=is_valid,
        duration=duration,
        issues=issues
    )

@app.get("/health")
async def health():
    return {"status": "ok"}
