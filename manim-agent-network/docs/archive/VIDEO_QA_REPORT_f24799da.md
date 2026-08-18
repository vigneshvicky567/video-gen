# Video QA Report — Job `f24799da` ("How Neural Networks Learn")

**Artifact:** `workspace/outputs/f24799da-9d72-480a-a5df-510074bf488a_final.mp4`
**Topic:** "How neural networks learn"
**Job status (DB):** `completed` — created `2026-06-08 14:25:54`, completed `2026-06-08 15:07:28` (~42 min wall)
**Video:** 1920×1080, h264, 03:02 (182.3 s), 6.6 MB
**Reviewed:** 2026-06-09 via `/watch` (80 frames @ 0.439 fps, frames-only — no audio transcript)
**Verdict:** Ships, but **2 of 10 scenes are missing** and **2–3 scenes render blank/near-blank**. ~40–50% of runtime is degraded.

---

## 1. How this was reviewed

The `/watch` skill was run against the local file. Setup was bootstrapped first (Windows host had no media tooling):

```powershell
# ffmpeg/ffprobe + yt-dlp were missing — installed once
winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
pip install --user yt-dlp
# session PATH (winget needs a new shell otherwise)
$env:PATH = "C:\Users\vicky\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.1-full_build\bin;" + $env:PATH
```

```powershell
# frames-only (no Whisper key configured; user opted out of external transcription)
python "<watch-skill>\scripts\watch.py" "<...>_final.mp4" --no-whisper
```

80 JPEG frames were extracted to a temp dir and each was read as an image. There is **no transcript** in this report — narration content below comes from the job's `script.scenes[].narration_text` in `workspace/jobs.db`, not from audio.

---

## 2. Ground truth (from `workspace/jobs.db`)

The pipeline emits two scene render types per scene (decided upstream by the code-generator; the validator routes by content sniff in `services/validator/app/main.py:detect_content_type`):

- **HTML / HyperFrames** scenes → `scene_N.html`, rendered by the **compositor** service.
- **Manim** scenes → `scene_N.py` → `render_scene_N/.../SceneN.mp4`.

Final state for this job:

| Scene | Type  | Rendered? | Retries | Narration (first line) |
|------:|-------|-----------|--------:|------------------------|
| 1  | HTML  | ✅ | 0 | "How do neural networks actually learn? It's not magic…" |
| 2  | HTML  | ✅ | 0 | "Imagine you're trying to predict house prices…" |
| 3  | Manim | ❌ **DROPPED** | **5 (cap)** | "Here's a simple neural network. It has an input layer…" |
| 4  | Manim | ✅ | 1 | "To make a prediction, the network does a forward pass…" |
| 5  | Manim | ✅ | 0 | "But how wrong was that guess? …the loss function…" |
| 6  | Manim | ❌ **DROPPED** | **5 (cap)** | "Now we need to improve. Imagine you're blindfolded on a hilly terrain…" |
| 7  | Manim | ✅ | 0 | "But wait—there are thousands of weights… Backpropagation…" |
| 8  | Manim | ✅ | 2 | "Here's the actual update: each weight gets adjusted by its gradient…" |
| 9  | Manim | ✅ | 4 | "Put it all together, and you have the training loop…" |
| 10 | HTML  | ✅ | 0 | "Neural networks learn by making predictions, measuring mistakes…" |

`render_paths` = scenes `{1,2,4,5,7,8,9,10}`. `error_logs` keys = `{3,6}`. `retry_counts` = `{4:1, 8:2, 9:4, 3:5, 6:5}`.

**Scenes 3 and 6 were dropped** by graceful degradation after exhausting the 5-retry cap. The job still completed with 8/10 scenes — degradation working as designed (`services/orchestrator/app/core/graph.py:validation_router`). But the narrative loses the network-structure introduction (3) and the gradient-descent "blindfolded on a hill" intuition (6).

---

## 3. Visual timeline (observed frames vs. computed scene slots)

Scene slot timing recomputed from `compositor/app/duration_prober.py` logic (HTML scenes use `estimated_duration_seconds`; Manim probed via ffprobe; slot = `max(video, audio)`):

