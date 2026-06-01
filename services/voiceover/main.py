import os
import subprocess
from fastapi import FastAPI, HTTPException
from services.shared.models import VoiceoverRequest, VoiceoverResponse

app = FastAPI(title="Voiceover Service")

WORKSPACE_DIR = "/workspace"

def generate_with_pyttsx3(text: str, output_path: str) -> bool:
    try:
        import pyttsx3
        engine = pyttsx3.init()
        # Set properties for better voice if needed
        engine.setProperty('rate', 150)
        engine.save_to_file(text, output_path)
        engine.runAndWait()
        return os.path.exists(output_path)
    except Exception as e:
        print(f"pyttsx3 failed: {e}")
        return False

def generate_with_espeak_cli(text: str, output_path: str) -> bool:
    try:
        # Fallback to espeak direct CLI if pyttsx3 has issues in docker
        subprocess.run(
            ["espeak", "-w", output_path, text],
            check=True
        )
        return os.path.exists(output_path)
    except Exception as e:
        print(f"espeak CLI failed: {e}")
        return False

@app.post("/generate_audio", response_model=VoiceoverResponse)
async def generate_audio(request: VoiceoverRequest):
    scene_dir = os.path.join(WORKSPACE_DIR, request.scene_id)
    os.makedirs(scene_dir, exist_ok=True)

    audio_path = os.path.join(scene_dir, "voiceover.wav")

    # Try using espeak CLI directly first as it's more reliable in basic Docker setups
    success = generate_with_espeak_cli(request.narration, audio_path)

    if not success:
        # Try pyttsx3
        success = generate_with_pyttsx3(request.narration, audio_path)

    if success:
        return VoiceoverResponse(audio_path=audio_path)
    else:
        raise HTTPException(status_code=500, detail="Failed to generate voiceover audio")

@app.get("/health")
async def health():
    return {"status": "ok"}
