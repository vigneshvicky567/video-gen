# HyperFrames Authoring Rules

Authoritative emission rules for standalone HyperFrames scene HTML. Every rule traces to `hyperframes/` or `gsap/` skill files.

## Required HTML skeleton

Standalone composition: `data-composition-id` div sits directly in `<body>` — NOT inside `<template>` (SKILL.md L168).

```html
<div id="composition"
     data-composition-id="scene-{scene_id}"
     data-start="0" data-duration="{duration}"
     data-width="1920" data-height="1080">
  <video id="el-1" data-start="0" data-duration="10" data-track-index="0" src="..." muted playsinline crossorigin="anonymous"></video>
  <img   id="el-2" data-start="5" data-duration="4"  data-track-index="1" src="..." crossorigin="anonymous"/>
  <audio id="el-3" data-start="0" data-duration="30" data-track-index="2" src="..." crossorigin="anonymous"></audio>
  <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
  <script>
    window.__timelines = window.__timelines || {};
    const tl = gsap.timeline({ paused: true });
    // tweens...
    window.__timelines["scene-{scene_id}"] = tl; // MUST equal data-composition-id
  </script>
</div>
```

## Required data-attributes

**Root composition div**: `data-composition-id`, `data-start="0"`, `data-duration` (s; takes precedence over GSAP length), `data-width`, `data-height` (1920x1080 or 1080x1920) — SKILL.md L150–158.