| Scene | Type  | Start | Slot (s) | On-screen (observed) | Status |
|------:|-------|------:|---------:|----------------------|--------|
| 1  | HTML  | 0:00 | 12.0 | Near-black; checklist-style text + **garbled overlapping corner text** | ⚠️ entrance anims never ran |
| 2  | HTML  | 0:12 | 17.3 | **Blank white**, only the narration caption box | ❌ invisible |
| 4  | Manim | 0:29 | 31.0 | Forward pass: `x₁ x₂` → neuron → output; layer network, orange node | ✅ (LaTeX partly garbled `z=γ·`) |
| 5  | Manim | 1:00 | 18.4 | Loss: scatter + regression line + dashed residuals + bar chart (3.34/2.50/1.67) | ✅ good |
| 7  | Manim | 1:18 | 28.0 | Backprop: 3-neuron chain, `∂z/∂w`, animated gradient arrows | ✅ good |
| 8  | Manim | 1:46 | 27.5 | Gradient descent: parabola + `α`, ball descends to minimum | ✅ best scene |
| 9  | Manim | 2:14 | 32.0 | Training-loop cycle (**near-invisible, dark-on-dark**) + text reveals ("Test Prediction: ✓") | ⚠️ low contrast |
| 10 | HTML  | 2:46 | 16.1 | **Blank white**, only the narration caption box | ❌ invisible |

Two HTML scenes (2, 10) are blank white. Scene 1 (HTML) shows static text only with its entrance animation never having played, plus garbled corner artifacts. Scenes 3 and 6 do not appear at all.

> Note: the on-screen text at 0:00–0:11 matches the *outro* checklist markup (`Predict / Measure Error / Adjust & Repeat`, present only in `scene_10.html`), not scene 1's title-card markup ("How Neural Networks Learn"). HTML-scene visibility and ordering are not being driven correctly — see Finding 2.

---

## 4. Findings

### F1 — Scenes 3 & 6 dropped: Manim API drift not caught pre-render  · **HIGH**

Both scenes failed render 5× with `AttributeError`s, then were dropped. The exact errors (from `error_logs` in the DB):

**Scene 3** — `scene_3.py:8`:
```
config.background
AttributeError: 'ManimConfig' object has no attribute 'background'
```
The correct attribute is `config.background_color`. The generated code used a non-existent attribute.

**Scene 6** — `scene_6.py:27` (`move_to_contour_view`):
```python
self.play(self.camera.animate.set_phi(0), self.camera.animate.set_theta(...))
AttributeError: 'ThreeDCamera' object has no attribute 'animate'
```
`ThreeDCamera` is not animatable via `.animate`. 3D camera moves require `self.move_camera(phi=..., theta=...)` (or `self.begin_ambient_camera_rotation()`).

**Why it's expensive:** these are *static, detectable* API-misuse patterns, but they are **not** in the validator's AST deny-list. `services/validator/app/main.py` only flags a small deprecated set:

```python
# services/validator/app/main.py:185
deprecated = {"SVGMobject", "SVGCircle", "ShowCreation", "ShowCreationThenFadeOut", "VGraph", "there_and_back_once"}
# :200
if key == "rate_functions.ease_out":
    issues.append("Use 'rate_functions.ease_out_sine' instead of 'rate_functions.ease_out'")
```

`config.background` and `ThreeDCamera(...).animate` pass AST preflight and only fail at actual `manim render` time. Each scene therefore burned all 5 retries × full render attempts (the retry cap, `graph.py:71` / `:142` / `:193`), i.e. up to 10 doomed renders for this job, contributing to the ~42-minute wall time.

### F2 — HTML scenes render blank/static: per-scene GSAP timelines are orphaned  · **HIGH**

The compositor inlines each HyperFrames scene into one master document (`compositor/app/llm_composer.py:compose_html` + `_inline_hyperframes_scene`), then renders via the HyperFrames CLI. Three independent defects combine to blank the HTML scenes:

**(a) The master timeline is empty.** `compose_html` registers `window.__timelines["main"]` but adds **no tweens** to it:
```python
# services/compositor/app/llm_composer.py:303-308
<script src="https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.2/gsap.min.js"></script>
<script>
  const tl = gsap.timeline({ paused: true });   // ← never gets .to()/.from()/.add()
  window.__timelines = window.__timelines || {};
  window.__timelines["main"] = tl;
</script>
```

**(b) Each scene's real animation lives in a *separate* paused timeline that nothing drives.** Every generated scene registers its own timeline and the inliner preserves the key (`_inline_hyperframes_scene` rewrites the id/key but never grafts the child into `main`):
```javascript
// scene_2.html:193,201-212  (representative)
const tl = gsap.timeline({ paused: true });
window.__timelines["scene-2"] = tl;
gsap.set(".title, .data-table, .question-mark, .dashed-border, .animated-text", { opacity: 0 }); // hide all
tl.to(".title",      { autoAlpha: 1, ... }, 0.3)   // entrances live only on the orphan timeline
  .to(".data-table", { autoAlpha: 1, ... }, 0.6)
  ...
```
The HyperFrames renderer seeks `window.__timelines["main"]`; `["scene-2"]`/`["scene-10"]`/`["scene-1"]` are never played or seeked. Scene 2 hides everything at load (`gsap.set(opacity:0)`) and never reveals it. Scene 10 uses `tl.from(... opacity:0)` (immediate-render hides on creation) and never animates back. Scene 1 uses `tl.from(autoAlpha:0)` for its title/subtitle — same result, entrances never play.

