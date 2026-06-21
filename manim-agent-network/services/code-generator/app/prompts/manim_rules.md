# Manim CE Authoring Rules

Authoritative rules for Manim Community Edition. Every rule traces to the `manimce-best-practices` skill (citations at end).

## Required imports

```python
from manim import *
```

Exposes every animation, color, direction, and rate function below as a bare name. NEVER use `from manimlib import *` (ManimGL — incompatible).

## Scene class skeleton

Exactly one `Scene` subclass per file with `construct(self)`.

```python
from manim import *
config.background_color = WHITE  # MODULE level — see rule below

class Scene{N}(Scene):
    def construct(self):
        circle = Circle(color=BLUE_E)
        self.play(Create(circle))
        self.wait(1)
```

## Background / visibility

- Canvas is WHITE. `config.background_color = WHITE` works ONLY at MODULE level
  (directly under the import, OUTSIDE the class). Setting it inside
  `construct()` is a silent no-op — the camera is created before `construct()`
  runs, and the video renders on the default BLACK background, making all your
  dark-colored content invisible. NEVER write `config.background_color` or
  `self.camera.background_color` inside `construct()`.
- ALL strokes, fills, text MUST be dark: `BLACK`, `BLUE_E`, `RED_E`, `GREEN_E`, `GREY_E`, `MAROON_E`, `PURPLE_E`.
- NEVER use `WHITE` for any visible element — invisible.
- Neutrals: prefer `BLACK`, `GREY_D`, `GREY_E`.

## Allowed Animation classes (whitelist)

Creation: `Create`, `Write`, `DrawBorderThenFill`, `FadeIn`, `GrowFromCenter`, `GrowFromPoint`, `GrowFromEdge`, `SpinInFromNothing`, `AddTextLetterByLetter`.
Removal: `FadeOut`, `Uncreate`, `ShrinkToCenter`, `RemoveTextLetterByLetter`.
Transform: `Transform`, `ReplacementTransform`, `TransformFromCopy`, `TransformMatchingShapes`, `TransformMatchingTex`, `MoveToTarget`.
Movement / emphasis: `Rotate`, `MoveAlongPath`, `Circumscribe`, `Indicate`, `Flash`, `TypeWithCursor`, `Blink`.
Grouping: `AnimationGroup`, `LaggedStart`, `Succession`.

Use `Create`, NEVER `ShowCreation` (removed in CE).

## Allowed `rate_func` names (whitelist)

