"""Final-cut polish for the compositor: background-music bed + intro/outro concat.

Runs once at the end of /assemble, after the film MP4 exists. All three pieces
are optional and controlled by env (INTRO_VIDEO_PATH / OUTRO_VIDEO_PATH /
BG_MUSIC_PATH). With all unset, finalize_film is a no-op and the output is
byte-for-byte the rendered film.

Ordering (spec MUS-005): music is mixed into the FILM audio first, THEN the
intro/outro (which carry their own sound) are concatenated around it — so the
branding clips stay pristine and only the explainer gets the music bed.

The ffmpeg arg-builders are pure (no IO) so they unit-test on the host without
ffmpeg; finalize_film() wraps them with ffprobe + subprocess.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

from shared.config import settings
from shared.log import get_logger

from .duration_prober import probe_duration, AssemblyError

logger = get_logger(__name__)

_W, _H, _FPS, _AR = 1920, 1080, 30, 48000


def build_music_mix_cmd(
    film: str, music: str, out: str, film_duration: float,
    volume: float, fadeout: float, film_has_audio: bool,
) -> List[str]:
    """ffmpeg command to mix a looping, low-volume music bed under the film.

    Music loops to cover the film, is trimmed to film length (-shortest), and
    fades out over the last `fadeout` seconds. Video is stream-copied (no
    re-encode). When the film has no audio (all TTS failed) the music becomes
    the sole track over the film's silence.
    """
    fade_start = max(0.0, film_duration - fadeout)
    bg = f"[1:a]volume={volume},afade=t=out:st={fade_start:.3f}:d={fadeout:.3f}[bg]"
    if film_has_audio:
        # amix duration=first ends with the film's own audio length; -shortest
        # then trims the (infinitely looped) music to the film's video length.
        flt = f"{bg};[0:a][bg]amix=inputs=2:duration=first:dropout_transition=0[a]"
    else:
        flt = bg  # no film audio to mix into — the bed IS the track
    a_label = "[a]" if film_has_audio else "[bg]"
    return [
        "ffmpeg", "-y", "-i", film, "-stream_loop", "-1", "-i", music,
        "-filter_complex", flt,
        "-map", "0:v", "-map", a_label,
        "-c:v", "copy", "-c:a", "aac", "-shortest",
        "-movflags", "+faststart", out,
    ]


def build_concat_cmd(parts: List[str], out: str) -> Optional[List[str]]:
    """ffmpeg concat-FILTER command joining `parts` in order into one MP4.

    Re-encodes (not the stream-copy concat demuxer) because intro/outro are
    authored externally and won't match the film's codec/timebase/SAR. Every
    input is normalized to 1920x1080 / 30fps / yuv420p / 48k stereo so the seam
    is glitch-free. Caller MUST guarantee every part has an audio stream
    (see ensure_audio) — the graph maps [i:a] for each input.
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
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-movflags", "+faststart", out,
    ]
    return cmd


def _has_audio_stream(path: str) -> bool:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=index", "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=60,
        )
        return bool(r.stdout.strip())
    except Exception:
        return True


def _run(cmd: List[str], out: Path, label: str, timeout_s: int) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
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
    # Re-encode concat is ~real-time-ish on veryfast; give 3x + slack, capped.
    return int(min(settings.COMPOSITOR_CHUNK_TIMEOUT_MAX_SECONDS, max(300, duration_s * 3)))


def finalize_film(film_path: Path, work_dir: Path) -> Tuple[Path, float]:
    """Apply music bed + intro/outro concat in place. Returns (film_path, intro_seconds).

    film_path is mutated in place (the result replaces it) so the /video URL and
    downstream path stay stable. intro_seconds is 0.0 when no intro is set — the
    frontend offsets transcript timestamps by it (TRN-005).
    """
    intro = settings.INTRO_VIDEO_PATH.strip()
    outro = settings.OUTRO_VIDEO_PATH.strip()
    music = settings.BG_MUSIC_PATH.strip()
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

    # 1) music bed under the film audio (video stream-copied, fast)
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

    # 2) concat intro + film + outro (re-encode, normalize, synth silence)
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

    # Replace the original output in place so final_output_path is unchanged.
    if work != film_path:
        os.replace(str(work), str(film_path))
    return film_path, round(intro_seconds, 3)