**(c) The scene-host background is white, so an invisible scene paints white.** When the inlined content is invisible, the host div's own background shows through:
```python
# services/compositor/app/llm_composer.py:190-195
<div class="clip scene-visual scene-host" id="host-scene-{scene_id}"
  data-start="{start}" data-duration="{slot_duration}"
  data-track-index="{track}"
  style="position:absolute;left:0;top:0;width:1920px;height:1080px;z-index:{track};background:#ffffff;overflow:hidden;">
```
Each scene HTML defines its *own* dark canvas (`#0e1116`, `#0a1628`, `#0a0f1c`), but those live on `#composition-scene-N` *inside* the host. With the inner content/canvas not rendering, the `#ffffff` host wins → the blank **white** frames observed for scenes 2 and 10. The Manim `<video>` host also uses `background:#ffffff` (`:229`), which is why a dropped/short video would flash white too.

**Net:** HTML scenes never animate. Any scene that gates its content behind its (orphaned) timeline is invisible; the white host is what the viewer sees. Visibility/ordering across HTML scenes is also wrong (outro markup observed at t=0).

### F3 — Manim scene 9 (training loop) is near-invisible: dark-on-dark  · **MEDIUM**

The "training loop" cycle diagram (Data → NN → Loss → W) at 2:14–2:46 renders with labels in a dark grey on Manim's near-black background — almost zero contrast, effectively unreadable. The render *succeeded* (it's in `render_paths`), so this is a styling defect in the generated code, not a crash. Scene 9 also needed 4 retries.

### F4 — Garbled / partial LaTeX and text reveals  · **LOW**

- Scene 4 forward-pass math shows fragments like `z=γ·`, a stray `w₃`, and a loose `2` — `MathTex` content overlapping or cut off.
- Scene 1 has overlapping garbled text in the corner.
- Scene 9 text reveals ("Neural N…", "Test Pr…") were caught mid-animation as partial strings.

Cosmetic, but reads as broken.

### F5 — Blank scenes still carry narration audio + captions  · **MEDIUM (UX)**

Scenes 2 and 10 are in `audio_paths`, so their voiceover plays over a blank white frame, with the lower-third caption (`llm_composer.py:235-244`) burned in. The compositor tolerates HTML having no probed duration (`duration_prober.py:34` returns `0.0` for `.html`, then falls back to `estimated_duration_seconds`), so the blank slot is held for the full narration length (12–17 s each). A failed visual is not detected — it is timed and shipped.

### F6 — Two assembler implementations; the ffmpeg one is dead in this deployment  · **INFO**

- `services/assembler/app/main.py` — ffmpeg `concat` assembler (Manim-only path).
- `services/compositor/app/main.py` — HyperFrames HTML assembler (the one actually used).

`docker-compose.yml:26` wires the orchestrator to the compositor:
```yaml
- ASSEMBLER_URL=http://compositor:8005
```
…while `shared/config.py:49` defaults to `http://assembler:8005`. The deployed path is the **compositor**; the ffmpeg `assembler/` service is effectively unused for this job (confirmed by the presence of `index.html` + inlined HTML in the job temp dir). Worth either removing or documenting to avoid future confusion.

---

## 5. Proposed fixes (not yet applied)

### Fix F1 — extend the validator AST deny-list (cheap, high value)

Catch these two patterns (and the class of them) before render, in `services/validator/app/main.py:_preflight_ast_checks`:

```python
# in visit_Attribute (services/validator/app/main.py ~:197)
def visit_Attribute(self, node: ast.Attribute):
    if isinstance(node.value, ast.Name):
        key = f"{node.value.id}.{node.attr}"
        if key == "rate_functions.ease_out":
            issues.append("Use 'rate_functions.ease_out_sine' instead of 'rate_functions.ease_out'")
        if key == "config.background":
            issues.append("Use 'config.background_color', not 'config.background'")
        if node.value.id in _FORBIDDEN_MODULES:
            issues.append(f"Security: forbidden module attribute access '{key}'")
    # .animate on a 3D camera: self.camera.animate... is invalid for ThreeDCamera
    if node.attr == "animate":
        # crude but effective: flag `.camera.animate`
        if isinstance(node.value, ast.Attribute) and node.value.attr == "camera":
            issues.append("ThreeDCamera has no '.animate'; use self.move_camera(phi=..., theta=...)")
    self.generic_visit(node)
```

This converts two render-time `AttributeError`s (5 wasted renders each) into a first-attempt validation failure, which feeds the error back to the code-generator for a targeted retry — and likely saves both scenes instead of dropping them.

