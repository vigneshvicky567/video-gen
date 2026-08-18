"""Final-cut polish for the compositor: background-music bed + intro/outro concat.

Runs once at the end of /assemble, after the film MP4 exists. Intro/outro/music
are optional (INTRO_VIDEO_PATH / OUTRO_VIDEO_PATH / BG_MUSIC_PATH), but this is
NOT a passthrough even with all unset: whenever the film has an audio track it
gets a final -14 LUFS loudnorm master pass (audio re-encoded, video -c:v copy),
so the output is only byte-for-byte identical to the input when the film has no
audio at all and no assets are configured.

Ordering (spec MUS-005 rev.2): intro/outro are concatenated around the film
FIRST, THEN a single music+loudness pass runs over the WHOLE resulting
timeline — so the branded intro/outro get the same music bed and loudness
target as the explainer, instead of silent/quiet branding clips bolted onto a
separately-mixed body.

The ffmpeg arg-builders are pure (no IO) so they unit-test on the host without
ffmpeg; finalize_film() wraps them with ffprobe + subprocess.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional, Tuple

from shared.config import settings
from shared.log import get_logger
from shared.proc import run_proc, ProcTimeout

from .duration_prober import probe_duration, AssemblyError

logger = get_logger(__name__)

_W, _H, _FPS, _AR = 1920, 1080, 30, 48000


def build_music_mix_cmd(
    film: str, music: str, out: str, film_duration: float,
    volume: float, fadeout: float, film_has_audio: bool,
) -> List[str]:
    """ffmpeg command to mix a looping, low-volume music bed under the film,
    then master the result to the platform loudness target.

    Music loops to cover the film, is trimmed to film length (-shortest), and
    fades out over the last `fadeout` seconds. Video is stream-copied (no
    re-encode). When the film has narration, the bed is sidechain-ducked under
    it (quieter while someone is talking, back up in the gaps) via
    sidechaincompress, the duck-bed and narration are mixed with
    `amix ... normalize=0` (ffmpeg's default amix normalize halves every input
    — we do our own loudness pass instead), and the mix is loudness-normalized
    to -14 LUFS. When the film has no audio (all TTS failed) the music becomes
    the sole track over the film's silence, still loudness-normalized.
    """
    fade_start = max(0.0, film_duration - fadeout)
    bed = f"[1:a]volume={volume},afade=t=out:st={fade_start:.3f}:d={fadeout:.3f}[bed]"
    if film_has_audio:
        flt = (
            f"{bed};[0:a]asplit=2[main][key];"
            f"[bed][key]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[duckbed];"
            f"[main][duckbed]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[mix];"
            f"[mix]loudnorm=I=-14:TP=-1.5:LRA=11[a]"
        )
    else:
        flt = f"{bed};[bed]loudnorm=I=-14:TP=-1.5:LRA=11[a]"
    return [
        "ffmpeg", "-y", "-i", film, "-stream_loop", "-1", "-i", music,
        "-filter_complex", flt,
        "-map", "0:v", "-map", "[a]",
        "-c:v", "copy", "-c:a", "aac", "-shortest",
        "-movflags", "+faststart", out,
    ]


def build_loudnorm_cmd(film: str, out: str) -> List[str]:
    """ffmpeg command for the no-music master pass: loudness-normalize the
    film's own audio to the platform target (-14 LUFS) with no other changes.
    Video is stream-copied so the concat pass's encode is preserved.
    """
    flt = "[0:a]loudnorm=I=-14:TP=-1.5:LRA=11[a]"
    return [
        "ffmpeg", "-y", "-i", film,
        "-filter_complex", flt,
        "-map", "0:v", "-map", "[a]",
        "-c:v", "copy", "-c:a", "aac",
        "-movflags", "+faststart", out,
    ]


def build_concat_cmd(parts: List[str], out: str) -> Optional[List[str]]:
    """ffmpeg concat-FILTER command joining `parts` in order into one MP4.

    This is now the FINAL video encode of the pipeline — the music/loudnorm
    pass that may follow stream-copies video (`-c:v copy`), so whatever
    quality is baked in here is what ships. Re-encodes (not the stream-copy
    concat demuxer) because intro/outro are authored externally and won't
    match the film's codec/timebase/SAR. Every input is normalized to
    1920x1080 / 30fps / yuv420p / 48k stereo so the seam is glitch-free.
    Caller MUST guarantee every part has an audio stream (see ensure_audio) —
    the graph maps [i:a] for each input.
    """
    if len(parts) < 2:
        return None
    cmd: List[str] = ["ffmpeg", "-y"]
    for p in parts:
        cmd += ["-i", p]
    chains, labels = [], []
    for i in range(len(parts)):
        chains.append(f"[{i}:v]scale={_W}:{_H},setsar=1,fps={_FPS},format=yuv420p[v{i}]")
        chains.append(f"[{i}:a]aresample={_AR},aformat=channel_layouts=stereo[a{i}]")
        labels.append(f"[v{i}][a{i}]")
    flt = ";".join(chains) + ";" + "".join(labels) + f"concat=n={len(parts)}:v=1:a=1[v][a]"
    cmd += [
        "-filter_complex", flt, "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-c:a", "aac", "-movflags", "+faststart", out,
    ]
    return cmd


def _has_audio_stream(path: str) -> bool:
    """True iff ffprobe positively reports an audio stream. Probe failure is
    treated as no-audio (routes through safe silent-audio synthesis) rather
    than certifying unknown files as having audio."""
    try:
        r = run_proc(
            ["ffprobe", "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=index", "-of", "csv=p=0", path],
            timeout=60,
        )
        if r.returncode != 0:
            logger.warning("ffprobe failed checking audio (%s); treating as no-audio", path)
            return False
        return bool(r.stdout.strip())
    except Exception as e:
        logger.warning("ffprobe error checking audio (%s): %s; treating as no-audio", path, e)
        return False


def _run(cmd: List[str], out: Path, label: str, timeout_s: int) -> None:
    try:
        r = run_proc(cmd, timeout=timeout_s)
    except ProcTimeout:
        raise AssemblyError(f"{label} timed out after {timeout_s}s (process tree killed)")
    if r.returncode != 0 or not out.exists() or out.stat().st_size == 0:
        raise AssemblyError(f"{label} failed (rc={r.returncode}): {r.stderr[-800:]}")


def _ensure_audio(path: Path, work_dir: Path) -> Path:
    """Return a copy of `path` guaranteed to have an audio stream, synthesizing
    a silent track when the source (e.g. a music-less intro) has none. INT-004.
    """
    if _has_audio_stream(str(path)):
        return path
    out = work_dir / f"{path.stem}_aud.mp4"
    cmd = [
        "ffmpeg", "-y", "-i", str(path),
        "-f", "lavfi", "-i", f"anullsrc=channel_layout=stereo:sample_rate={_AR}",
        "-shortest", "-c:v", "copy", "-c:a", "aac", str(out),
    ]
    _run(cmd, out, f"silent-audio synth ({path.name})", 600)
    return out


def _timeout_for(duration_s: float) -> int:
    # Re-encode concat runs at -preset fast (crf 18) — a modest bump over the
    # old veryfast, chosen so long films with intro/outro still finish under the
    # cap on CPU-only hosts. 6x + slack, capped.
    return int(min(settings.COMPOSITOR_CHUNK_TIMEOUT_MAX_SECONDS, max(300, duration_s * 6)))


def finalize_film(film_path: Path, work_dir: Path) -> Tuple[Path, float]:
    """Concat intro/outro, lay the music bed, and master loudness in place.
    Returns (film_path, intro_seconds). A final -14 LUFS loudnorm pass runs
    whenever the film has audio, even with no intro/outro/music configured.

    film_path is mutated in place (the result replaces it) so the /video URL and
    downstream path stay stable. intro_seconds is 0.0 when no intro is set — the
    frontend offsets transcript timestamps by it (TRN-005).
    """
    intro = settings.INTRO_VIDEO_PATH.strip()
    outro = settings.OUTRO_VIDEO_PATH.strip()
    music = settings.BG_MUSIC_PATH.strip()

    # Rotate through a BGM directory when BG_MUSIC_PATH isn't pinned to one file.
    # Pick deterministically: hash(job stem) mod count — same job → same track.
    if not music and settings.BG_MUSIC_DIR.strip():
        bgm_dir = Path(settings.BG_MUSIC_DIR.strip())
        tracks = sorted(p for p in bgm_dir.iterdir()
                        if p.suffix.lower() in (".mp3", ".wav", ".aac", ".ogg", ".flac")
                        and p.is_file())
        if tracks:
            idx = hash(film_path.stem) % len(tracks)
            music = str(tracks[idx])
            logger.info("BGM rotation selected", extra={"track": tracks[idx].name, "index": idx})

    work_dir.mkdir(parents=True, exist_ok=True)

    def _exists(p: str) -> bool:
        if not p:
            return False
        if not Path(p).is_file():
            logger.warning("Polish asset configured but missing — skipping", extra={"path": p})
            return False
        return True

    work = film_path
    intro_seconds = 0.0

    # 1) concat intro + film + outro FIRST (re-encode, normalize, synth
    # silence) so the music/loudness pass below runs over the WHOLE timeline,
    # not just the film body — branded intro/outro get the same bed + target.
    # ponytail: full re-encode of the film each time intro/outro present. Spec's
    # robust choice; upgrade path = normalize intro/outro to film params once +
    # stream-copy concat-demuxer if this pass gets too slow on long films.
    parts: List[Path] = []
    if _exists(intro):
        parts.append(Path(intro))
        intro_seconds = probe_duration(intro)
    parts.append(work)
    if _exists(outro):
        parts.append(Path(outro))

    if len(parts) > 1:
        parts = [_ensure_audio(p, work_dir) for p in parts]
        out = work_dir / "final_polished.mp4"
        cmd = build_concat_cmd([str(p) for p in parts], str(out))
        total = sum(probe_duration(str(p)) for p in parts)
        logger.info("Concatenating intro/outro", extra={"parts": len(parts), "intro_s": round(intro_seconds, 2)})
        _run(cmd, out, "intro/outro concat", _timeout_for(total))
        work = out

    # 2) ONE final audio pass over the concatenated (or bare-film) timeline:
    # music+ducking+loudnorm if a bed is configured, else a loudnorm-only
    # master pass if there's any audio at all, else skip (no audio, no music).
    # Probe AFTER concat — duration/has-audio must reflect the full timeline.
    if _exists(music):
        film_dur = probe_duration(str(work))
        out = work_dir / "film_music.mp4"
        cmd = build_music_mix_cmd(
            str(work), music, str(out), film_dur,
            settings.BG_MUSIC_VOLUME, settings.BG_MUSIC_FADEOUT_SECONDS,
            _has_audio_stream(str(work)),
        )
        logger.info("Mixing background music bed", extra={"volume": settings.BG_MUSIC_VOLUME})
        _run(cmd, out, "music mix", _timeout_for(film_dur))
        work = out
    elif _has_audio_stream(str(work)):
        film_dur = probe_duration(str(work))
        out = work_dir / "film_loudnorm.mp4"
        cmd = build_loudnorm_cmd(str(work), str(out))
        logger.info("Applying loudness normalization master pass")
        _run(cmd, out, "loudnorm", _timeout_for(film_dur))
        work = out

    # Replace the original output in place so final_output_path is unchanged.
    if work != film_path:
        os.replace(str(work), str(film_path))
    return film_path, round(intro_seconds, 3)
