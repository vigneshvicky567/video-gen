from __future__ import annotations

import logging
import os
import subprocess
import time
import uuid
from pathlib import Path
from typing import Optional, Tuple

from fastapi import FastAPI, HTTPException

from shared.config import settings
from shared.schemas.requests import VoiceoverRequest
from shared.schemas.responses import VoiceoverResponse

app = FastAPI(title="Voiceover Service")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_tracer = None
if os.getenv("LANGSMITH_API_KEY"):
    try:
        import langsmith

        _tracer = langsmith.Client()
        logger.info("LangSmith tracing enabled")
    except ImportError:
        logger.warning("langsmith not installed, tracing disabled")

_kokoro = None


def _validate_audio(path: str) -> Tuple[bool, str]:
    audio_path = Path(path)
    if not audio_path.exists():
        return False, f"audio file missing: {path}"
    if audio_path.stat().st_size == 0:
        return False, f"audio file empty: {path}"

    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,duration",
            "-of",
            "default=noprint_wrappers=1",
            path,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False, f"ffprobe failed for {path}: {result.stderr.strip()}"
    if "codec_type=audio" not in result.stdout:
        return False, f"ffprobe found no audio stream in {path}"
    return True, ""


def _cuda_available() -> bool:
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception as exc:
        logger.warning(f"Could not check CUDA availability: {exc}")
        return False


def generate_dia2_tts(text: str, output_path: str) -> Tuple[bool, str]:
    device = settings.DIA2_DEVICE.lower()
    if device == "cuda" and not _cuda_available():
        return False, "Dia2 configured for CUDA, but no CUDA device is available"

    try:
        from dia2 import Dia2, GenerationConfig, SamplingConfig
    except Exception as exc:
        return False, f"Dia2 import failed: {exc}"

    try:
        logger.info(f"Dia2: loading {settings.DIA2_MODEL} on {device} ({settings.DIA2_DTYPE})")
        dia = Dia2.from_repo(settings.DIA2_MODEL, device=device, dtype=settings.DIA2_DTYPE)
        config = GenerationConfig(
            cfg_scale=float(settings.DIA2_CFG_SCALE),
            audio=SamplingConfig(
                temperature=float(settings.DIA2_TEMPERATURE),
                top_k=50,
            ),
            use_cuda_graph=(device == "cuda"),
        )
        tagged_text = text if text.strip().startswith("[S") else f"[S1] {text}"
        dia.generate(tagged_text, config=config, output_wav=output_path, verbose=False)
        ok, reason = _validate_audio(output_path)
        return ok, reason
    except Exception as exc:
        return False, f"Dia2 generation failed: {exc}"


def _get_kokoro():
    global _kokoro
    if _kokoro is None:
        from kokoro_onnx import Kokoro

        model_path = Path(settings.KOKORO_MODEL_PATH)
        voices_path = Path(settings.KOKORO_VOICES_PATH)
        if not model_path.exists():
            raise FileNotFoundError(f"Kokoro model missing: {model_path}")
        if not voices_path.exists():
            raise FileNotFoundError(f"Kokoro voices missing: {voices_path}")

        logger.info(f"Kokoro: loading model {model_path}")
        _kokoro = Kokoro(str(model_path), str(voices_path))
    return _kokoro


def generate_kokoro_tts(text: str, output_path: str) -> Tuple[bool, str]:
    try:
        import soundfile as sf

        kokoro = _get_kokoro()
        samples, sample_rate = kokoro.create(
            text,
            voice=settings.KOKORO_VOICE,
            speed=float(settings.KOKORO_SPEED),
            lang=settings.KOKORO_LANG,
        )
        sf.write(output_path, samples, sample_rate)
        ok, reason = _validate_audio(output_path)
        return ok, reason
    except Exception as exc:
        return False, f"Kokoro generation failed: {exc}"


def generate_espeak_fallback(text: str, output_path: str) -> Tuple[bool, str]:
    try:
        subprocess.run(
            ["espeak", "-w", output_path, text],
            check=True,
            capture_output=True,
            text=True,
        )
        ok, reason = _validate_audio(output_path)
        return ok, reason
    except Exception as exc:
        return False, f"espeak generation failed: {exc}"