### Fix F2 — drive the per-scene timelines (the real blank-scene fix)

The master script must advance every inlined scene timeline, not just `main`. Minimal change in `llm_composer.py:compose_html` master `<script>`:

```javascript
<script src="https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.2/gsap.min.js"></script>
<script>
  window.__timelines = window.__timelines || {};
  const main = gsap.timeline({ paused: true });

  // Graft every scene sub-timeline onto main at its host's data-start.
  document.querySelectorAll('.scene-host').forEach(host => {
    const id = host.id.replace('host-', '');          // "scene-2"
    const start = parseFloat(host.dataset.start) || 0;
    const sub = window.__timelines[id];
    if (sub) { sub.paused(false); main.add(sub, start); }
  });

  window.__timelines["main"] = main;
</script>
```

This requires the inlined scene scripts to run *before* the master script (they already do — `_inline_hyperframes_scene` appends head `<script>`s after the body, and `compose_html` emits the master script last). Verify ordering after the change.

Also harden the host so a non-rendering scene degrades to dark, not white:

```python
# services/compositor/app/llm_composer.py:193  (and the <video> host at :229)
# background:#ffffff  →  background:#0a0f1c   (or transparent)
```

### Fix F2b — fail loudly on a blank scene (defense in depth)

A scene that renders to a single flat colour should fail composition, not ship. After the HyperFrames render in `compositor/app/main.py`, sample a few frames and reject near-uniform ones (ties into the broader "measurement before enforcement" plan for the HTML stack):

```python
# after render, before returning AssemblerResponse (compositor/app/main.py ~:106)
# probe N frames; if any scene-slot's midpoint frame has < ~0.5% pixel variance, raise AssemblyError
```

(Implementation deferred — needs a frame-variance probe helper.)

### Fix F3/F4 — generation-side guardrails

These are code-generator prompt/quality issues, not orchestration bugs:
- Enforce a minimum contrast ratio for text vs. the scene background (scene 9).
- Constrain `MathTex` width / use `.scale_to_fit_width` so equations don't overflow or overlap (scene 4).

---

## 6. Summary

| Severity | Finding | Fix locus |
|----------|---------|-----------|
| HIGH | F1: scenes 3 & 6 dropped on undetected Manim API drift (`config.background`, `ThreeDCamera.animate`) | `validator/app/main.py` AST deny-list |
| HIGH | F2: HTML scenes blank — orphaned per-scene GSAP timelines + empty master timeline + white host bg | `compositor/app/llm_composer.py` |
| MEDIUM | F3: scene 9 training-loop diagram dark-on-dark | code-generator styling |
| LOW | F4: garbled/partial LaTeX & text reveals (scenes 1, 4, 9) | code-generator |
| MEDIUM | F5: blank scenes still carry narration audio + captions | `compositor` (detect blank, see F2b) |
| INFO | F6: dead ffmpeg `assembler/` service; compositor is the live assembler | cleanup / docs |

**Bottom line:** Graceful degradation correctly prevented a hard failure, but the safety net is masking two distinct upstream defects — (1) the validator can't see common Manim API drift so good scenes get dropped, and (2) the HyperFrames composition never animates, so HTML scenes ship blank. Both are deterministic and code-local. Fixing F1 (validator) and F2 (composer timeline grafting + host background) would recover an estimated 4 of the 5 degraded/missing scenes.

---

## Appendix — diagnostic commands

```bash
# job ground truth
python - <<'PY'
import sqlite3, json
db=sqlite3.connect("workspace/jobs.db"); db.row_factory=sqlite3.Row
st=json.loads(db.execute("select state_json from jobs where job_id like 'f24799da%'").fetchone()[0])
print("render_paths:", sorted(st["render_paths"], key=int))
print("retry_counts:", st["retry_counts"])
print("error_logs keys:", list(st["error_logs"]))
PY

# per-scene timeline (probe audio, accumulate slots)  → §3 table
# scene render-type split
ls workspace/temp/f24799da-9d72-480a-a5df-510074bf488a/   # scene_*.html vs scene_*.py + render_scene_*
```

Implicated source files:
- `services/orchestrator/app/core/graph.py` — `validation_router` (drop logic), retry caps
- `services/validator/app/main.py` — AST preflight deny-list (F1)
- `services/compositor/app/llm_composer.py` — `compose_html`, `_inline_hyperframes_scene` (F2)
- `services/compositor/app/duration_prober.py` — HTML duration fallback (F5)
- `services/compositor/app/main.py` — HyperFrames render entry (F2b)
- `services/assembler/app/main.py` — dead ffmpeg assembler (F6)

Generated scene HTML (this job): `workspace/temp/f24799da-.../scene_{1,2,10}.html`
