from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import List, Optional, Tuple

from fastapi import FastAPI, HTTPException

from shared.config import settings
from shared.proc import run_proc, ProcTimeout
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

    try:
        result = run_proc(
            [
                "ffprobe",
                "-v", "error",
                "-show_entries", "stream=codec_type,duration",
                "-of", "default=noprint_wrappers=1",
                path,
            ],
            timeout=30,
        )
    except ProcTimeout:
        return False, f"ffprobe timed out validating {path}"
    if result.returncode != 0:
        return False, f"ffprobe failed for {path}: {result.stderr.strip()}"
    # WAV files sometimes report codec_type=audio without a duration line — that's fine
    if "codec_type=audio" not in result.stdout:
        return False, f"ffprobe found no audio stream in {path}: {result.stdout.strip()}"
    return True, ""


def _normalize_audio_file(path: str) -> bool:
    """Loudness-normalize the final TTS clip in place (EBU R128 via ffmpeg).

    Each provider writes raw synthesis with no gain staging, so scene-to-scene
    levels drift and the overall mix reads quiet. Target -16 LUFS for a mono
    narration clip (the compositor later masters the full multi-track mix to
    -14 LUFS, so this leaves it headroom rather than double-normalizing).

    Safe by construction: renders to a temp path first and only swaps it in on
    success. If ffmpeg is missing, errors, or times out, the original file is
    left untouched and a warning is logged — normalization is best-effort and
    must never cost us the audio.
    """
    src = Path(path)
    tmp = src.with_name(f"{src.stem}.norm{src.suffix}")
    try:
        result = run_proc(
            ["ffmpeg", "-y", "-i", str(src), "-af",
             "loudnorm=I=-16:TP=-1.5:LRA=11", str(tmp)],
            timeout=60,
        )
        if result.returncode != 0 or not tmp.exists() or tmp.stat().st_size < 44:
            logger.warning("Loudness normalization failed, keeping original audio",
                            extra={"path": path, "stderr": (result.stderr or "")[:200]})
            tmp.unlink(missing_ok=True)
            return False
        tmp.replace(src)
        return True
    except ProcTimeout:
        logger.warning("Loudness normalization timed out, keeping original audio",
                        extra={"path": path})
        tmp.unlink(missing_ok=True)
        return False
    except Exception as exc:  # noqa: BLE001 — normalization is best-effort, never fatal
        logger.warning("Loudness normalization errored, keeping original audio",
                        extra={"path": path, "error": str(exc)[:200]})
        tmp.unlink(missing_ok=True)
        return False


def _normalize_or_warn(path: str, provider: str) -> None:
    """Shared tail for each provider: loudness-normalize `path` in place and
    log (not raise) if normalization couldn't be applied. Keeps the three
    identical if-not-normalized-then-warn blocks (kokoro/edge/piper) from
    drifting out of sync with each other."""
    if not _normalize_audio_file(path):
        logger.warning(f"{provider} output not loudness-normalized; using raw synthesis",
                        extra={"path": path})


def _get_kokoro():
    global _kokoro
    if _kokoro is None:
        import os
        from kokoro_onnx import Kokoro

        model_path = Path(settings.KOKORO_MODEL_PATH)
        voices_path = Path(settings.KOKORO_VOICES_PATH)
        if not model_path.exists():
            raise FileNotFoundError(f"Kokoro model missing: {model_path}")
        if not voices_path.exists():
            raise FileNotFoundError(f"Kokoro voices missing: {voices_path}")

        # Prefer the GPU when onnxruntime actually exposes CUDA; else CPU. Safe on a
        # CPU-only image: get_available_providers() won't list CUDA, so we stay on
        # CPU with zero behavior change. Activating the GPU needs onnxruntime-gpu +
        # CUDA libs in the image (see Dockerfile.voiceover) — this code just uses it
        # once present. Honors ONNX_PROVIDER (kokoro-onnx reads it) AND passes
        # providers= when the installed Kokoro supports the kwarg.
        try:
            import onnxruntime as ort
            avail = ort.get_available_providers()
        except Exception:  # noqa: BLE001 — never let provider probing kill TTS
            avail = ["CPUExecutionProvider"]
        providers = (["CUDAExecutionProvider", "CPUExecutionProvider"]
                     if "CUDAExecutionProvider" in avail else ["CPUExecutionProvider"])
        os.environ.setdefault("ONNX_PROVIDER", providers[0])

        logger.info(f"Kokoro: loading model {model_path} (providers={providers})")
        try:
            _kokoro = Kokoro(str(model_path), str(voices_path), providers=providers)
        except TypeError:
            # older kokoro-onnx without a providers kwarg — relies on ONNX_PROVIDER env
            _kokoro = Kokoro(str(model_path), str(voices_path))
    return _kokoro


