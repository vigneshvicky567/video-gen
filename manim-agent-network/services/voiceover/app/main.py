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
    if audio_path.stat().st_size < 44:  # smaller than any viable WAV/MP3 file
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


def generate_kokoro_tts(text: str, output_path: str, speed: float = 1.0) -> Tuple[bool, str, list]:
    try:
        import numpy as np
        import soundfile as sf

        kokoro = _get_kokoro()
        # Generate one sentence at a time. eSpeak's line-mismatch crash is
        # content-dependent; isolating sentences means a single bad one is
        # SKIPPED (logged) instead of failing the whole scene's narration.
        # Per-sentence synthesis ALSO gives EXACT timing: each sentence's sample
        # count is its real duration, so we can hand code-gen a precise cue sheet.
        sentences = _split_sentences(_clean_for_tts(text))
        logger.info("Kokoro TTS", extra={"sentences": len(sentences), "text_chars": len(text)})

        sample_rate = 24000
        gap = 0.15
        silence = np.zeros(int(sample_rate * gap), dtype=np.float32)  # 150ms gap
        all_samples = []
        segments: list = []
        cursor = 0.0
        skipped = 0
        for sent in sentences:
            try:
                s, sample_rate = kokoro.create(
                    sent,
                    voice=settings.KOKORO_VOICE,
                    speed=speed,
                    lang=settings.KOKORO_LANG,
                )
                dur = len(s) / float(sample_rate)
                segments.append({"text": sent, "start": round(cursor, 3), "duration": round(dur, 3)})
                cursor += dur + gap
                all_samples.append(s)
                all_samples.append(silence)
            except Exception as se:
                skipped += 1
                logger.warning("Kokoro skipped a sentence", extra={"error": str(se)[:120],
                                                                    "sentence": sent[:80]})

        if not all_samples:
            return False, "Kokoro produced no audio (every sentence failed phonemization)", []
        if skipped:
            logger.warning(f"Kokoro skipped {skipped}/{len(sentences)} sentences")

        samples = np.concatenate(all_samples[:-1])  # drop trailing silence
        sf.write(output_path, samples, sample_rate)
        ok, reason = _validate_audio(output_path)
        if ok:
            log_file(logger, "written", output_path)
        else:
            logger.warning("Kokoro audio validation failed", extra={"reason": reason})
        return ok, reason, segments
    except Exception as exc:
        logger.error("Kokoro generation failed", extra={"error": str(exc)}, exc_info=True)
        return False, f"Kokoro generation failed: {exc}", []


def _speed_to_rate(speed: float) -> str:
    """edge-tts wants a percentage delta string, e.g. 1.3 -> '+30%', 0.9 -> '-10%'."""
    pct = int(round((speed - 1.0) * 100))
    return f"+{pct}%" if pct >= 0 else f"{pct}%"


def generate_edge_tts(text: str, output_path: str, speed: float = 1.0) -> Tuple[bool, str, list]:
    """Free fallback TTS via Microsoft edge-tts (no API key, network required).

    Used when Kokoro is unavailable (missing model, phonemizer failure). Writes
    MP3 bytes to output_path (which carries a .mp3 suffix via _provider_output_path);
    validation is ffprobe-based. Reuses the same text cleaning as Kokoro."""
    try:
        import edge_tts

        clean = _clean_for_tts(text)
        if not clean:
            return False, "edge-tts: empty text after cleaning", []

        rate = _speed_to_rate(speed)

        async def _run() -> None:
            communicate = edge_tts.Communicate(clean, settings.EDGE_TTS_VOICE, rate=rate)
            await communicate.save(output_path)

        # generate_edge_tts runs inside a worker thread (asyncio.to_thread), so
        # there is no running loop here — asyncio.run is safe.
        asyncio.run(_run())

        ok, reason = _validate_audio(output_path)
        if ok:
            log_file(logger, "written", output_path)
        else:
            logger.warning("edge-tts audio validation failed", extra={"reason": reason})
        segments = _proportional_segments(text, _audio_duration(output_path)) if ok else []
        return ok, reason, segments
    except Exception as exc:
        logger.error("edge-tts generation failed", extra={"error": str(exc)}, exc_info=True)
        return False, f"edge-tts generation failed: {exc}", []


def generate_piper_tts(text: str, output_path: str, speed: float = 1.0) -> Tuple[bool, str]:
    """Offline neural fallback via Piper (ONNX). Fully local, no network.

    Independent of Kokoro's runtime and phonemizer path (separate package), so it
    survives the exact failure that killed Kokoro (onnxruntime/CUDA import, misaki
    phoneme line-mismatch). Driven via the `piper` CLI with text on stdin — the
    -m/-f flags are stable across piper versions, unlike the changing Python API.
    Writes WAV. Speed is left at the model default (piper is the fallback)."""
    try:
        clean = _clean_for_tts(text)
        if not clean:
            return False, "piper: empty text after cleaning", []
        model = settings.PIPER_MODEL_PATH
        if not Path(model).exists():
            return False, f"piper model missing: {model}", []

        cmd = ["piper", "-m", model, "-f", output_path]
        result = subprocess.run(cmd, input=clean, capture_output=True, text=True)
        if result.returncode != 0:
            return False, f"piper failed (rc={result.returncode}): {result.stderr.strip()[:200]}", []

        ok, reason = _validate_audio(output_path)
        if ok:
            log_file(logger, "written", output_path)
        else:
            logger.warning("piper audio validation failed", extra={"reason": reason})
        segments = _proportional_segments(text, _audio_duration(output_path)) if ok else []
        return ok, reason, segments
    except Exception as exc:
        logger.error("piper generation failed", extra={"error": str(exc)}, exc_info=True)
        return False, f"piper generation failed: {exc}", []


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





