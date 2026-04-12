import os
import json
import asyncio
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
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=60)

            if process.returncode != 0:
                issues.append(f"ffprobe execution failed with return code {process.returncode}: {stderr.decode()}")
            else:
                data = json.loads(stdout.decode())

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

        except asyncio.TimeoutError:
            process.kill()
            await process.communicate()
            issues.append("ffprobe execution timed out after 60 seconds")
        except asyncio.CancelledError:
            process.terminate()
            raise
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