def _verbalize_code_math(text: str) -> str:
    """Turn common code/math notation into words before the generic
    symbol-stripping regex in `_clean_for_tts` throws the same characters away
    as noise (e.g. `dp[i]=x` would otherwise lose the `=` and read as
    "dp i x"). Order matters here: the `O(...)` and `name[...]` patterns run
    first (each is a whole-token shape), then multi-char operators (`==`,
    `<=`, `>=`, `!=`) before the single-char ones (`=`, `*`, `+`), so a
    multi-char operator is never split by an earlier single-char rule.

    IMPORTANT: `_clean_for_tts` must call this BEFORE it collapses whitespace
    (`\\s+` -> " "). The `*`/`+` rule below relies on seeing real newlines to
    tell a markdown bullet's `* item` apart from arithmetic like `a + b` --
    once a newline is flattened to a plain space the two look identical and
    can no longer be told apart.

    Narration text here is LLM/markdown-authored, so `*` and `+` are just as
    likely to be markdown (`* bullet`, `**bold**`, `*italic*`) as arithmetic.
    Bare `<`/`>` are similarly ambiguous in prose (e.g. "Replace <PLACEHOLDER>
    with...") so they are intentionally NOT verbalized here -- they fall
    through to the markdown/symbol-strip regex in `_clean_for_tts`, same as
    before this function existed.
    """
    import re

    # Big-O notation: `O(n)`, `O(n^2)`, `O(log n)`, `O(1)` -> spoken phrases.
    # Anything else inside O(...) (e.g. `O(n log n)`) falls back to
    # "big O of <contents>" rather than silently disappearing.
    def _big_o(m: "re.Match") -> str:
        inner = m.group(1).strip()
        squashed = inner.replace(" ", "")
        if squashed == "1":
            return "big O of one"
        if squashed in ("n^2", "n**2"):
            return "big O of n squared"
        if squashed.lower() == "logn":
            return "big O of log n"
        if squashed == "n":
            return "big O of n"
        return f"big O of {inner}"

    text = re.sub(r"\bO\(([^()]*)\)", _big_o, text)

    # Array/sequence indexing: `name[expr]` -> "name of expr". A bare `-`
    # between operands inside the index (e.g. `i-1`) is spoken as "minus"
    # instead of vanishing in the symbol strip below (matching how `+` is
    # already spoken as "plus" there).
    def _index(m: "re.Match") -> str:
        name, inner = m.group(1), m.group(2)
        inner = re.sub(r"(?<=\w)-(?=\w)", " minus ", inner)
        return f"{name} of {inner}"

    text = re.sub(r"\b([A-Za-z_][A-Za-z0-9_]*)\[([^\[\]]*)\]", _index, text)

    # Operators, multi-char tokens before single-char so e.g. `<=` isn't left
    # as a stray `<` once the plain `=` rule below has run. `==` must come
    # before the single `=` rule for the same reason (`x == y` -> "x equals
    # y", not "x equals equals y"). Bare `<`/`>` are deliberately NOT handled
    # here (see docstring) -- they fall through to the symbol-strip regex.
    text = re.sub(r"\s*<=\s*", " less than or equal to ", text)
    text = re.sub(r"\s*>=\s*", " greater than or equal to ", text)
    text = re.sub(r"\s*!=\s*", " not equal to ", text)
    text = re.sub(r"\s*==\s*", " equals ", text)
    text = re.sub(r"\s*=\s*", " equals ", text)

    # `*` and `+` double as markdown syntax (bullets, `**bold**`, `*italic*`),
    # so they only become words when they sit BETWEEN two operands with
    # *matching* spacing on both sides -- either touching directly (`2*n`) or
    # the same run of spaces/tabs on each side (`a + b`, `rob1 + n`). The
    # `(?P<ws>...)` / `(?P=ws)` backreference enforces that symmetry, which is
    # what rules out asymmetric markdown like `*italic*` (space outside, none
    # inside) and doubled `**bold**` (a `*` is never itself an operand, so the
    # lookbehind/lookahead on the inner pair of stars both fail). Only
    # `[ \t]` -- not `\n` -- counts as spacing here, so a bullet's `* ` sitting
    # right after a newline fails the lookbehind (the preceding char is `\n`,
    # not an operand) and is left for the markdown-strip regex, same as
    # before this function existed.
    text = re.sub(r"(?<=[A-Za-z0-9)])(?P<ws>[ \t]*)\*(?P=ws)(?=[A-Za-z0-9(])", " times ", text)
    text = re.sub(r"(?<=[A-Za-z0-9)])(?P<ws>[ \t]*)\+(?P=ws)(?=[A-Za-z0-9(])", " plus ", text)

    return text


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

    text = re.sub(r"[;:]", ", ", text)                   # semicolon/colon -> comma
    # _verbalize_code_math runs BEFORE whitespace is collapsed -- it needs real
    # newlines intact to tell a markdown bullet's `* item` apart from
    # arithmetic like `a + b` (see that function's docstring).
    text = _verbalize_code_math(text)                    # code/math tokens -> words (before symbol strip)
    text = re.sub(r"\s+", " ", text)                     # collapse all whitespace to single spaces
    text = re.sub(r"[*_`#>|~^\\/{}\[\]<>=+]", " ", text)  # markdown/symbols -> space
    text = text.replace('"', "")                        # straight quotes confuse line count

    # 2. Hard guarantee: strip anything still outside printable ASCII so no stray
    #    Unicode (control chars, leftover replacement chars, exotic punctuation)
    #    can reach espeak and desync its input/output line count.
    text = "".join(c for c in text if 32 <= ord(c) < 127)

    text = re.sub(r"\s+", " ", text)                     # re-collapse
    return text.strip()


