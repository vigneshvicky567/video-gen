from __future__ import annotations

import asyncio
import os
import subprocess
import time
import uuid
from pathlib import Path
from typing import List, Optional, Tuple

from fastapi import FastAPI, HTTPException

from shared.config import settings
from shared.schemas.requests import VoiceoverRequest
from shared.schemas.responses import VoiceoverResponse
from shared.log import get_logger, set_log_context, timed_block, log_file, make_request_logging_middleware

app = FastAPI(title="Voiceover Service")
app.add_middleware(make_request_logging_middleware("voiceover"))
logger = get_logger(__name__)

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
    if audio_path.stat().st_size < 44:  # WAV header is 44 bytes minimum
        return False, f"audio file too small ({audio_path.stat().st_size} bytes): {path}"

    result = subprocess.run(
        [
            "ffprobe",
            "-v", "error",
            "-show_entries", "stream=codec_type,duration",
            "-of", "default=noprint_wrappers=1",
            path,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False, f"ffprobe failed for {path}: {result.stderr.strip()}"
    # WAV files sometimes report codec_type=audio without a duration line — that's fine
    if "codec_type=audio" not in result.stdout:
        return False, f"ffprobe found no audio stream in {path}: {result.stdout.strip()}"
    return True, ""


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
        import numpy as np
        import soundfile as sf

        kokoro = _get_kokoro()
        chunks = _split_text(text)
        logger.info("Kokoro TTS", extra={"chunks": len(chunks), "text_chars": len(text)})

        if len(chunks) == 1:
            samples, sample_rate = kokoro.create(
                chunks[0],
                voice=settings.KOKORO_VOICE,
                speed=float(settings.KOKORO_SPEED),
                lang=settings.KOKORO_LANG,
            )
        else:
            logger.info(f"Kokoro: splitting {len(text)} chars into {len(chunks)} chunks")
            all_samples = []
            sample_rate = 24000
            silence = np.zeros(int(sample_rate * 0.25), dtype=np.float32)  # 250ms gap
            for chunk in chunks:
                s, sample_rate = kokoro.create(
                    chunk,
                    voice=settings.KOKORO_VOICE,
                    speed=float(settings.KOKORO_SPEED),
                    lang=settings.KOKORO_LANG,
                )
                all_samples.append(s)
                all_samples.append(silence)
            samples = np.concatenate(all_samples[:-1])  # drop trailing silence

        sf.write(output_path, samples, sample_rate)
        ok, reason = _validate_audio(output_path)
        if ok:
            log_file(logger, "written", output_path)
        else:
            logger.warning("Kokoro audio validation failed", extra={"reason": reason})
        return ok, reason
    except Exception as exc:
        logger.error("Kokoro generation failed", extra={"error": str(exc)}, exc_info=True)
        return False, f"Kokoro generation failed: {exc}"


def _split_text(text: str, max_chars: int = 400) -> List[str]:
    """Split text into sentence-boundary chunks under max_chars."""
    if len(text) <= max_chars:
        return [text]

    import re
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    chunks: List[str] = []
    current = ""
    for sentence in sentences:
        if len(current) + len(sentence) + 1 <= max_chars:
            current = f"{current} {sentence}".strip()
        else:
            if current:
                chunks.append(current)
            # If a single sentence exceeds max_chars, split on commas
            if len(sentence) > max_chars:
                parts = re.split(r'(?<=,)\s+', sentence)
                sub = ""
                for part in parts:
                    if len(sub) + len(part) + 1 <= max_chars:
                        sub = f"{sub} {part}".strip()
                    else:
                        if sub:
                            chunks.append(sub)
                        sub = part
                if sub:
                    current = sub
                else:
                    current = ""
            else:
                current = sentence
    if current:
        chunks.append(current)
    return chunks or [text]



def _provider_output_path(temp_dir: Path, scene_id: int, provider: str) -> str:
    suffix = "wav"
    return str(temp_dir / f"scene_{scene_id}_audio.{suffix}")


def _try_provider(provider: str, text: str, temp_dir: Path, scene_id: int) -> Tuple[bool, str, str]:
    output_path = _provider_output_path(temp_dir, scene_id, provider)
    if provider.lower() == "kokoro":
        ok, warning = generate_kokoro_tts(text, output_path)
    else:
        ok, warning = False, f"Unsupported voiceover provider: {provider}"
    return ok, output_path, warning


@app.post("/generate", response_model=VoiceoverResponse)
async def generate_voiceover(request: VoiceoverRequest):
    set_log_context(job_id=request.job_id, scene_id=request.scene_id)
    logger.info("Voiceover request", extra={"scene_id": request.scene_id,
                                             "text_chars": len(request.narration_text),
                                             "provider": settings.VOICEOVER_PROVIDER})

    run_id = str(uuid.uuid4())
    start_time = time.time()
    primary = settings.VOICEOVER_PROVIDER.lower()
    max_retries = max(1, settings.VOICEOVER_MAX_RETRIES)
    backoff = settings.VOICEOVER_RETRY_BACKOFF_SECONDS

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
                    "max_retries": max_retries,
                },
            )
        except Exception as _trace_exc:
            logger.debug(f"LangSmith trace failed: {_trace_exc}")

    temp_dir = Path(settings.WORKSPACE_DIR) / "temp" / request.job_id
    temp_dir.mkdir(parents=True, exist_ok=True)

    last_warning = ""
    for attempt in range(1, max_retries + 1):
        # Run blocking TTS in a thread so we don't stall the event loop
        # (Kokoro ONNX inference is CPU-bound and can take several seconds)
        ok, audio_path, warning = await asyncio.to_thread(
            _try_provider, primary, request.narration_text, temp_dir, request.scene_id
        )
        if ok:
            if warning:
                logger.warning("Provider warning", extra={"provider": primary, "warning": warning})
            logger.info("Voiceover produced", extra={"scene_id": request.scene_id,
                                                      "provider": primary,
                                                      "attempt": attempt,
                                                      "audio_path": audio_path})
            if _tracer:
                try:
                    _tracer.update_run(
                        run_id=run_id,
                        outputs={
                            "audio_path": audio_path,
                            "provider_used": primary,
                            "attempts": attempt,
                        },
                        end_time=time.time(),
                        metrics={"total_latency": time.time() - start_time},
                    )
                except Exception as _trace_exc:
                    logger.debug(f"LangSmith trace failed: {_trace_exc}")
            return VoiceoverResponse(
                scene_id=request.scene_id,
                audio_path=audio_path,
                provider_used=primary,
                fallback_used=False,
                warning=warning or None,
            )

        last_warning = warning
        logger.warning("Voiceover attempt failed", extra={"provider": primary,
                                                           "scene_id": request.scene_id,
                                                           "attempt": attempt,
                                                           "max_retries": max_retries,
                                                           "reason": warning})
        if attempt < max_retries:
            await asyncio.sleep(backoff)

    message = f"Voiceover failed after {max_retries} attempt(s) with {primary}: {last_warning}"
    if _tracer:
        try:
            _tracer.update_run(
                run_id=run_id,
                error=message,
                end_time=time.time(),
                metrics={"total_latency": time.time() - start_time},
            )
        except Exception as _trace_exc:
            logger.debug(f"LangSmith trace failed: {_trace_exc}")
    raise HTTPException(status_code=500, detail=message)


@app.get("/health")
def health():
    return {"status": "ok"}