def _provider_output_path(temp_dir: Path, scene_id: int, provider: str) -> str:
    suffix = "wav"
    return str(temp_dir / f"scene_{scene_id}_audio.{suffix}")


def _try_provider(provider: str, text: str, temp_dir: Path, scene_id: int) -> Tuple[bool, str, str]:
    output_path = _provider_output_path(temp_dir, scene_id, provider)
    normalized = provider.lower()
    if normalized == "dia2":
        ok, warning = generate_dia2_tts(text, output_path)
    elif normalized == "kokoro":
        ok, warning = generate_kokoro_tts(text, output_path)
    elif normalized == "espeak" and settings.ALLOW_ESPEAK_FALLBACK:
        ok, warning = generate_espeak_fallback(text, output_path)
    else:
        ok, warning = False, f"Unsupported or disabled voiceover provider: {provider}"
    return ok, output_path, warning


@app.post("/generate", response_model=VoiceoverResponse)
async def generate_voiceover(request: VoiceoverRequest):
    logger.info(f"Generating voiceover for job {request.job_id}, scene {request.scene_id}")

    run_id = str(uuid.uuid4())
    start_time = time.time()
    primary = settings.VOICEOVER_PROVIDER.lower()
    fallback = settings.VOICEOVER_FALLBACK_PROVIDER.lower()

    if _tracer:
        try:
            _tracer.create_run(
                name="voiceover.generate",
                run_type="chain",
                run_id=run_id,
                metadata={
                    "service": "voiceover",
                    "job_id": request.job_id,
                    "scene_id": request.scene_id,
                    "primary_provider": primary,
                    "fallback_provider": fallback,
                },
            )
        except Exception:
            pass

    temp_dir = Path(settings.WORKSPACE_DIR) / "temp" / request.job_id
    temp_dir.mkdir(parents=True, exist_ok=True)

    attempted = []
    for provider in (primary, fallback):
        if provider in attempted:
            continue
        attempted.append(provider)
        ok, audio_path, warning = _try_provider(
            provider,
            request.narration_text,
            temp_dir,
            request.scene_id,
        )
        if ok:
            fallback_used = provider != primary
            if warning:
                logger.warning(warning)
            logger.info(f"Voiceover scene {request.scene_id} produced by {provider}: {audio_path}")
            if _tracer:
                try:
                    _tracer.update_run(
                        run_id=run_id,
                        outputs={
                            "audio_path": audio_path,
                            "provider_used": provider,
                            "fallback_used": fallback_used,
                        },
                        end_time=time.time(),
                        metrics={"total_latency": time.time() - start_time},
                    )
                except Exception:
                    pass
            return VoiceoverResponse(
                scene_id=request.scene_id,
                audio_path=audio_path,
                provider_used=provider,
                fallback_used=fallback_used,
                warning=warning or None,
            )

        logger.warning(f"{provider} voiceover failed for scene {request.scene_id}: {warning}")

    if settings.ALLOW_ESPEAK_FALLBACK and "espeak" not in attempted:
        ok, audio_path, warning = _try_provider(
            "espeak",
            request.narration_text,
            temp_dir,
            request.scene_id,
        )
        if ok:
            logger.warning(f"Emergency espeak fallback used for scene {request.scene_id}")
            return VoiceoverResponse(
                scene_id=request.scene_id,
                audio_path=audio_path,
                provider_used="espeak",
                fallback_used=True,
                warning="Emergency espeak fallback used",
            )
        logger.warning(warning)

    message = f"Voiceover failed. Attempted providers: {', '.join(attempted)}"
    if _tracer:
        try:
            _tracer.update_run(
                run_id=run_id,
                error=message,
                end_time=time.time(),
                metrics={"total_latency": time.time() - start_time},
            )
        except Exception:
            pass
    raise HTTPException(status_code=500, detail=message)


@app.get("/health")
def health():
    return {"status": "ok"}
