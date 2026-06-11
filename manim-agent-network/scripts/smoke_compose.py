"""Smoke test: rebuild the f24799da composition with the new sub-composition
mounting and verify it with the HyperFrames CLI on the host.

Usage:  python scripts/smoke_compose.py [--render]

Copies the job's artifacts into workspace/temp/<SMOKE_JOB>/, rewrites the
container paths (/workspace/...) to host paths, runs compute_scene_timings +
compose_html, then prints the composition path for `hyperframes render`.
"""

import json
import shutil
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

JOB_PREFIX = "f24799da"
SMOKE_JOB = "smoke2-f24799da"

from shared.config import settings  # noqa: E402

settings.WORKSPACE_DIR = str(REPO / "workspace")

from services.compositor.app.duration_prober import compute_scene_timings  # noqa: E402
from services.compositor.app.llm_composer import compose_html  # noqa: E402
from services.compositor.app.html_validator import validate_composition  # noqa: E402


def main() -> None:
    workspace = Path(settings.WORKSPACE_DIR)
    src_dir = next((workspace / "temp").glob(f"{JOB_PREFIX}*"))
    smoke_dir = workspace / "temp" / SMOKE_JOB
    if smoke_dir.exists():
        shutil.rmtree(smoke_dir)
    shutil.copytree(src_dir, smoke_dir, ignore=shutil.ignore_patterns("__pycache__", "index.html"))

    db = sqlite3.connect(str(workspace / "jobs.db"))
    state = json.loads(
        db.execute(
            "select state_json from jobs where job_id like ?", (f"{JOB_PREFIX}%",)
        ).fetchone()[0]
    )

    def to_smoke(p: str) -> str:
        # /workspace/temp/<job>/... -> <workspace>/temp/<SMOKE_JOB>/...
        rel = p.split(f"{src_dir.name}/", 1)[1]
        return str(smoke_dir / rel)

    render_paths = {int(k): to_smoke(v) for k, v in state["render_paths"].items()}
    audio_paths = {int(k): to_smoke(v) for k, v in state["audio_paths"].items()}
    scene_plans = state["script"]["scenes"]

    timings = compute_scene_timings(render_paths, audio_paths, scene_plans)
    for t in timings:
        print(f"scene {t.scene_id:>2}  start={t.start_time_seconds:>7.2f}  "
              f"video={t.actual_video_duration_seconds:>6.2f}  audio={t.actual_audio_duration_seconds:>6.2f}")

    html_path = compose_html(
        script_title=state["script"].get("title", "Smoke"),
        scene_timings=timings,
        image_paths={},
        job_id=SMOKE_JOB,
        scene_plans=scene_plans,
    )
    validate_composition(html_path)
    print(f"\ncomposition OK: {html_path}")


if __name__ == "__main__":
    main()

