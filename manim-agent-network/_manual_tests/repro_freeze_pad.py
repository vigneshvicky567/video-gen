"""Empirical repro + fix-verification for the manim-vanishing bug.

Builds the EXACT production composition (compose_html) with a 2s solid-red
"manim" clip whose narration audio is 6s, renders it with the real hyperframes
CLI, then samples a frame at t=4.0s (past the clip, inside the slot):

  red  center pixel -> video frame held for the whole slot   (good / fixed)
  white center pixel -> <video> vanished to the #fff bg       (bug reproduced)

Runs twice: unpadded (reproduce) and freeze-padded (verify fix).
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

CLI = os.environ.get(
    "HYPERFRAMES_CLI",
    r"C:\Users\vicky\AppData\Roaming\npm\node_modules\hyperframes\dist\cli.js",
)
WORK = Path(REPO) / "_manual_tests" / "_render_work"


def _run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=600, **kw)


def _mk_media(comp_dir):
    comp_dir.mkdir(parents=True, exist_ok=True)
    red = comp_dir / "clip.mp4"
    aud = comp_dir / "narration.mp3"
    r1 = _run(["ffmpeg", "-y", "-f", "lavfi",
               "-i", "color=c=red:size=1920x1080:duration=2:rate=30",
               "-pix_fmt", "yuv420p", str(red)])
    assert red.exists(), r1.stderr[-500:]
    r2 = _run(["ffmpeg", "-y", "-f", "lavfi",
               "-i", "sine=frequency=440:duration=6", str(aud)])
    assert aud.exists(), r2.stderr[-500:]
    return red, aud


def _center_rgb(video, t):
    """Mean RGB of the center pixel at time t (1x1 scaled rawvideo)."""
    r = subprocess.run(
        ["ffmpeg", "-ss", str(t), "-i", str(video), "-frames:v", "1",
         "-vf", "scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, timeout=120,
    )
    b = r.stdout
    if len(b) < 3:
        return None
    return (b[0], b[1], b[2])


def _classify(rgb):
    if rgb is None:
        return "NO-FRAME"
    r, g, b = rgb
    if r > 180 and g < 80 and b < 80:
        return "RED (held)"
    if r > 200 and g > 200 and b > 200:
        return "WHITE (vanished)"
    return f"OTHER{rgb}"


def scenario(pad):
    from shared.config import settings
    settings.WORKSPACE_DIR = str(WORK)
    from services.compositor.app.llm_composer import compose_html
    from services.compositor.app.duration_prober import freeze_pad_renders
    from shared.schemas.common import SceneTimingRecord

    job_id = "padded" if pad else "unpadded"
    comp_dir = WORK / "temp" / job_id
    if comp_dir.exists():
        shutil.rmtree(comp_dir)
    red, aud = _mk_media(comp_dir)

    timings = [SceneTimingRecord(
        scene_id=1, render_path=str(red), audio_path=str(aud),
        actual_video_duration_seconds=2.0, actual_audio_duration_seconds=6.0,
        start_time_seconds=0.0,
    )]
    if pad:
        timings = freeze_pad_renders(timings, comp_dir / "padded")
        print(f"  [pad] render_path now: {Path(timings[0].render_path).name}, "
              f"video_dur={timings[0].actual_video_duration_seconds}")

    scene_plans = [{"scene_id": 1, "content_type": "manim",
                    "narration_text": "This is a test of the freeze pad behavior over six seconds.",
                    "estimated_duration_seconds": 6}]
    html_path = compose_html("Repro", timings, {}, job_id, scene_plans)
    index = comp_dir / "index.html"
    Path(html_path).replace(index)

    out = comp_dir / "out.mp4"
    print(f"  rendering {job_id} ...")
    r = _run(["node", CLI, "render", "--output", str(out),
              "--fps", "30", "--quality", "draft", "--workers", "1"],
             cwd=str(comp_dir))
    if not out.exists():
        print(f"  RENDER FAILED rc={r.returncode}\n  STDERR: {r.stderr[-800:]}")
        return None

    dur = subprocess.run(["ffprobe", "-v", "quiet", "-show_entries",
                          "format=duration", "-of", "csv=p=0", str(out)],
                         capture_output=True, text=True).stdout.strip()
    f1 = _classify(_center_rgb(out, 1.0))
    f4 = _classify(_center_rgb(out, 4.0))
    print(f"  out duration = {dur}s")
    print(f"  t=1.0s center = {f1}   (expect RED both)")
    print(f"  t=4.0s center = {f4}   ({'expect RED (fix)' if pad else 'BUG if WHITE'})")
    return f4


if __name__ == "__main__":
    WORK.mkdir(parents=True, exist_ok=True)
    print("=== UNPADDED (reproduce bug) ===")
    unp = scenario(pad=False)
    print("\n=== PADDED (verify fix) ===")
    pad = scenario(pad=True)
    print("\n" + "=" * 50)
    print(f"unpadded t=4s: {unp}")
    print(f"padded   t=4s: {pad}")
    ok = (pad == "RED (held)")
    print("FIX VERIFIED" if ok else "FIX NOT CONFIRMED")
    sys.exit(0 if ok else 1)