def _audio_duration(path: str) -> float:
    """Total seconds via ffprobe. 0.0 if unreadable."""
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True,
    )
    try:
        return float(r.stdout.strip())
    except (ValueError, AttributeError):
        return 0.0


def _proportional_segments(text: str, total_dur: float) -> list:
    """Approximate per-sentence timing by splitting total_dur across sentences in
    proportion to character length. Used by providers that emit one audio blob
    (piper/edge); kokoro reports exact per-sentence durations instead."""
    sents = _split_sentences(_clean_for_tts(text))
    if not sents or total_dur <= 0:
        return []
    lens = [max(1, len(s)) for s in sents]
    tot = sum(lens)
    segs, cur = [], 0.0
    for s, l in zip(sents, lens):
        d = total_dur * l / tot
        segs.append({"text": s, "start": round(cur, 3), "duration": round(d, 3)})
        cur += d
    return segs


def _provider_output_path(temp_dir: Path, scene_id: int, provider: str) -> str:
    # Kokoro writes WAV (soundfile); edge-tts writes MP3. Use the right extension
    # so downstream consumers that infer format from the suffix don't misread it.
    suffix = "mp3" if provider.lower() in ("edge_tts", "edge", "edgetts") else "wav"
    return str(temp_dir / f"scene_{scene_id}_audio.{suffix}")


def _try_provider(
    provider: str, text: str, temp_dir: Path, scene_id: int, speed: float = 1.0
) -> Tuple[bool, str, str, list]:
    output_path = _provider_output_path(temp_dir, scene_id, provider)
    p = provider.lower()
    if p == "kokoro":
        ok, warning, segments = generate_kokoro_tts(text, output_path, speed)
    elif p in ("piper", "piper_tts"):
        ok, warning, segments = generate_piper_tts(text, output_path, speed)
    elif p in ("edge_tts", "edge", "edgetts"):
        ok, warning, segments = generate_edge_tts(text, output_path, speed)
    else:
        ok, warning, segments = False, f"Unsupported voiceover provider: {provider}", []
    return ok, output_path, warning, segments


@app.post("/generate", response_model=VoiceoverResponse)
@traceable(run_type="chain", name="voiceover.generate")
async def generate_voiceover(request: VoiceoverRequest):
    set_log_context(job_id=request.job_id, scene_id=request.scene_id)
    logger.info("Voiceover request", extra={"scene_id": request.scene_id,
                                             "text_chars": len(request.narration_text),
                                             "provider": settings.VOICEOVER_PROVIDER})

    start_time = time.time()
    primary = settings.VOICEOVER_PROVIDER.lower()
    # Fallback chain: comma-separated, tried in order after the primary. All-offline
    # by default (kokoro -> piper). Each provider is a distinct engine so a runtime
    # break in one doesn't take down the next.
    fallbacks = [p.strip().lower() for p in (settings.VOICEOVER_FALLBACK_PROVIDER or "").split(",") if p.strip()]
    max_retries = max(1, settings.VOICEOVER_MAX_RETRIES)
    backoff = settings.VOICEOVER_RETRY_BACKOFF_SECONDS

    # request.speed is None when the caller didn't specify one -> use the
    # configured KOKORO_SPEED. An explicit value (including 1.0) overrides it.
    speed = float(settings.KOKORO_SPEED) if request.speed is None else float(request.speed)

    temp_dir = Path(settings.WORKSPACE_DIR) / "temp" / request.job_id
    temp_dir.mkdir(parents=True, exist_ok=True)

    # Build the ordered provider chain (primary first), de-duped, preserving order.
    chain: List[str] = [primary] + fallbacks
    seen: set = set()
    chain = [p for p in chain if not (p in seen or seen.add(p))]
    providers = [(p, idx > 0) for idx, p in enumerate(chain)]

    last_warning = ""
    for provider, is_fallback in providers:
        for attempt in range(1, max_retries + 1):
            # Run blocking TTS in a thread so we don't stall the event loop
            # (Kokoro ONNX inference is CPU-bound and can take several seconds)
            ok, audio_path, warning, segments = await asyncio.to_thread(
                _try_provider, provider, request.narration_text, temp_dir, request.scene_id, speed
            )
            if ok:
                if warning:
                    logger.warning("Provider warning", extra={"provider": provider, "warning": warning})
                logger.info("Voiceover produced", extra={"scene_id": request.scene_id,
                                                          "provider": provider,
                                                          "fallback_used": is_fallback,
                                                          "attempt": attempt,
                                                          "segments": len(segments or []),
                                                          "audio_path": audio_path})
                return VoiceoverResponse(
                    scene_id=request.scene_id,
                    audio_path=audio_path,
                    provider_used=provider,
                    fallback_used=is_fallback,
                    warning=warning or None,
                    segments=segments or None,
                )

            last_warning = warning
            logger.warning("Voiceover attempt failed", extra={"provider": provider,
                                                               "is_fallback": is_fallback,
                                                               "scene_id": request.scene_id,
                                                               "attempt": attempt,
                                                               "max_retries": max_retries,
                                                               "reason": warning})
            if attempt < max_retries:
                await asyncio.sleep(backoff)

        if len(providers) > 1 and (provider, is_fallback) != providers[-1]:
            logger.warning("Provider exhausted, trying next in chain",
                           extra={"failed": provider, "chain": [p for p, _ in providers],
                                  "scene_id": request.scene_id})

    tried = " -> ".join(p for p, _ in providers)
    message = f"Voiceover failed after trying [{tried}], {max_retries} attempt(s) each: {last_warning}"
    raise HTTPException(status_code=500, detail=message)


@app.get("/health")
def health():
    return {"status": "ok"}