def _pause_for_sentence(sentence: str) -> float:
    """Trailing silence after a sentence, keyed off its last non-space
    character so delivery isn't flatly paced: a question or exclamation gets
    a longer beat, a period a medium one, anything else keeps the original
    short gap. Deterministic — no randomness, no external state."""
    stripped = sentence.rstrip()
    last = stripped[-1] if stripped else ""
    if last in "?!":
        return 0.35
    if last == ".":
        return 0.25
    return 0.15


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
                # Punctuation-aware pause: longer after a question/exclamation,
                # medium after a period, short otherwise (see _pause_for_sentence).
                gap = _pause_for_sentence(sent)
                cursor += dur + gap
                all_samples.append(s)
                all_samples.append(np.zeros(int(sample_rate * gap), dtype=np.float32))
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
        _normalize_or_warn(output_path, "Kokoro")
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

        _normalize_or_warn(output_path, "edge-tts")
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
        try:
            # Scene narrations are short (<1 min speech); 180s is generous for
            # CPU synthesis — a piper that runs longer is hung, not slow.
            result = run_proc(cmd, timeout=180, input=clean)
        except ProcTimeout:
            return False, "piper timed out (180s) — killed process tree", []
        if result.returncode != 0:
            return False, f"piper failed (rc={result.returncode}): {result.stderr.strip()[:200]}", []

        _normalize_or_warn(output_path, "piper")
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
    try:
        r = run_proc(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            timeout=30,
        )
        return float(r.stdout.strip())
    except (ProcTimeout, ValueError, AttributeError):
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


def demo() -> None:
    """Framework-free self-check for the `_clean_for_tts` code/math lexicon
    (FIX 3) and the punctuation-aware pause table (FIX 2). Exercises pure
    functions only — no FastAPI, no kokoro/onnx — so it can run on a host
    that doesn't have the service's heavy deps installed."""
    cleaned = _clean_for_tts("dp[i-1] = max(dp[i-1], O(n))")
    print(f"cleaned: {cleaned!r}")
    assert "dp of i minus 1" in cleaned, cleaned
    assert "equals" in cleaned, cleaned
    assert "big O of n" in cleaned, cleaned
    assert "[" not in cleaned, cleaned
    assert "=" not in cleaned, cleaned

    cases = {
        "O(n^2) beats O(n) for large n.": ("big O of n squared", "big O of n"),
        "Is this O(log n)?": ("big O of log n",),
        "Constant time is O(1).": ("big O of one",),
        "arr[j] <= arr[j+1] and x != y": ("arr of j", "less than or equal to", "not equal to"),
        "total = a + b * c": ("equals", "plus", "times"),
    }
    for text, expected_fragments in cases.items():
        out = _clean_for_tts(text)
        print(f"{text!r} -> {out!r}")
        for frag in expected_fragments:
            assert frag in out, f"expected {frag!r} in {out!r} (from {text!r})"
        assert "[" not in out and "]" not in out, out
        assert "=" not in out, out

    # --- Regression coverage: `*`/`+` -> words must not mangle markdown
    # (bullets, bold/italic) that would otherwise look "operand-flanked"
    # once whitespace is collapsed, and the folded-in fixes (`==`, bare
    # `<`/`>` removal, index-internal minus) must behave as specified. ---
    bullets = _clean_for_tts("* First\n* Second")
    print(f"bullets -> {bullets!r}")
    assert "First" in bullets and "Second" in bullets, bullets
    assert "times" not in bullets, bullets

    emphasis = _clean_for_tts("This is **bold** and *italic* text")
    print(f"emphasis -> {emphasis!r}")
    assert "times" not in emphasis, emphasis
    assert "bold" in emphasis and "italic" in emphasis, emphasis

    eq = _clean_for_tts("if x == y")
    print(f"eq -> {eq!r}")
    assert "x equals y" in eq, eq
    assert "equals equals" not in eq, eq

    placeholder = _clean_for_tts("Replace <KEY> now")
    print(f"placeholder -> {placeholder!r}")
    assert "less than" not in placeholder, placeholder

    dp = _clean_for_tts("dp[i-1] = max(rob1 + n, rob2)")
    print(f"dp -> {dp!r}")
    assert "dp of i minus 1" in dp, dp
    assert "equals" in dp, dp
    assert "rob1 plus n" in dp, dp

    assert _pause_for_sentence("Is this correct?") == 0.35
    assert _pause_for_sentence("Wow!") == 0.35
    assert _pause_for_sentence("This is a fact.") == 0.25
    assert _pause_for_sentence("mid-sentence fragment") == 0.15

    print("All _clean_for_tts / _pause_for_sentence self-checks passed.")


if __name__ == "__main__":
    demo()
