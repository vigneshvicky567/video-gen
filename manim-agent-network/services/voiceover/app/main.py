from fastapi import FastAPI
from shared.schemas.requests import VoiceoverRequest
from shared.schemas.responses import VoiceoverResponse
from shared.config import settings
from shared.llm_client import get_openai_tts_client
import os
import logging
import subprocess
import uuid
import time

# LangSmith Tracing
app = FastAPI(title="Voiceover Service")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# LangSmith tracer setup
_tracer = None
if os.getenv("LANGSMITH_API_KEY"):
    try:
        import langsmith
        langsmith_client = langsmith.Client()
        _tracer = langsmith_client
        logger.info("LangSmith tracing enabled")
    except ImportError:
        logger.warning("langsmith not installed, tracing disabled")

# OpenAI client for TTS only (NVIDIA NIM has no TTS endpoint)
client = get_openai_tts_client()


def generate_openai_tts(text: str, output_path: str, model: str = None) -> bool:
    """Generate TTS using OpenAI. Returns True if successful."""
    if model is None:
        model = settings.VOICEOVER_MODEL

    try:
        logger.info(f"Generating TTS with model: {model}")
        response = client.audio.speech.create(
            model=model,
            voice="alloy",
            input=text
        )
        with open(output_path, "wb") as f:
            f.write(response.content)
        logger.info(f"Successfully generated OpenAI TTS audio with {model}")
        return True
    except Exception as e:
        logger.warning(f"OpenAI TTS failed with {model}: {str(e)}")
        return False


def generate_dia2_tts(text: str, output_path: str) -> bool:
    """Generate TTS using Dia2 (nari-labs/Dia2-1B or Dia2-2B).

    Dia2 is a streaming dialogue TTS model that runs locally.
    Weights are auto-downloaded on first use from Hugging Face.

    Requires: pip install dia2  (installed in the voiceover Docker image)
    VRAM: ~4GB for 1B, ~6GB for 2B — fits comfortably in 8GB VRAM.

    Speaker tags [S1] / [S2] are supported for multi-speaker output.
    Single-speaker narration is wrapped in [S1] automatically.

    Returns True on success, False on any failure.
    """
    try:
        from dia2 import Dia2, GenerationConfig, SamplingConfig
    except ImportError:
        logger.warning("dia2 not installed — skipping Dia2 TTS")
        return False

    try:
        model_repo = settings.DIA2_MODEL  # e.g. "nari-labs/Dia2-1B"
        device = settings.DIA2_DEVICE     # "cuda" or "cpu"
        dtype = settings.DIA2_DTYPE       # "bfloat16" or "float32"

        logger.info(f"Dia2: loading model {model_repo} on {device} ({dtype})")

        dia = Dia2.from_repo(model_repo, device=device, dtype=dtype)

        config = GenerationConfig(
            cfg_scale=float(settings.DIA2_CFG_SCALE),
            audio=SamplingConfig(
                temperature=float(settings.DIA2_TEMPERATURE),
                top_k=50,
            ),
            use_cuda_graph=(device == "cuda"),
        )

        # Wrap plain narration text in [S1] speaker tag if not already tagged
        tagged_text = text if text.strip().startswith("[S") else f"[S1] {text}"

        logger.info(f"Dia2: generating audio for {len(tagged_text)} chars")
        dia.generate(tagged_text, config=config, output_wav=output_path, verbose=False)

        logger.info(f"Dia2: audio written to {output_path}")
        return True

    except Exception as e:
        logger.warning(f"Dia2 TTS failed: {e}")
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

    run_id = str(uuid.uuid4())
    start_time = time.time()
    provider = settings.VOICEOVER_PROVIDER.lower()

    if _tracer:
        try:
            _tracer.create_run(
                name="voiceover.generate",
                run_type="llm",
                run_id=run_id,
                metadata={
                    "service": "voiceover",
                    "job_id": request.job_id,
                    "scene_id": request.scene_id,
                    "provider": provider,
                    "model": settings.VOICEOVER_MODEL,
                }
            )
        except Exception as e:
            logger.debug(f"LangSmith trace start failed: {e}")

    temp_dir = os.path.join(settings.WORKSPACE_DIR, "temp", request.job_id)
    os.makedirs(temp_dir, exist_ok=True)

    tts_start = time.time()
    success = False

    if provider == "dia2":
        # Dia2 local inference — output is wav
        audio_path = os.path.join(temp_dir, f"scene_{request.scene_id}_audio.wav")
        success = generate_dia2_tts(request.narration_text, audio_path)
        if not success:
            logger.warning("Dia2 TTS failed, falling back to OpenAI TTS")
            audio_path = os.path.join(temp_dir, f"scene_{request.scene_id}_audio.mp3")
            success = generate_openai_tts(request.narration_text, audio_path, settings.VOICEOVER_MODEL)
    else:
        # Default: OpenAI TTS
        audio_path = os.path.join(temp_dir, f"scene_{request.scene_id}_audio.mp3")
        success = generate_openai_tts(request.narration_text, audio_path, settings.VOICEOVER_MODEL)

    tts_duration = time.time() - tts_start

    if _tracer:
        try:
            _tracer.update_run(
                run_id=run_id,
                inputs={"text_length": len(request.narration_text)},
                outputs={"success": success, "provider": provider},
                metrics={"latency": tts_duration}
            )
        except Exception:
            pass

    if not success:
        logger.warning("All TTS providers failed, falling back to espeak")
        audio_path = os.path.join(temp_dir, f"scene_{request.scene_id}_audio.wav")
        generate_espeak_fallback(request.narration_text, audio_path)

    total_duration = time.time() - start_time

    if _tracer:
        try:
            _tracer.update_run(
                run_id=run_id,
                outputs={"audio_path": audio_path},
                end_time=time.time(),
                metrics={"total_latency": total_duration}
            )
        except Exception:
            pass

    return VoiceoverResponse(
        scene_id=request.scene_id,
        audio_path=audio_path
    )


@app.get("/health")
def health():
    return {"status": "ok"}
