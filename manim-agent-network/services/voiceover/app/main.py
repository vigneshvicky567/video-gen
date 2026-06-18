from __future__ import annotations

import asyncio
import subprocess
import time
from pathlib import Path
from typing import List, Optional, Tuple

from fastapi import FastAPI, HTTPException

from shared.config import settings
from shared.schemas.requests import VoiceoverRequest
from shared.schemas.responses import VoiceoverResponse
from shared.log import get_logger, set_log_context, log_file, make_request_logging_middleware
from langsmith import traceable

app = FastAPI(title="Voiceover Service")
app.add_middleware(make_request_logging_middleware("voiceover"))
logger = get_logger(__name__)

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


def _clean_for_tts(text: str) -> str:
    """Normalise narration for eSpeak. Collapse whitespace and drop characters
    that make kokoro-onnx's phonemizer emit a mismatched input/output line count
    ("number of lines in input and output must be equal") and crash TTS."""
    import re
    import unicodedata

    # 1. Normalise Unicode, then map common typographic chars to ASCII. The real
    #    crasher was U+FFFD (mojibake from a smart apostrophe) surviving into espeak.
    text = unicodedata.normalize("NFKC", text)
    table = {
        "’": "'", "‘": "'", "“": "", "”": "",   # smart quotes
        "–": ", ", "—": ", ", "…": " ",              # dashes, ellipsis
        "�": "",                                                # replacement char
    }
    for k, v in table.items():
        text = text.replace(k, v)

    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[;:]", ", ", text)                   # semicolon/colon -> comma
    text = re.sub(r"[*_`#>|~^\\/{}\[\]<>=+]", " ", text)  # markdown/symbols -> space
    text = text.replace('"', "")                        # straight quotes confuse line count

    # 2. Hard guarantee: strip anything still outside printable ASCII so no stray
    #    Unicode (control chars, leftover replacement chars, exotic punctuation)
    #    can reach espeak and desync its input/output line count.
    text = "".join(c for c in text if 32 <= ord(c) < 127)

    text = re.sub(r"\s+", " ", text)                     # re-collapse
    return text.strip()


def generate_kokoro_tts(text: str, output_path: str) -> Tuple[bool, str]:
    try:
        import numpy as np
        import soundfile as sf

        kokoro = _get_kokoro()
        # Generate one sentence at a time. eSpeak's line-mismatch crash is
        # content-dependent; isolating sentences means a single bad one is
        # SKIPPED (logged) instead of failing the whole scene's narration.
        sentences = _split_sentences(_clean_for_tts(text))
        logger.info("Kokoro TTS", extra={"sentences": len(sentences), "text_chars": len(text)})

        sample_rate = 24000
        silence = np.zeros(int(sample_rate * 0.15), dtype=np.float32)  # 150ms gap
        all_samples = []
        skipped = 0
        for sent in sentences:
            try:
                s, sample_rate = kokoro.create(
                    sent,
                    voice=settings.KOKORO_VOICE,
                    speed=float(settings.KOKORO_SPEED),
                    lang=settings.KOKORO_LANG,
                )
                all_samples.append(s)
                all_samples.append(silence)
            except Exception as se:
                skipped += 1
                logger.warning("Kokoro skipped a sentence", extra={"error": str(se)[:120],
                                                                    "sentence": sent[:80]})

        if not all_samples:
            return False, "Kokoro produced no audio (every sentence failed phonemization)"
        if skipped:
            logger.warning(f"Kokoro skipped {skipped}/{len(sentences)} sentences")

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


def _split_sentences(text: str, max_chars: int = 400) -> List[str]:
    """Sentence-boundary split, with over-long sentences broken on commas then
    hard-wrapped. Keeps each piece small so eSpeak phonemizes it cleanly."""
    import re
    if not text:
        return []
    pieces = re.split(r'(?<=[.!?])\s+', text)
    out: List[str] = []
    for p in pieces:
        p = p.strip()
        if not p:
            continue
        if len(p) <= max_chars:
            out.append(p)
            continue
        # over-long: split on commas, then hard-wrap any remaining giant span
        for part in re.split(r'(?<=,)\s+', p):
            part = part.strip()
            while len(part) > max_chars:
                out.append(part[:max_chars])
                part = part[max_chars:]
            if part:
                out.append(part)
    return out





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
@traceable(run_type="chain", name="voiceover.generate")
async def generate_voiceover(request: VoiceoverRequest):
    set_log_context(job_id=request.job_id, scene_id=request.scene_id)
    logger.info("Voiceover request", extra={"scene_id": request.scene_id,
                                             "text_chars": len(request.narration_text),
                                             "provider": settings.VOICEOVER_PROVIDER})

    start_time = time.time()
    primary = settings.VOICEOVER_PROVIDER.lower()
    max_retries = max(1, settings.VOICEOVER_MAX_RETRIES)
    backoff = settings.VOICEOVER_RETRY_BACKOFF_SECONDS

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
    raise HTTPException(status_code=500, detail=message)


@app.get("/health")
def health():
    return {"status": "ok"}
