"""Tests for the compositor final-cut ffmpeg arg-builders
(services/compositor/app/postprocess.py). Pure functions — no ffmpeg needed."""

import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from services.compositor.app.postprocess import (
    build_music_mix_cmd, build_concat_cmd, build_loudnorm_cmd,
)


def test_music_mix_with_film_audio():
    cmd = build_music_mix_cmd(
        "film.mp4", "music.mp3", "out.mp4", film_duration=30.0,
        volume=0.12, fadeout=2.0, film_has_audio=True,
    )
    s = " ".join(cmd)
    assert "-stream_loop -1" in s          # music loops to cover the film
    assert "volume=0.12" in s
    assert "afade=t=out:st=28.000:d=2.000" in s  # fade starts at dur-fadeout
    assert "amix=inputs=2" in s            # narration + bed mixed
    assert "-shortest" in s                # trim looped music to film length
    assert cmd[cmd.index("-map") + 1] == "0:v"
    assert "normalize=0" in s              # don't let amix halve every input
    assert "sidechaincompress" in s        # duck the bed under narration
    assert "loudnorm=I=-14" in s           # master to platform loudness target


def test_music_mix_without_film_audio():
    # No narration track: the bed becomes the sole audio, no amix.
    cmd = build_music_mix_cmd(
        "film.mp4", "music.mp3", "out.mp4", film_duration=10.0,
        volume=0.2, fadeout=2.0, film_has_audio=False,
    )
    s = " ".join(cmd)
    assert "amix" not in s
    assert "volume=0.2" in s
    assert "loudnorm=I=-14" in s            # still mastered to platform target
    assert "[a]" in cmd                     # maps the mastered output, not [bed]
    assert cmd[cmd.index("-map") + 1] == "0:v"
    assert cmd[cmd.index("-map", cmd.index("-map") + 1) + 1] == "[a]"


def test_loudnorm_only():
    cmd = build_loudnorm_cmd("film.mp4", "out.mp4")
    s = " ".join(cmd)
    assert "loudnorm=I=-14:TP=-1.5:LRA=11" in s
    assert "-c:v copy" in s
    assert cmd[cmd.index("-map") + 1] == "0:v"
    assert cmd[cmd.index("-map", cmd.index("-map") + 1) + 1] == "[a]"


def test_concat_two_inputs():
    cmd = build_concat_cmd(["intro.mp4", "film.mp4"], "out.mp4")
    s = " ".join(cmd)
    assert s.count("-i ") == 2 or cmd.count("-i") == 2
    assert "concat=n=2:v=1:a=1[v][a]" in s
    assert "scale=1920:1080" in s
    assert "fps=30" in s
    assert "[0:v]" in s and "[1:v]" in s
    assert "[0:a]" in s and "[1:a]" in s
    assert "-crf 18" in s                   # final encode quality bump


def test_concat_three_inputs_intro_film_outro():
    cmd = build_concat_cmd(["intro.mp4", "film.mp4", "outro.mp4"], "out.mp4")
    s = " ".join(cmd)
    assert "concat=n=3:v=1:a=1[v][a]" in s
    assert "[2:v]" in s and "[2:a]" in s
    assert "-crf 18" in s


def test_concat_single_part_is_noop():
    # Nothing to join — caller should skip the concat pass entirely.
    assert build_concat_cmd(["film.mp4"], "out.mp4") is None
    assert build_concat_cmd([], "out.mp4") is None


if __name__ == "__main__":
    test_music_mix_with_film_audio()
    test_music_mix_without_film_audio()
    test_loudnorm_only()
    test_concat_two_inputs()
    test_concat_three_inputs_intro_film_outro()
    test_concat_single_part_is_noop()
    print("all postprocess arg-builder tests passed")