ALWAYS write the qualified form `rate_functions.<name>` — in Manim CE 0.20 the
`ease_*` family is NOT exported by `from manim import *`; bare
`rate_func=ease_out_sine` crashes with `NameError: name 'ease_out_sine' is not
defined` (verified in this pipeline's render container). Only the classics
(`linear`, `smooth`, `there_and_back`) happen to be exported bare — qualify
everything anyway for one consistent rule.

- Core: `rate_functions.linear`, `rate_functions.smooth`, `rate_functions.rush_into`, `rate_functions.rush_from`, `rate_functions.there_and_back`, `rate_functions.there_and_back_with_pause`, `rate_functions.double_smooth`, `rate_functions.lingering`.
- Ease-in: `rate_functions.ease_in_sine`, `rate_functions.ease_in_quad`, `rate_functions.ease_in_cubic`, `rate_functions.ease_in_expo`, `rate_functions.ease_in_circ`, `rate_functions.ease_in_back`.
- Ease-out: `rate_functions.ease_out_sine`, `rate_functions.ease_out_quad`, `rate_functions.ease_out_cubic`, `rate_functions.ease_out_expo`, `rate_functions.ease_out_circ`, `rate_functions.ease_out_back`, `rate_functions.ease_out_bounce`.
- Ease-in-out: `rate_functions.ease_in_out_sine`, `rate_functions.ease_in_out_quad`, `rate_functions.ease_in_out_cubic`, `rate_functions.ease_in_out_expo`, `rate_functions.ease_in_out_circ`, `rate_functions.ease_in_out_back`.

`rate_functions.ease_out` does NOT exist — pick a concrete shape like
`rate_functions.ease_out_sine`.

## Allowed color constants (whitelist)

From colors.md L14-44.

- Primaries: `RED`, `GREEN`, `BLUE`, `YELLOW`, `ORANGE`, `PINK`, `PURPLE`, `WHITE`, `BLACK`, `GREY` (alias `GRAY`).
- Variants `_A` (lightest) - `_E` (darkest) for: `BLUE`, `RED`, `GREEN`, `GREY`, `TEAL`, `GOLD`, `MAROON`, `PURPLE`. e.g. `BLUE_A BLUE_B BLUE_C BLUE_D BLUE_E`.
- Named: `TEAL`, `GOLD`, `MAROON`.
- Pure: `PURE_RED`, `PURE_GREEN`, `PURE_BLUE`.
- Greys: `LIGHT_GREY`, `DARK_GREY`, `LIGHTER_GREY`, `DARKER_GREY`.
- Browns: `LIGHT_BROWN`, `DARK_BROWN`.
- Hex strings allowed: `"#FF5733"` (colors.md L62-66).

Forbidden: `DARK_RED`, `DARK_BLUE`, `DARK_GREEN`, `LIGHT_GRAY`, `DARK_GRAY` — not in colors.md. Map: dark red -> `RED_E` or `MAROON_E`; dark blue -> `BLUE_E`; light gray -> `GREY_A` or `LIGHT_GREY`; dark gray -> `GREY_E` or `DARK_GREY` (note GREY spelling).

## Text & LaTeX patterns

```python
title = Text("Hello", font_size=48, color=BLACK)         # text.md L25-34
eq    = MathTex(r"E = mc^2", font_size=64, color=BLACK)  # latex.md L189
mixed = Tex(r"Area is $A = \pi r^2$", color=BLACK)       # latex.md L128
```

- Always raw strings for LaTeX. `MathTex` for math, `Tex` for text+math, `Text` for plain.
- Default `font_size=48`. Titles 56-72; body 32-48; captions 24.
- Color math parts: `eq.set_color_by_tex("x", RED_E)` or `eq[0][2].set_color(BLUE_E)`.
- `AddTextLetterByLetter` works only on `Text`, not `MathTex`.

### Equation overflow & overlap — HARD rules

- After creating ANY `MathTex`/`Tex` longer than a few symbols, fit it BEFORE revealing:
  ```python
  eq = MathTex(r"z = w_1 x_1 + w_2 x_2 + w_3 x_3 + b", color=BLACK)
  if eq.width > 10:
      eq.scale_to_fit_width(10)
  eq.move_to(ORIGIN)          # position AFTER fitting
  self.play(Write(eq))
  ```
- One equation per screen region. NEVER `Write` a new equation onto a region that
  still holds an old one — `ReplacementTransform(old, new)` or `FadeOut(old)` first.
  Overlapping `MathTex` renders as garbled fragments.
- Never split one logical equation across multiple `MathTex` objects positioned by
  hand — one string, one object, let LaTeX do the layout.
- Labels attached to moving objects must use `always_redraw` or move WITH the object
  in the same `self.play`, or they detach and overlap other content.

### Contrast contract — every visible mobject

The canvas is WHITE (the pipeline injects `config.background_color = WHITE` if you
forget it — never rely on a dark background existing).

- Every `color=` you write must be readable on WHITE: `BLACK`, `GREY_E`, `BLUE_E`,
  `RED_E`, `GREEN_E`, `MAROON_E`, `PURPLE_E`, or dark hex (`"#1a1a2e"`, `"#e63946"`).
- FORBIDDEN on white: `WHITE`, `YELLOW`, `GREY_A`, `GREY_B`, `GOLD_A`, `TEAL_A`,
  any `_A`/`_B` tint as text/stroke color.
- Diagram nodes: dark stroke + light fill (`fill_color="#e8f4fd", fill_opacity=1,
  color=BLUE_E`) so arrows and labels stay legible on top.

## Frame size — HARD limit

The visible frame is **14.22 units wide × 8 units tall** (x ∈ [-7.1, 7.1], y ∈ [-4, 4]). Anything outside is CROPPED in the final video. The safe area is **x ∈ [-6, 6], y ∈ [-2.8, 3.5]**.

- The bottom band **y < -2.8** (lowest ~160px of the frame) is RESERVED for narration captions overlaid by the compositor. Placing mobjects there means captions will cover them — keep all content above y = -2.8.
- `.to_edge(DOWN, ...)` and `.to_corner(DL/DR, ...)` MUST use `buff >= 1.2` (the default 0.5 lands inside the caption band; `buff=1.2` puts the mobject's bottom at y ≈ -2.8).
- After final layout, the whole scene's bounding box must satisfy `group.get_bottom()[1] >= -2.8`.
- NEVER create a primitive larger than the frame: `Square(side_length=N)` with N>6 will not fit vertically; keep N ≤ 5 and prefer ≤ 3.
- NEVER `.shift()` an object past the safe area. A 5-unit square shifted `DOWN*2.5` reaches y=-5 → cropped. Compute extent before shifting.
- After building, the WHOLE scene's bounding box must fit. If unsure, scale it down (see below).

## Layout patterns — build SMALL, arrange, fit-as-animation, clear

Canonical pattern. The fit step MUST be played or applied before the reveal — NEVER left as dead trailing code:

```python
# 1. Build at modest size
a = Circle(radius=0.8, color=BLUE_E)
b = Square(side_length=1.2, color=RED_E)
c = Triangle(color=GREEN_E)

# 2. Group + arrange (never hand-place with magic .shift offsets)
parts = VGroup(a, b, c).arrange(RIGHT, buff=0.6)        # grouping.md L74-90

# 3. FIT BEFORE REVEALING — scale the group down if it exceeds the safe width,
#    THEN position, THEN animate. The scale happens before self.play(Create(...)).
if parts.width > 12:
    parts.scale_to_fit_width(12)                         # applied to layout, not dead code
parts.move_to(ORIGIN)                                    # or .to_edge(UP, buff=0.5)

# 4. Reveal the already-fitted group
self.play(Create(parts), run_time=2)
self.wait(1)
```

**FORBIDDEN (the #1 real bug):** emitting `group.scale_to_fit_width(12)` / `group.move_to(ORIGIN)` as the LAST statements of `construct`, AFTER everything was already drawn. That is a no-op with zero visual effect — the overflow stays. Fit happens BEFORE the reveal, or is itself played: `self.play(parts.animate.scale_to_fit_width(12))`.

- Direction constants: `UP DOWN LEFT RIGHT UL UR DL DR ORIGIN` (positioning.md L21-33).
- `to_edge(..., buff=0.5)`, `to_corner(UL|UR|DL|DR, buff=0.5)` for screen-relative placement.
- `arrange_in_grid(rows=R, cols=C, buff=0.5)` for grids.
- Escape hatch for unavoidably-large content: subclass `MovingCameraScene` and `self.camera.auto_zoom(group, margin=1)` to fit the camera to the content.

## Text collision — HARD rules (the #2 real bug)

### Title + subtitle vertical stacking

NEVER position a subtitle by absolute coordinate — it will land on the title.
Always derive the subtitle's position FROM the title using `next_to`:

```python
# FORBIDDEN — overlap guaranteed
title    = Text("Conservation of Energy", font_size=56, color=BLACK).to_edge(UP)
subtitle = Text("Total Energy = Constant", font_size=36, color=RED_E)
subtitle.move_to(UP * 2.8)   # hardcoded y crashes into the title

# REQUIRED — subtitle always clears the title
title    = Text("Conservation of Energy", font_size=56, color=BLACK)
subtitle = Text("Total Energy = Constant", font_size=36, color=RED_E)
header   = VGroup(title, subtitle).arrange(DOWN, buff=0.2)
header.to_edge(UP, buff=0.3)
```

### Multi-label layout under diagrams

When a diagram has N labeled objects (bars, nodes, columns):
NEVER call `label.next_to(obj, DOWN)` per object — labels overlap when spacing < label width.

```python
# FORBIDDEN — individual next_to causes overlap
label1.next_to(bar1, DOWN)
label2.next_to(bar2, DOWN)
label3.next_to(bar3, DOWN)

# REQUIRED — group + arrange uses real bounding boxes, zero overlap
labels = VGroup(
    Text("Pressure Energy", font_size=24, color=BLACK),
    Text("Kinetic Energy",  font_size=24, color=BLACK),
    Text("Potential Energy", font_size=24, color=BLACK),
)
labels.arrange(RIGHT, buff=0.3)
if labels.width > 12:
    labels.scale_to_fit_width(12)
labels.next_to(bars_group, DOWN, buff=0.4)
```

`VGroup.arrange()` measures actual rendered widths and spaces accordingly —
it is the ONLY collision-free approach for sibling labels.

## Clear before introducing — NEVER accumulate (the #1 clutter bug)

Mobjects do NOT auto-clear between `self.play` calls. Drawing new content on top of old produces overlapping, unreadable composites. Match every introduction with a removal:

```python
self.play(Create(step1)); self.wait(1)
self.play(FadeOut(step1))                  # clear BEFORE next concept
self.play(Write(step2)); self.wait(1)
self.play(ReplacementTransform(step2, step3))   # morph, leaving no stale object
```

- "If you `Create`, later `Uncreate`/`FadeOut`. If you `FadeIn`, later `FadeOut`." (creation-animations.md L158)
- Use `ReplacementTransform(a, b)` (NOT `Transform`) so `a` is removed from the scene — `Transform` leaves a stale invisible object.
- Before a new full-screen concept: `self.play(FadeOut(*self.mobjects))` or fade the specific prior group.
- NEVER call `Create()` / `.animate` on a mobject that is already on screen or was never `add`-ed — causes a snap/redraw glitch.

## Motion that lands — no self-undoing slides

`there_and_back` returns the object to its START — it does NOT "slide in and stay." For an entrance that lands, animate FROM an offscreen copy TO the final position with a one-way ease:

```python
obj.shift(LEFT * 8)                                  # start offscreen-left
self.play(obj.animate.shift(RIGHT * 8), rate_func=rate_functions.ease_out_sine)   # lands center
```

Use `there_and_back` only for a deliberate round-trip (e.g. a nudge/bounce that should return).

## Transform / `.animate` patterns

```python
self.play(square.animate.shift(RIGHT))                  # animations.md L18
self.play(circle.animate.scale(2))
self.play(text.animate.set_color(RED_E))
self.play(square.animate.shift(RIGHT).rotate(PI/4))     # chain
self.play(ReplacementTransform(square, circle))         # transform-animations.md L41
```

`rate_func` and `run_time` belong on `self.play(...)`, NOT inside `.animate(...)`:

```python
# CORRECT
self.play(square.animate.shift(RIGHT), rate_func=rate_functions.smooth, run_time=2)
# WRONG
self.play(square.animate(rate_func=rate_functions.smooth).shift(RIGHT))
```

For rotation prefer `Rotate(mob, angle)` or `mob.rotate(angle)`. Do not pass `axis=` through `.animate.rotate(...)`.

## Timing

```python
self.play(Create(circle), run_time=2)
self.play(circle.animate.shift(RIGHT), run_time=0.5, rate_func=rate_functions.ease_out_sine)
self.wait()       # 1 sec default
self.wait(2)      # explicit seconds
```

Keep `run_time` 0.5 - 3 seconds (timing.md L199).

## Forbidden / will-break APIs

| Forbidden | Replacement / Reason |
|---|---|
| `ShowCreation(...)` | Removed in CE — use `Create(...)` (animations.md L84). |
| `ShowCreationThenFadeOut(...)` | `self.play(Create(o)); self.play(FadeOut(o))`. |
| `SVGMobject("file.svg")` | No SVG assets bundled — will fail. |
| `SVGCircle`, `VGraph` | Not in CE public API. |
| `there_and_back_once` | Not a rate_func — use `there_and_back` (timing.md L62). |
| `Circle(arc_length=...)`, `Arc(arc_length=...)` | No such kwarg — use `radius=` / `angle=`. |
| `line_intersection(p1, p2)` | Use `(p1 + p2) / 2` for midpoint. |
| `MoveAlongPath(Dot(curve, ...), curve)` | First `dot = Dot(curve.get_start())`, then `MoveAlongPath(dot, curve)`. |
| `.set_fill_by_checkerboard()` | Not public. |
| `obj.animate.rotate(angle, axis=...)` | Drop `.animate` — call `obj.rotate(angle, axis=axis)`. |
| `Rotating(mob, radians=...)` | `radians=`/`axis=` are rejected by `Animation.__init__` in current CE — use `self.play(Rotate(mob, angle=PI/2))` for a fixed turn, or `mob.rotate(PI/2)` for an instant one. |
| `ThreeDScene` / `ThreeDAxes` / `Surface` (3D) unless explicitly required | 3D renders are slow and fragile. Prefer a 2D `Axes` projection. If 3D is unavoidable: `class SceneN(ThreeDScene)`, `self.set_camera_orientation(phi=70*DEGREES, theta=-45*DEGREES)`, keep ≤1 `Surface` at `resolution=(16,16)`, no `Rotating`. |
| `DARK_RED`, `DARK_BLUE`, `DARK_GREEN`, `LIGHT_GRAY`, `DARK_GRAY` | Not defined — use `_E` variants, `LIGHT_GREY` / `DARK_GREY`, or hex. |
| `rate_functions.ease_out` | Does not exist — use `rate_functions.ease_out_sine`, `rate_functions.ease_out_quad`, `rate_functions.smooth`, or `rate_functions.linear`. |
| `rate_func=ease_out_sine` (bare) | `NameError` in CE 0.20 — always qualify: `rate_func=rate_functions.ease_out_sine`. |
| `rate_func=` inside `.animate(...)` | Pass to `self.play(...)` instead (animations.md L43-49). |
| `from manimlib import *` | Wrong framework — use `from manim import *`. |
| `Code(code=..., tab_width=..., background=..., language=..., font=..., style=..., font_size=..., insert_line_no=..., stroke_width=...)` | **Manim CE 0.20+ broke this API** — `Code()` no longer accepts `code=` kwarg. Use `Text("...", font_size=24)` or `Paragraph("line1", "line2")` for plain-text blocks. `Code()` is only for displaying source-code files. |

## Class-name contract

Validator runs `manim render -qh <file> Scene{N}` where `{N}` is the scene id from the caller. Class name MUST be exactly `Scene{N}` (e.g. `Scene1`). Do NOT rename, prefix, or suffix. Exactly one Scene subclass per file.

## Citations

| Rule | Source |
|---|---|
| `from manim import *` | SKILL.md L78; scenes.md L17 |
| Scene/construct skeleton | scenes.md L19-24 |
| `Create` not `ShowCreation` | animations.md L84; creation-animations.md L13-23 |
| `rate_func` whitelist | timing.md L46-101 |
| `ease_out_sine` valid | timing.md L86 |
| Color constants | colors.md L14-44 |
| Hex colors | colors.md L62-66 |
| `Text` / `MathTex` API | text.md L25-34; latex.md L36-58 |
| `VGroup.arrange` / `to_edge` | grouping.md L74-90; positioning.md L137-147 |
| `.animate` syntax | animations.md L13-28 |
| `run_time` / `rate_func` on `play` | animations.md L36-49 |
| `self.wait()` | scenes.md L74-81 |
| `ReplacementTransform` | transform-animations.md L33-45 |
