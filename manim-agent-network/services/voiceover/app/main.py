from fastapi import FastAPI
from shared.schemas.requests import VoiceoverRequest
from shared.schemas.responses import VoiceoverResponse
from shared.config import settings
from google import genai
from google.genai import types
import os
import wave
import logging
import subprocess

app = FastAPI(title="Voiceover Service")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Gemini Client
client = genai.Client(
    api_key=settings.GEMINI_API_KEY,
    http_options=types.HttpOptions(timeout=settings.GEMINI_REQUEST_TIMEOUT_MS),
)

def wave_file(filename, pcm, channels=1, rate=24000, sample_width=2) -> None:
    with wave.open(filename, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(rate)
        wf.writeframes(pcm)

def generate_gemini_tts(text: str, output_path: str, model: str = None) -> bool:
    """Generate TTS using Gemini. Returns True if successful."""
    if model is None:
        model = settings.VOICEOVER_MODEL
    
    try:
        logger.info(f"Generating TTS with model: {model}")
        response = client.models.generate_content(
            model=model,
            contents=text,
            config=types.GenerateContentConfig(
                speech_config=types.SpeechConfig(
                    language_code="en-US",
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name="Aoede",
                        )
                    ),
                ),
            ),
        )

        data = response.candidates[0].content.parts[0].inline_data.data
        wave_file(output_path, data)
        logger.info(f"Successfully generated Gemini TTS audio with {model}")
        return True

    except Exception as e:
        logger.warning(f"Gemini TTS failed with {model}: {str(e)}")
        return False

def generate_espeak_fallback(text: str, output_path: str):
    """Fallback to espeak (last resort)."""
    logger.warning("Using espeak fallback for TTS")
    try:
        subprocess.run(
            ["espeak", "-w", output_path, text],
            check=True,
            capture_output=True
        )
    except Exception as e:
        logger.error(f"Espeak fallback failed: {e}")
        raise e

@app.post("/generate", response_model=VoiceoverResponse)
async def generate_voiceover(request: VoiceoverRequest):
    logger.info(f"Generating voiceover for job {request.job_id}, scene {request.scene_id}")

    temp_dir = os.path.join(settings.WORKSPACE_DIR, "temp", request.job_id)
    os.makedirs(temp_dir, exist_ok=True)
    audio_path = os.path.join(temp_dir, f"scene_{request.scene_id}_audio.wav")

    # Try primary model first (gemini-2.5-flash for free tier)
    primary_model = getattr(settings, 'VOICEOVER_MODEL', 'gemini-2.0-flash')
    success = generate_gemini_tts(request.narration_text, audio_path, primary_model)
    
    if not success:
        # Fallback to espeak if Gemini fails
        logger.warning("Gemini TTS failed, falling back to espeak")
        generate_espeak_fallback(request.narration_text, audio_path)

    return VoiceoverResponse(
        scene_id=request.scene_id,
        audio_path=audio_path
    )

@app.get("/health")
def health():
    return {"status": "ok"}
