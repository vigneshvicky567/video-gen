"""Before/after check: does passing duration make manim code fill the narration?

Generates real manim code (NVIDIA qwen coder) for a 24s scene with the OLD
prompt (no duration) and the NEW prompt (duration + pacing), then estimates each
script's wall-clock from run_time + self.wait beats. Expectation: NEW lands near
24s; OLD races through in ~single digits.
"""
import asyncio
import importlib
import importlib.util
import json
import os
import re
import sys

from dotenv import load_dotenv

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(REPO, ".env"))
sys.path.insert(0, REPO)
CG = os.path.join(REPO, "services", "code-generator")
sys.path.insert(0, CG)


def _load_cg():
    if "cg_app" not in sys.modules:
        app_dir = os.path.join(CG, "app")
        spec = importlib.util.spec_from_file_location(
            "cg_app", os.path.join(app_dir, "__init__.py"),
            submodule_search_locations=[app_dir],
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules["cg_app"] = mod
        spec.loader.exec_module(mod)
    return importlib.import_module("cg_app.main")


def _estimate_seconds(code: str) -> float:
    rts = [float(x) for x in re.findall(r"run_time\s*=\s*([0-9.]+)", code)]
    n_play = len(re.findall(r"self\.play\(", code))
    plays_total = sum(rts) + max(0, n_play - len(rts)) * 1.0  # bare play default 1s
    total = plays_total
    for w in re.findall(r"self\.wait\(\s*([0-9.]*)\s*\)", code):
        total += float(w) if w.strip() else 1.0
    return round(total, 1)


def _extract_code(text: str) -> str:
    try:
        return json.loads(text)["python_code"]
    except Exception:
        pass
    m = re.search(r'"python_code"\s*:\s*"(.*)"\s*}', text, re.DOTALL)
    if m:
        return m.group(1).encode().decode("unicode_escape")
    m = re.search(r"```python\s*(.*?)```", text, re.DOTALL)
    return m.group(1) if m else text


class _Scene:
    scene_id = 3
    title = "Dijkstra relaxation"
    narration_text = (
        "Dijkstra's algorithm grows a shortest-path tree one vertex at a time. "
        "We start at the source with distance zero and every other vertex at infinity. "
        "At each step we pick the unvisited vertex with the smallest tentative distance, "
        "lock it in, and relax each of its outgoing edges, lowering a neighbor's distance "
        "whenever a shorter path is found. We repeat until every vertex is visited."
    )
    visual_description = (
        "A weighted directed graph of five nodes. Highlight the current node, then animate "
        "each edge relaxation updating the neighbor distance labels, step by step."
    )
    estimated_duration_seconds = 24
    content_type = "manim"


async def _gen(cg, system, prompt):
    resp = await cg.client.chat.completions.acreate(
        model=cg.settings.CODE_GENERATOR_MODEL,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": prompt}],
        temperature=cg._sampling_temperature(0.2),
        top_p=cg._sampling_top_p(),
        max_tokens=cg.settings.CODE_GENERATOR_MAX_TOKENS,
    )
    return _extract_code(resp.choices[0].message.content)


def _old_prompt(scene):
    # The pre-fix user prompt: no duration, no pacing.
    return f"""Create a Manim CE scene per the system rules.

SCENE DETAILS:
Scene #:    {scene.scene_id}
Narration:  {scene.narration_text}
Visual:     {scene.visual_description}

Class name MUST be exactly `Scene{scene.scene_id}` (subclass of `Scene`).
No on-screen title text (the HyperFrames layer adds the scene title).
First line of `construct()`: `config.background_color = WHITE`.

Return ONLY: {{"python_code": "..."}}"""


async def main():
    cg = _load_cg()
    scene = _Scene()
    target = scene.estimated_duration_seconds

    print(f"target narration = {target}s\n")
    new_code = await _gen(cg, cg._MANIM_SYSTEM, cg._build_manim_prompt(scene))
    new_est = _estimate_seconds(new_code)
    print(f"NEW prompt (duration+pacing): est ~{new_est}s  "
          f"plays={len(re.findall(r'self.play', new_code))} waits={len(re.findall(r'self.wait', new_code))}")

    old_code = await _gen(cg, cg._MANIM_SYSTEM, _old_prompt(scene))
    old_est = _estimate_seconds(old_code)
    print(f"OLD prompt (no duration):     est ~{old_est}s  "
          f"plays={len(re.findall(r'self.play', old_code))} waits={len(re.findall(r'self.wait', old_code))}")

    print(f"\nNEW within +/-30% of {target}s? {abs(new_est-target) <= 0.3*target}")
    print(f"NEW closer to target than OLD? {abs(new_est-target) < abs(old_est-target)}")


if __name__ == "__main__":
    asyncio.run(main())