**Every clip**: `id` (unique), `data-start` (seconds OR clip-id ref `"el-1"`/`"intro + 2"`), `data-track-index` (integer; same-track clips can't overlap; does NOT control z-order — use CSS `z-index`) — SKILL.md L138–147.

**Required for img/div/composition clips**: `data-duration`. Video/audio default to media duration.

**Optional**: `data-media-start`, `data-volume` (0–1), `data-composition-src`, `data-variable-values`.

**Forbidden attrs**: `data-layer` (use `data-track-index`), `data-end` (use `data-duration`) — SKILL.md L312.

## GSAP timeline registration

```js
window.__timelines = window.__timelines || {};
const tl = gsap.timeline({ paused: true });
// tweens via tl.from / tl.to / tl.set with explicit time positions
window.__timelines["scene-{scene_id}"] = tl;
```

- Timeline MUST be `paused: true` — the player owns playback and seeks deterministically. Never call `tl.play()` for render-critical motion.
- Build SYNCHRONOUSLY — no `async`/`await`/`setTimeout`/`Promise`. Capture engine reads `window.__timelines` synchronously after page load (SKILL.md L305).
- Framework auto-nests sub-timelines; do NOT manually `master.add(child)` (SKILL.md L291).
- Duration comes from `data-duration`, not GSAP timeline length (SKILL.md L292).
- Never `repeat: -1` (SKILL.md L303). Compute finite repeats from duration.
- Registry key MUST equal the root's `data-composition-id` (gsap/SKILL.md L21).

## Visibility checklist (don't render blank)

- **Explicit `background-color` on `#composition` and on each `.scene` div.** Required for shader compositions; safe everywhere (transitions.md L106).
- **Never `opacity: 0` on a clip element directly.** Framework forces `opacity: 1` on any element with `data-start`/`data-duration` while active — your CSS is silently overwritten. Wrap in a no-data-attr div and animate the wrapper (patterns.md L96–98).
- **Never combine CSS `opacity: 0` with `gsap.from(..., { opacity: 0 })` on the same element.** `from()` animates FROM the given value TO the current CSS value — if CSS is already 0 the element animates 0→0 and stays invisible forever. Pick ONE: either CSS starts hidden and you use `gsap.to(..., { opacity: 1 })` / `tl.set` reveals, or CSS holds the final visible state and `gsap.from()` provides the hidden start. Default to the `from()` style.
- **Fonts**: write `font-family` in CSS — compiler embeds supported fonts automatically. No `@font-face` for built-ins. For custom fonts: user provides `.woff2` in `fonts/` and you add local `@font-face`; warn if missing. No async font-loading APIs (SKILL.md L362–366).
- **Don't `gsap.set()` clip elements from later scenes** — they're not in the DOM at page load. Use `tl.set(selector, vars, timePos)` inside the timeline at/after the clip's `data-start` (SKILL.md L318).
- **No `<br>` in body content** — natural wrap + forced break = double break. Use `max-width`. Exception: deliberate one-word-per-line display titles (SKILL.md L319).
- **No full-screen linear gradients on dark backgrounds** — H.264 banding. Use radial or solid + localized glow (SKILL.md L355).
- **Position content via padding, not `position: absolute; top: Npx`** on content containers — they overflow when content exceeds remaining space. Reserve `position: absolute` for decoratives only (SKILL.md L73).
- **No `position: fixed`** for clip elements.

## Animation patterns

Animate FROM offscreen/invisible TO the CSS final position. Final layout lives in CSS; tweens describe the journey.

```js
tl.from(".title", { y: 60, opacity: 0, duration: 0.6, ease: "power3.out" }, 0.3); // fade+rise
tl.from(".item",  { y: 30, opacity: 0, duration: 0.5, ease: "power2.out", stagger: 0.12 }, 0.4); // stagger
tl.from(".logo",  { scale: 0.8, opacity: 0, duration: 0.4, ease: "back.out(1.7)" }, 0.5); // slide+scale
```

Guardrails: offset first animation 0.1–0.3s (not t=0); vary eases (≥3 different per scene); don't repeat an entrance pattern within a scene; only animate visual props (`opacity`, `x`, `y`, `scale`, `rotation`, `color`, `backgroundColor`, `borderRadius`, transforms) — SKILL.md L299, L352–357.

## Captions / lower-third pattern

Landscape: bottom 80–120px, centered. Portrait: ~600–700px from bottom. Container is full-width absolute; do NOT use `left:50%; transform:translateX(-50%)` (clips at edges). One group visible at a time. `overflow: visible` (NOT hidden — clips emphasis-word scaling/glow). Every group needs a hard kill at `group.end`:

```js
tl.to(g, { opacity: 0, scale: 0.95, duration: 0.12, ease: "power2.in" }, group.end - 0.12);
tl.set(g, { opacity: 0, visibility: "hidden" }, group.end); // deterministic kill
```

Dynamic copy: `window.__hyperframes.fitTextFontSize(text, { maxWidth, fontFamily, fontWeight })`. Group sizes: 2–3 high-energy / 3–5 conversational / 4–6 calm (captions.md L68–101).

## Composition caption safe-zone — bottom 160px is RESERVED

The master composition overlays narration captions across the bottom 160px of the 1920×1080 frame (y ≥ 920px). Scene content MUST stay out of that band:

- NEVER absolutely position readable content with `bottom` < 160px (e.g. `bottom: 40px`) or `top` ≥ 920px.
- The `.scene-content` container MUST use `padding: 80px 120px 160px` so flowed content cannot reach the band.
- Full-bleed backgrounds and decorative glows MAY cross the band; text, diagrams, labels, charts, and legends MUST NOT.
- Do NOT author your own narration lower-third — the composition owns captions. (A scene-local emphasis caption is fine ONLY if it sits above the band.)

## Forbidden / will-break patterns

(SKILL.md L297–319 unless noted.)

- No `Math.random()`/`Date.now()`/time-based logic — seeded PRNG only (L297).
- No animating `visibility`/`display`; no `video.play()`/`audio.play()` calls (L299).
- Never animate the same property on the same element from multiple timelines (L301).
- No `repeat: -1` on any timeline/tween — breaks capture engine (L303; gsap/SKILL.md L234).
- No async timeline construction (L305).
- Never forget `window.__timelines` registration (L309).
- Never use video for audio — muted+playsinline video + separate `<audio>` (L310).
- Never nest video inside a timed div — use a non-timed wrapper (L311).
- No `data-layer`/`data-end` — use `data-track-index`/`data-duration` (L312).
- Never animate video element dimensions — animate a wrapper div (L313).
- No play/pause/seek on media — framework owns playback (L314).
- No top-level container without `data-composition-id` (L315).
- No `gsap.set()` on clip elements from later scenes (L318).
- No `<br>` in content text (L319).
- No readable content in the bottom 160px (caption safe-zone — see section above).
- No exit animations except on the final scene — transition IS the exit; outgoing scene fully visible at transition start (L327; transitions.md L11–12).
- Shader compositions: no `transparent` in gradients (use target color α=0); no gradient on <4px elements; no `var()` on capture-visible elements; no gradient opacity <0.15 (transitions.md L101–105).
- Don't animate layout props (`width`/`height`/`top`/`left`) when transforms suffice (gsap/SKILL.md L229).

## Self-contained scene contract

Each emitted scene HTML is a STANDALONE valid HyperFrames composition (loaded as iframe or inlined into a master).

- **Root id stays `composition`** (NOT `scene-N` — reserved for our scene-id-bearing wrappers). The root `<div>`'s `data-composition-id` value is `scene-{scene_id}`.
- **Standalone = NO `<template>`** — `data-composition-id` div sits directly in `<body>` (SKILL.md L168).
- **All assets via CDN**: GSAP from `https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js`. No relative paths to local files. `crossorigin="anonymous"` on external media (SKILL.md L364; gsap/SKILL.md L13).
- **Timeline key**: `window.__timelines["scene-{scene_id}"] = tl`, matching the root's `data-composition-id`.
- **Synchronous only**: no `fetch().then(...)` for data — inline JSON or sync XHR (gsap/references/effects.md L211–224).
- **Deterministic**: no randomness, no clocks; seeded PRNG if needed.

## Citations

| Rule | Source |
| --- | --- |
| Skeleton | hyperframes/patterns.md L137–191 |
| Standalone vs `<template>` | hyperframes/SKILL.md L168 |
| Required data-attrs | hyperframes/SKILL.md L138–158 |
| Paused timeline contract | gsap/SKILL.md L11–28; SKILL.md L289–305 |
| Wrapper-div opacity rule | hyperframes/patterns.md L96–98 |
| Padding > absolute for content | hyperframes/SKILL.md L73 |
| Animation guardrails | hyperframes/SKILL.md L352–357 |
| Entrance-only / no exits | hyperframes/SKILL.md L321–348 |
| Shader-safe CSS | transitions.md L97–107 |
| Captions position + kill | captions.md L68–101 |
| Fonts auto-embedded | hyperframes/SKILL.md L362–366 |
| Sync data load | gsap/references/effects.md L211–224 |
