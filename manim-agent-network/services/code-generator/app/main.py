from fastapi import FastAPI
from shared.schemas.requests import CodeGeneratorRequest
from shared.schemas.responses import CodeGeneratorResponse
from shared.config import settings, require_keys
from shared.llm_client import get_llm_client
from shared.log import get_logger, set_log_context, timed_block, log_llm_call, log_file, make_request_logging_middleware
import os
import sys
import ast
from .sanitizer import sanitize_manim_code, check_manim_security
from .pitfalls import pitfalls_block
from .prompts import load as load_rules
from langsmith import traceable
import re
import json
import time
import base64


def _sampling_temperature(path_default: float) -> float:
    """CODE_GENERATOR_TEMPERATURE env override, else the per-path default.

    Reasoning models (nvidia/nemotron-3-*) need temperature 1.0; coder models
    work best at low temperature. Env-driven so a model swap in .env can carry
    its sampling params without a code change.
    """
    raw = settings.CODE_GENERATOR_TEMPERATURE.strip()
    return float(raw) if raw else path_default


def _sampling_top_p() -> float | None:
    raw = settings.CODE_GENERATOR_TOP_P.strip()
    return float(raw) if raw else None


def _run_sanitizer_self_test() -> None:
    """Fail-fast on stale image: confirm sanitizer rewrites ShowCreation."""
    sample = (
        "from manim import *\n"
        "class S(Scene):\n"
        "    def construct(self):\n"
        "        self.play(ShowCreation(Circle()))\n"
    )
    out, _ = sanitize_manim_code(sample, scene_id=0)
    if "ShowCreation" in out or "Create" not in out:
        # Logger may not exist yet at this import-time; print + exit.
        print("STALE IMAGE: sanitizer self-test failed (ShowCreation not rewritten)", file=sys.stderr)
        sys.exit(1)

app = FastAPI(title="Code Generator Service")
app.add_middleware(make_request_logging_middleware("code-generator"))
logger = get_logger(__name__)

_run_sanitizer_self_test()

client = get_llm_client()
logger.info("Code Generator ready", extra={"model": settings.CODE_GENERATOR_MODEL})
logger.info("Sanitizer self-test passed")


@app.on_event("startup")
async def _validate_config() -> None:
    # Fail at boot, not with a 401 inside the first generation mid-job.
    require_keys(any_of=("NVIDIA_API_KEY", "ANTHROPIC_API_KEY", "MISTRAL_API_KEY"))


# ── Mistral fallback (separate provider/quota) ────────────────────────────────
import asyncio

# Circuit breaker: after NIM fails, route code-gen straight to Mistral for a
# cooldown window so a 40-scene batch doesn't burn the per-scene NIM retry budget
# (~tens of seconds each) before failing over. Resets to trying NIM after cooldown.
# The Mistral call itself goes through the SHARED llm_client (routed by model id),
# so the fallback inherits retry/backoff/typed-errors/concurrency caps instead of
# the old raw one-shot httpx call that bypassed all of it.
_nim_down_until = 0.0
_NIM_COOLDOWN_S = 120
_breaker_lock = asyncio.Lock()  # check-and-set on _nim_down_until spans awaits


async def _llm_chat(messages, max_tokens, temperature, top_p=None, response_format=None):
    """Code-gen LLM call: NIM primary, Mistral fallback on any NIM failure (incl.
    429). A process circuit breaker skips NIM during a cooldown after it fails so
    the rest of a batch fails over fast instead of retrying a dead NIM per scene."""
    global _nim_down_until
    has_mistral = bool(settings.MISTRAL_API_KEY)
    async with _breaker_lock:
        nim_skipped = has_mistral and time.monotonic() < _nim_down_until
    if not nim_skipped:
        try:
            return await client.chat.completions.acreate(
                model=settings.CODE_GENERATOR_MODEL, messages=messages,
                temperature=temperature, top_p=top_p,
                max_tokens=max_tokens, response_format=response_format,
            )
        except Exception as e:
            if not has_mistral:
                raise
            async with _breaker_lock:
                _nim_down_until = time.monotonic() + _NIM_COOLDOWN_S
            logger.warning(f"NIM code-gen failed -> Mistral fallback (cooldown {_NIM_COOLDOWN_S}s)",
                           extra={"error": str(e)[:160], "mistral_model": settings.MISTRAL_MODEL})
    # Routed by model id to _MistralCompletions inside the shared client.
    return await client.chat.completions.acreate(
        model=settings.MISTRAL_MODEL, messages=messages,
        temperature=min(max(temperature or 0.3, 0.0), 1.0),  # Mistral caps temp at 1.0
        max_tokens=max_tokens, response_format=response_format,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Scene classification (fallback when script-writer doesn't set content_type)
# ─────────────────────────────────────────────────────────────────────────────
MANIM_KEYWORDS = [
    "equation", "formula", "graph", "plot", "curve", "axes", "matrix",
    "vector", "geometry", "proof", "derivative", "integral", "transform",
    "animate", "draw", "manim", "mathematical", "3d surface", "eigenvalue",
    # Visual verbs/structures that read better as a Manim diagram than an HF card.
    "flow", "diagram", "network", "cycle", "process", "compare",
    "timeline", "graph", "plot",
]

def classify_scene(narration: str, visual: str) -> str:
    """Heuristic fallback used ONLY when script-writer set no content_type.

    Threshold is 1 hit when the visual_description is non-trivial (the scene
    actually describes something to draw); otherwise require 2 so a stray
    keyword in prose narration alone doesn't force Manim. No LLM call."""
    combined = f"{narration} {visual}".lower()
    hits = sum(1 for kw in MANIM_KEYWORDS if kw in combined)
    visual_is_nontrivial = len((visual or "").strip()) >= 40
    threshold = 1 if visual_is_nontrivial else 2
    return "manim" if hits >= threshold else "hyperframes"


# ─────────────────────────────────────────────────────────────────────────────
# HyperFrames HTML generation via LLM
# ─────────────────────────────────────────────────────────────────────────────
# System prompt is the official HyperFrames skill rules + a thin task wrapper.
# Rule edits live in services/code-generator/app/prompts/hf_rules.md, not here.
_HF_SYSTEM = load_rules("hf_rules") + """

---

# Your Task

You are an expert HyperFrames HTML composer building educational-explainer scenes.
Output ONLY a complete <!DOCTYPE html> … </html> document — no markdown fences,
no commentary. Follow every rule above without exception. The composition
will be inlined into a master 1920x1080 canvas, so the rendered scene MUST
have a visible non-transparent background and visible foreground content.

Visual baseline (override with explicit user-supplied palette when given):
- Canvas: 1920×1080.
- LAYOUT: every scene's content lives in a `.scene-content` container sized
  `width:100%; height:100%; padding:80px 120px 160px; display:flex; flex-direction:column;
  gap:32px; box-sizing:border-box`. The bottom 160px is the composition caption
  band — keep content out of it. Position content with padding/flex — NEVER
  `position:absolute; top:Npx` on a content container (it overflows). Reserve
  `position:absolute` for decoratives only. Build the static end-state layout
  first, THEN add gsap.from() entrances.
- BACKGROUND: NOT flat pure white. Use a tinted near-neutral (e.g. #f4f1ea warm
  or #0e1116 dark) plus ONE depth layer (soft radial glow or subtle grain) and
  ONE accent hue used at full saturation on the focal element. Pure #ffffff/#000
  reads as "nothing loaded". Keep ONE palette across ALL scenes.
- TYPOGRAPHY (video scale, not web): headlines 64-110px, body 28-42px, labels
  18-24px. Pair a serif with a sans (NOT two sans). Extreme weight contrast
  (300 vs 900). Do NOT use Inter, Roboto, Poppins, Open Sans, Lato, Nunito —
  they are instant AI-design tells. Prefer system serif ("Georgia","Times New
  Roman",serif) paired with a system sans, or a bundled .woff2. Tabular-nums on
  stacked numbers. Let text wrap via max-width — never <br>.
- MOTION: stagger multi-element reveals (`stagger:{each:0.08, from:"center"}`),
  set one motion signature via `gsap.timeline({defaults:{ease:"power3.out",
  duration:0.6}})`, vary eases (≥3/scene), use autoAlpha not opacity. Entrance
  animations only — NO exit animations except the final scene.
- ⛔ VISIBILITY (the #1 render-killer — read carefully): NEVER set `opacity:0` or
  `visibility:hidden` in CSS on an element you then animate in with
  `gsap.from(el,{opacity:0})` / `gsap.from(el,{autoAlpha:0})`. `from()` tweens FROM
  your value TO the element's CURRENT (CSS) value — if CSS already pins it at 0 the
  tween is 0→0 and the element STAYS INVISIBLE FOR THE WHOLE SCENE (blank screen).
  Rule: elements revealed via `gsap.from(...)` MUST keep their natural visible CSS
  (no opacity/visibility hiding, neither in a `<style>` rule NOR an inline
  `style="opacity:0"` attribute) — `from()` supplies the hidden start itself and
  reveals to the real value. ONLY hide in CSS when you reveal with `gsap.to(el,
  {opacity:1})` instead. Never both. When unsure, use `gsap.from()` + visible CSS.
- CONTRAST: on-screen text must hit WCAG 4.5:1 against whatever is behind it.
- GSAP CDN (exact URL — the compositor dedupes it against the master doc):
  https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"""

# ── HyperFrames few-shot examples ─────────────────────────────────────────────
# The Manim path always had a worked example; the HF path had only rules — and
# LLMs lean on few-shot for layout/motion taste, so HF scenes converged on the
# templated "centered title + bullets + fade". Two distinct archetype examples,
# picked per scene, anchor the craft: layout archetype, .scene-content container,
# timeline registration, gsap.from() with VISIBLE CSS, staggers, varied eases.

_HF_FEW_SHOT_BIG_STAT = """<!DOCTYPE html>
<html>
<head>
<style>
  body { margin:0; background:#0e1116; }
  .scene-content { width:100%; height:100%; padding:80px 120px 160px;
    display:flex; flex-direction:column; justify-content:center; gap:32px;
    box-sizing:border-box; }
  .kicker { font:600 24px/1 "Helvetica Neue", Arial, sans-serif;
    letter-spacing:0.22em; text-transform:uppercase; color:#8b93a7; }
  .stat { font:900 220px/0.9 Georgia, serif; color:#f4f1ea;
    font-variant-numeric:tabular-nums; }
  .stat .unit { font-size:96px; color:#00d4ff; }
  .anchor { font:300 38px/1.4 "Helvetica Neue", Arial, sans-serif;
    color:#c9d1e3; max-width:980px; }
  .anchor em { font-style:normal; color:#00d4ff; }
</style>
</head>
<body>
<div id="composition" data-composition-id="scene-1" data-start="0" data-duration="9"
     data-width="1920" data-height="1080"
     style="position:relative;width:1920px;height:1080px;overflow:hidden;background:#0e1116;">
  <div class="scene-content">
    <div class="kicker">every single day</div>
    <div class="stat"><span id="count">0.0</span> <span class="unit">billion</span></div>
    <div class="anchor">searches — that's <em>40 questions</em> in the time it took to hear this sentence.</div>
  </div>
</div>
<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
<script>
  const tl = gsap.timeline({ paused: true, defaults: { ease: "power3.out", duration: 0.6 } });
  window.__timelines = window.__timelines || {};
  window.__timelines["scene-1"] = tl;
  tl.from(".kicker", { autoAlpha: 0, y: 24 }, 0.2)
    .from(".stat", { autoAlpha: 0, scale: 0.85, duration: 0.8, ease: "back.out(1.5)" }, 0.6);
  const counter = { v: 0 };
  tl.to(counter, { v: 8.5, duration: 1.2, ease: "power2.out", onUpdate: () => {
      document.getElementById("count").textContent = counter.v.toFixed(1);
    } }, 0.7)
    .from(".anchor", { autoAlpha: 0, y: 20, duration: 0.7, ease: "power2.out" }, 2.1);
</script>
</body>
</html>"""

_HF_FEW_SHOT_SPLIT_COMPARE = """<!DOCTYPE html>
<html>
<head>
<style>
  body { margin:0; background:#f4f1ea; }
  .scene-content { width:100%; height:100%; padding:80px 120px 160px;
    display:flex; flex-direction:column; gap:40px; box-sizing:border-box; }
  .headline { font:900 72px/1.1 Georgia, serif; color:#1a1a1a; max-width:1100px; }
  .panels { flex:1; display:flex; gap:48px; }
  .panel { flex:1; border-radius:12px; padding:48px; display:flex;
    flex-direction:column; gap:20px; }
  .panel.left  { background:#e9e4d8; }
  .panel.right { background:#1a1a1a; }
  .panel h3 { margin:0; font:600 26px/1 "Helvetica Neue", Arial, sans-serif;
    letter-spacing:0.14em; text-transform:uppercase; color:#7a7468; }
  .panel.right h3 { color:#9a948a; }
  .panel .figure { font:300 88px/1 Georgia, serif; color:#1a1a1a; }
  .panel.right .figure { color:#f4f1ea; }
  .panel .note { font:300 28px/1.45 "Helvetica Neue", Arial, sans-serif; color:#55504a; }
  .panel.right .note { color:#b5afa5; }
  .delta { align-self:center; font:900 40px/1 "Helvetica Neue", Arial, sans-serif;
    color:#e63946; }
</style>
</head>
<body>
<div id="composition" data-composition-id="scene-1" data-start="0" data-duration="10"
     data-width="1920" data-height="1080"
     style="position:relative;width:1920px;height:1080px;overflow:hidden;background:#f4f1ea;">
  <div class="scene-content">
    <div class="headline">Same journey. Two very different engines.</div>
    <div class="panels">
      <div class="panel left">
        <h3>Combustion</h3>
        <div class="figure">~30%</div>
        <div class="note">of the fuel's energy reaches the wheels — the rest leaves as heat.</div>
      </div>
      <div class="panel right">
        <h3>Electric</h3>
        <div class="figure">~90%</div>
        <div class="note">of the battery's energy reaches the wheels.</div>
      </div>
    </div>
    <div class="delta">3x the useful work from every stored joule</div>
  </div>
</div>
<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
<script>
  const tl = gsap.timeline({ paused: true, defaults: { ease: "power3.out", duration: 0.6 } });
  window.__timelines = window.__timelines || {};
  window.__timelines["scene-1"] = tl;
  tl.from(".headline", { autoAlpha: 0, y: 28 }, 0.2)
    .from(".panel.left",  { autoAlpha: 0, x: -80, duration: 0.7 }, 0.9)
    .from(".panel.right", { autoAlpha: 0, x: 80,  duration: 0.7 }, 1.05)
    .from(".panel .figure", { autoAlpha: 0, y: 16, stagger: 0.15, ease: "power2.out" }, 1.7)
    .from(".panel .note",   { autoAlpha: 0, y: 12, stagger: 0.12, ease: "power2.out" }, 2.1)
    .from(".delta", { autoAlpha: 0, scale: 0.9, duration: 0.5, ease: "back.out(1.6)" }, 3.0);
</script>
</body>
</html>"""


def _pick_hf_example(visual: str, scene_id: int) -> str:
    """Pick the few-shot whose archetype best matches this scene's shot spec;
    alternate by scene id otherwise so consecutive scenes see different craft."""
    v = (visual or "").lower()
    if any(k in v for k in ("big-stat", "big number", "count-up", "statistic")):
        return _HF_FEW_SHOT_BIG_STAT
    if any(k in v for k in ("split-compare", "compare", "comparison", "versus", " vs ", "before-after", "two panel")):
        return _HF_FEW_SHOT_SPLIT_COMPARE
    return _HF_FEW_SHOT_BIG_STAT if scene_id % 2 == 1 else _HF_FEW_SHOT_SPLIT_COMPARE


# ── Stock-image compositing (Option B) ────────────────────────────────────────
# Images are pre-fetched (image-fetcher service) and arrive as local file paths.
# The LLM references them ONLY via `__IMAGE_k__` placeholders; we inline each to a
# base64 data URI AFTER generation. Data URIs (not file paths) make the scene HTML
# self-contained, so it renders identically whether the validator renders it
# standalone or the compositor inlines it into the master doc — no file:// access,
# no path-rebasing when the scene file is copied into compositions/.
_IMG_INLINE_MAX_BYTES = 4 * 1024 * 1024  # skip absurd files; keeps HTML sane
_DATA_URI_RE = re.compile(r"data:image/[^;]+;base64,[A-Za-z0-9+/=]+")
_IMG_TOKEN_RE = re.compile(r"__IMAGE_\d+__")


def _sniff_image_mime(raw: bytes) -> str:
    """Return the image mime from magic bytes. Fetched stock images arrive with
    varied real formats (webp/gif/png), not just jpeg — a wrong mime on the data
    URI can make a browser refuse to decode it. Default jpeg only as last resort."""
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if raw[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    if raw[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return "image/jpeg"


def _img_data_uri(path: str) -> str:
    with open(path, "rb") as fh:
        raw = fh.read()
    if len(raw) > _IMG_INLINE_MAX_BYTES:
        raise ValueError(f"image too large to inline: {len(raw)} bytes")
    mime = _sniff_image_mime(raw)
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def _inline_images(html: str, image_paths) -> str:
    """Replace each `__IMAGE_k__` placeholder with a base64 data URI. Unmatched or
    unreadable placeholders are blanked so no broken src reaches the renderer —
    and every blanked token is LOGGED (a silently emptied src used to be the
    invisible reason a scene lost its imagery).

    The prompt tells the model every provided image MUST be used (index 0 is
    mandatory). The model sometimes ignores that, and the invented-token scrub
    below would then silently erase the imagery. So we verify each provided
    index actually appeared; a missing REQUIRED image (index 0) is warned about,
    and — when there's an obvious full-bleed <img> slot — index 0 is injected
    into it rather than lost."""
    inlined_indices: set[int] = set()
    if image_paths:
        for i, p in enumerate(image_paths):
            token = f"__IMAGE_{i}__"
            if token not in html:
                continue
            try:
                html = html.replace(token, _img_data_uri(p))
                inlined_indices.add(i)
            except Exception as e:
                logger.warning("Could not inline image — token blanked",
                               extra={"path": p, "token": token, "error": str(e)})
                html = html.replace(token, "")

    # A provided image the model never referenced would otherwise vanish silently.
    if image_paths:
        missing = [i for i in range(len(image_paths)) if i not in inlined_indices]
        if missing:
            logger.warning("Provided images not referenced by the scene",
                           extra={"missing_indices": missing,
                                  "provided": len(image_paths)})
        # Index 0 is mandatory per _image_guidance. If it never made it in, try a
        # sensible default injection (a full-bleed bg <img> as the first child of
        # the #composition wrapper); otherwise at least warn loudly.
        if 0 in missing:
            try:
                data_uri = _img_data_uri(image_paths[0])
            except Exception as e:
                data_uri = None
                logger.warning("Required image __IMAGE_0__ missing AND unreadable",
                               extra={"path": image_paths[0], "error": str(e)})
            if data_uri:
                bg_img = (f'<img src="{data_uri}" '
                          'style="position:absolute;inset:0;width:100%;height:100%;'
                          'object-fit:cover;z-index:0;">')
                comp_open = re.search(r"<div\b[^>]*id=[\"']composition[\"'][^>]*>", html, re.IGNORECASE)
                if comp_open:
                    at = comp_open.end()
                    html = html[:at] + bg_img + html[at:]
                    logger.warning("Required image __IMAGE_0__ was unused — injected as full-bleed background",
                                   extra={"path": image_paths[0]})
                else:
                    logger.warning("Required image __IMAGE_0__ unused and no #composition slot to inject into",
                                   extra={"path": image_paths[0]})

    # Drop any placeholder the model invented past the available image count.
    invented = sorted(set(_IMG_TOKEN_RE.findall(html)))
    if invented:
        logger.warning("Model referenced non-existent image tokens — blanked",
                       extra={"tokens": invented, "available": len(image_paths or [])})
    return _IMG_TOKEN_RE.sub("", html)


def _strip_data_uris(html: str) -> str:
    """Shrink inlined base64 back to numbered markers so retry prompts stay small.
    The same data URI always maps to the same token (deduped by content), so a
    placeholder used N times in the HTML (e.g. same bg image repeated) stays
    __IMAGE_0__ everywhere rather than becoming __IMAGE_0__, __IMAGE_1__, …"""
    _uri_to_token: dict = {}
    _counter = [0]
    def _replacer(m: re.Match) -> str:
        uri = m.group(0)
        if uri not in _uri_to_token:
            _uri_to_token[uri] = f"__IMAGE_{_counter[0]}__"
            _counter[0] += 1
        return _uri_to_token[uri]
    return _DATA_URI_RE.sub(_replacer, html)


def _image_guidance(n: int, duration: int) -> str:
    if n <= 0:
        return ""
    toks = ", ".join(f"__IMAGE_{i}__" for i in range(n))
    plural = "s" if n > 1 else ""
    return f"""

IMAGERY — {n} relevant photo{plural} available. Reference ONLY by these exact placeholders in src: {toks}. Never invent src values, never use http(s) URLs. You MUST use __IMAGE_0__. Do NOT skip it.

Choose the display style that best serves the scene's visual description:

**Option A — Full-bleed background** (atmosphere, environment, wide establishing shot):
  <img id="bg-photo" src="__IMAGE_0__" style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover;z-index:0;">
  Add a scrim: <div style="position:absolute;inset:0;z-index:1;background:linear-gradient(...)"> at 0.55–0.85 alpha so all text keeps WCAG 4.5:1. Text/decoratives sit above (z-index:2+). The `#composition` div keeps its opaque palette background-color (fallback). Optional Ken-Burns: tl.fromTo("#bg-photo", {{scale:1.0}}, {{scale:1.08, ease:"power1.inOut", duration:{duration}}}, 0).

**Option B — Framed inset** (specific subject, person, diagram, product, or example):
  <img src="__IMAGE_0__" style="width:280px;height:200px;object-fit:cover;border-radius:8px;box-shadow:0 4px 24px rgba(0,0,0,0.35);position:relative;z-index:2;">
  Position naturally in the layout (float, flex item, or absolute corner). The `#composition` palette background remains the canvas — no scrim needed."""


def _cue_sheet(audio_cues, kind: str) -> str:
    """Format per-sentence audio cues into timed beat instructions so the LLM lands
    each animation beat on the spoken word. kind in {"hf","manim"} tailors the how-to.
    Empty string when there are no cues (degrades to duration-based pacing)."""
    if not audio_cues:
        return ""
    rows = []
    i = 0
    for c in audio_cues:
        if not isinstance(c, dict):
            continue  # cues come from the voiceover service unvalidated
        i += 1
        s = float(c.get("start", 0) or 0)
        d = float(c.get("duration", 0) or 0)
        txt = (c.get("text") or "").strip().replace("\n", " ")
        rows.append(f'  beat {i} @ {s:.1f}s (spoken {d:.1f}s): "{txt}"')
    if not rows:
        return ""
    table = "\n".join(rows)
    last = [c for c in audio_cues if isinstance(c, dict)][-1]
    total = round(float(last.get("start", 0) or 0) + float(last.get("duration", 0) or 0), 1)
    if kind == "hf":
        how = ("Put each beat on the GSAP timeline at its cue start via the absolute position "
               "param — e.g. `tl.from('#beat-2', {autoAlpha:0, y:30, duration:0.5}, 2.4)` reveals "
               "beat 2 at 2.4s. Reveal a sentence's visual AT its start time: never before it's "
               "spoken, never all at once. One beat per sentence.")
    else:
        how = ("Pace construct() so each beat begins at its cue start: size self.play(run_time=...) "
               "to the cue's spoken duration and add self.wait(...) to fill gaps, so the Nth reveal "
               "lands at the Nth cue's start.")
    return (f"\n## AUDIO SYNC — align animation to the recorded narration (seconds from scene start)\n"
            f"{table}\nTotal narration ~= {total}s.\n{how}\n")


def _build_hf_prompt(scene_id: int, narration: str, visual: str, duration: int,
                     error_log: str = None, previous_html: str = None,
                     image_paths=None, job_style: dict = None,
                     neighbor_context: dict = None, audio_cues=None,
                     error_history=None) -> str:
    """User-prompt body. Style + structure rules come from the system prompt
    (hf_rules.md). This message only carries scene-specific values + the two
    template strings the LLM must emit verbatim with the right scene_id."""

    # Phase 1: identity block — overrides hf_rules.md palette/font defaults
    identity_block = ""
    if job_style:
        identity_block = (
            f"\n## THIS SCENE'S IDENTITY (override the Visual baseline defaults above)\n"
            f"Style: {job_style.get('name', 'Swiss Pulse')}\n"
            f"Background: {job_style.get('palette_bg', '#f5f5f0')} "
            f"(use this, not the near-neutral default)\n"
            f"Foreground: {job_style.get('palette_fg', '#1a1a1a')}\n"
            f"Accent: {job_style.get('palette_accent', '#e63946')}\n"
            f"Fonts: serif={job_style.get('font_serif', 'Georgia, serif')}; "
            f"sans={job_style.get('font_sans', 'Arial, sans-serif')}\n"
            f"Timeline defaults: ease=\"{job_style.get('easing_entrance', 'power3.out')}\" "
            f"on entrances, \"{job_style.get('easing_exit', 'power2.in')}\" on exits\n"
            f"Motion signature: {job_style.get('motion_sig', '')}\n"
            f"Keep this identity identical to every other scene in this video.\n"
        )

    # Phase 3: neighbor context — helps echo/contrast adjacent scenes
    neighbor_block = ""
    if neighbor_context:
        prev = neighbor_context.get("prev_visual")
        nxt = neighbor_context.get("next_visual")
        parts = []
        if prev:
            parts.append(f"← coming from: {prev}")
        if nxt:
            parts.append(f"→ going into: {nxt}")
        if parts:
            neighbor_block = "# Scene context: " + " | ".join(parts) + "\n\n"

    contract = f"""REQUIRED root wrapper (copy literally — the HyperFrames compiler mounts the
scene by this exact data-composition-id, then drops the wrapper):
  <div id="composition"
       data-composition-id="scene-{scene_id}"
       data-start="0"
       data-duration="{duration}"
       data-width="1920"
       data-height="1080"
       style="position:relative;width:1920px;height:1080px;overflow:hidden;">

REQUIRED GSAP registration block (paste literally with the right scene_id —
the runtime auto-nests the timeline ONLY when this key equals the
data-composition-id above):
  const tl = gsap.timeline({{ paused: true }});
  window.__timelines = window.__timelines || {{}};
  window.__timelines["scene-{scene_id}"] = tl;
  // then add tl.from(...) / tl.to(...) calls for each animated element

Both `body` and the `#composition` div MUST have an explicit non-transparent
background-color following the system palette baseline (tinted near-neutral,
NOT pure #ffffff/#000000) so the rendered frame is visible.

Do NOT include a lower-third caption — narration is audio-only.
Do NOT use @font-face — use system font stacks per the system typography rules.
Do NOT load external scripts other than the GSAP CDN.

Output ONLY the complete <!DOCTYPE html>...</html> document."""

    img_block = _image_guidance(len(image_paths or []), duration)
    cue_block = _cue_sheet(audio_cues, "hf")

    if error_log and previous_html:
        # previous_html is the already-inlined file (base64 images) — strip those
        # back to a marker so the retry prompt doesn't balloon / truncate mid-base64.
        prev = _strip_data_uris(previous_html)[:6000]
        return f"""Fix this HyperFrames scene per the system rules — it failed validation.
{neighbor_block}
Scene ID: {scene_id}
Total duration: {duration} seconds
Narration (spoken, NOT on-screen): {narration}
Visual description: {visual}
{identity_block}
PREVIOUS HTML:
```html
{prev}
```

VALIDATION ERROR:
{error_log[-600:]}
{_history_block(error_history)}
Fix the error while keeping the scene's content and design intent.

{contract}{img_block}{cue_block}"""

    example = _pick_hf_example(visual, scene_id)
    return f"""Create a HyperFrames HTML scene per the system rules.
{pitfalls_block("hyperframes")}{neighbor_block}
Scene ID: {scene_id}
Total duration: {duration} seconds
Narration (spoken, NOT on-screen): {narration}
Visual description: {visual}
{identity_block}
{contract}{img_block}{cue_block}

FEW-SHOT EXAMPLE — a DIFFERENT scene on a DIFFERENT topic. Imitate the CRAFT
(layout archetype, .scene-content flex container, timeline registration,
gsap.from() entrances with visible CSS, staggered reveals, varied eases,
type-scale contrast), NOT the content, palette, or ids — yours is scene-{scene_id}
with the identity palette above:
```html
{example}
```"""


def _extract_html(text: str) -> str:
    """Pull the HTML document out of an LLM response."""
    # Strip markdown fences if present
    text = re.sub(r"```html\s*", "", text)
    text = re.sub(r"```\s*$", "", text, flags=re.MULTILINE)
    m = re.search(r"<!DOCTYPE\s+html.*</html>", text, re.IGNORECASE | re.DOTALL)
    if m:
        return m.group(0)
    m = re.search(r"<html.*</html>", text, re.IGNORECASE | re.DOTALL)
    return m.group(0) if m else text.strip()


_OPACITY0_RE = re.compile(r"opacity\s*:\s*0(?:\.0+)?\s*(;|(?=\}))", re.IGNORECASE)
_VIS_HIDDEN_RE = re.compile(r"visibility\s*:\s*hidden\s*(;|(?=\}))", re.IGNORECASE)
_STYLE_BLOCK_RE = re.compile(r"(<style[^>]*>)(.*?)(</style>)", re.IGNORECASE | re.DOTALL)
# gsap.from(...) / fromTo(...) calls whose first arg is a quoted selector.
_FROM_CALL_RE = re.compile(r"""\.(?:from|fromTo)\s*\(\s*(['"])(.*?)\1\s*,\s*\{(.*?)\}""", re.DOTALL)
_SEL_TOKEN_RE = re.compile(r"[#.][\w-]+")
_HID_IN_ARGS_RE = re.compile(r"(?:opacity|autoAlpha)\s*:\s*0(?![.\d])", re.IGNORECASE)


def _unhide_css(html: str) -> str:
    """Fix the gsap.from() 0->0 invisible trap WITHOUT breaking gsap.to() reveals.

    The render-killer: an element pinned `opacity:0` in CSS AND revealed with
    gsap.from({opacity:0}) — `from` tweens FROM 0 TO the element's CURRENT (CSS)
    value, also 0, so it stays invisible (blank screen). But elements revealed with
    gsap.to({opacity:1}) CORRECTLY start hidden in CSS, and CSS @keyframes use
    opacity:0 legitimately — so a blanket strip breaks those. We therefore strip
    `opacity:0`/`visibility:hidden` ONLY from CSS rules whose selector is a
    from()/fromTo() opacity-0 target. @keyframes/@media survive automatically because
    the rule regex forbids nested braces. The GSAP <script> is never touched.
    (Known gap: inline style="opacity:0" attributes are not scrubbed — the system
    prompt forbids hiding animated elements that way.)"""
    targets = set()
    for m in _FROM_CALL_RE.finditer(html):
        if _HID_IN_ARGS_RE.search(m.group(3)):
            targets.update(_SEL_TOKEN_RE.findall(m.group(2)))
    if not targets:
        return html
    # `tok(?![\w-])` so `.title` doesn't match an unrelated `.title-bar` rule.
    sel_alt = "|".join(re.escape(t) + r"(?![\w-])" for t in targets)
    rule_re = re.compile(r"([^{}]*(?:" + sel_alt + r")[^{}]*)\{([^{}]*)\}")

    def fix_rule(rm: "re.Match") -> str:
        body = _VIS_HIDDEN_RE.sub("", _OPACITY0_RE.sub("", rm.group(2)))
        return rm.group(1) + "{" + body + "}"

    def fix_style(sm: "re.Match") -> str:
        return sm.group(1) + rule_re.sub(fix_rule, sm.group(2)) + sm.group(3)

    return _STYLE_BLOCK_RE.sub(fix_style, html)


async def _generate_hyperframes(request):
    scene    = request.scene
    scene_id = scene.scene_id
    set_log_context(scene_id=scene_id)
    is_retry = bool(request.error_log and request.previous_code)
    logger.info("Generating HyperFrames HTML", extra={"scene_id": scene_id, "is_retry": is_retry})

    image_paths = request.image_paths or []
    prompt = _build_hf_prompt(
        scene_id         = scene_id,
        narration        = scene.narration_text,
        visual           = scene.visual_description,
        duration         = scene.estimated_duration_seconds,
        error_log        = request.error_log,
        previous_html    = request.previous_code,
        image_paths      = image_paths,
        job_style        = request.job_style,
        neighbor_context = request.neighbor_context,
        audio_cues       = request.audio_cues,
        error_history    = request.error_history,
    )

    last_error = None
    for attempt in range(3):
        try:
            t0 = time.time()
            resp = await _llm_chat(
                messages = [
                    {"role": "system", "content": _HF_SYSTEM},
                    {"role": "user",   "content": prompt},
                ],
                max_tokens  = settings.CODE_GENERATOR_MAX_TOKENS,
                temperature = _sampling_temperature(0.6),
                top_p       = _sampling_top_p(),
            )
            elapsed = time.time() - t0
            html = _extract_html(resp.choices[0].message.content)
            if not html:
                raise ValueError("LLM returned empty HTML")
            # Safety net: strip CSS opacity:0/visibility:hidden so gsap.from()
            # entrances can't animate 0->0 and leave content invisible.
            html = _unhide_css(html)
            # Inline any __IMAGE_k__ placeholders to base64 data URIs so the
            # written file is self-contained (renders the same standalone or
            # inlined into the master composition).
            html = _inline_images(html, image_paths)

            log_llm_call(logger, settings.CODE_GENERATOR_MODEL,
                         prompt_chars=len(prompt),
                         response_chars=len(resp.choices[0].message.content),
                         elapsed_s=elapsed, attempt=attempt + 1,
                         scene_id=scene_id, content_type="hyperframes")

            temp_dir  = os.path.join(settings.WORKSPACE_DIR, "temp", request.job_id)
            os.makedirs(temp_dir, exist_ok=True)
            file_path = os.path.join(temp_dir, f"scene_{scene_id}.html")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(html)
            log_file(logger, "written", file_path, scene_id=scene_id, content_type="hyperframes")

            logger.info("HyperFrames HTML saved", extra={"scene_id": scene_id, "path": file_path})
            return CodeGeneratorResponse(scene_id=scene_id, code_path=file_path)

        except Exception as e:
            last_error = e
            logger.warning("HyperFrames attempt failed", extra={"attempt": attempt + 1, "error": str(e)})

    raise RuntimeError(f"HyperFrames generation failed after 3 attempts: {last_error}")


# ─────────────────────────────────────────────────────────────────────────────
# Manim Python code generation via LLM
# ─────────────────────────────────────────────────────────────────────────────
# System prompt is the official Manim CE skill rules + a thin task wrapper.
# Rule edits live in services/code-generator/app/prompts/manim_rules.md.
_MANIM_SYSTEM = load_rules("manim_rules") + """

---

# Your Task

You are an expert Manim Community Edition animator. Always respond with valid
JSON containing a single `python_code` key whose value is the complete scene
file. Follow every rule above without exception — the validator runs the code
through `manim render` and a forbidden-API sanitizer; both will reject
violations.

Pipeline-specific contract:
- Set `config.background_color` at MODULE level — directly under
  `from manim import *`, OUTSIDE the class, BEFORE the class definition.
  Setting it inside `construct()` is a SILENT NO-OP (camera is created before
  construct runs). Use the background color from THIS VIDEO'S VISUAL IDENTITY
  in the user message; if no identity is given, default to `WHITE`. Never
  render any element in a color close to the background (it would be
  invisible): on a light/WHITE canvas use dark strokes/text, on a dark canvas
  use light ones.
- Use rich colors for math that contrast with the background: on a light
  canvas, axes `"#1a1a2e"`, curves `"#e63946"` or `"#2196f3"`, dots `"#ff9800"`.
- The class name MUST be exactly `Scene{N}` (one integer the caller fills in).
- No external asset loads, no `SVGMobject("...")`, no web calls."""


# Few-shot demonstrates the craft the rules describe: motion that carries
# meaning (the dot RIDES the curve to a landing point — ease_in_out_sine LANDS,
# unlike the forbidden self-undoing there_and_back), guided attention
# (Indicate on the focal object at the payoff), and a held final frame.
_MANIM_FEW_SHOT = (
    '{"python_code": "from manim import *\\n'
    'config.background_color = WHITE  # module level — use the identity background for THIS video if given; WHITE shown as the no-identity default\\n\\n'
    'class Scene1(Scene):\\n'
    '    def construct(self):\\n'
    '        axes = Axes(x_range=[-3,3], y_range=[0,9], x_length=10, y_length=6,'
    ' axis_config={\\\"color\\\": \\\"#1a1a2e\\\", \\\"stroke_width\\\": 3})'
    '.move_to(UP*0.3)\\n'
    '        labels = axes.get_axis_labels(x_label=\\\"x\\\", y_label=\\\"y\\\")'
    '.set_color(BLACK)\\n'
    '        curve = axes.plot(lambda x: x**2, color=\\\"#e63946\\\", stroke_width=4)\\n'
    '        self.play(Create(axes), Write(labels))\\n'
    '        self.play(Create(curve), run_time=2)\\n'
    '        dot = Dot(axes.c2p(-2, 4), color=\\\"#ff9800\\\", radius=0.12)\\n'
    '        self.play(FadeIn(dot, scale=0.5))\\n'
    '        self.play(MoveAlongPath(dot, curve), run_time=3,'
    ' rate_func=rate_functions.ease_in_out_sine)\\n'
    '        value = MathTex(\\\"f(2)=4\\\", color=\\\"#1a1a2e\\\")'
    '.next_to(axes.c2p(2, 4), UR, buff=0.3)\\n'
    '        self.play(Write(value), Indicate(dot, color=\\\"#ff9800\\\"))\\n'
    '        self.wait(1.5)\\n"}'
)


def _history_block(error_history) -> str:
    """Format the FULL failure trail for late retries. Seeing only the latest
    error made the model ping-pong between two mistakes; the trail says
    'attempt 1 died on X, attempt 2 on Y — produce code with NONE of these.'"""
    entries = [h for h in (error_history or []) if isinstance(h, dict) and h.get("error")]
    if len(entries) < 2:
        return ""
    rows = "\n".join(
        f"  attempt {h.get('attempt', '?')} ({h.get('source', '?')}): {str(h['error'])[:300]}"
        for h in entries
    )
    return (f"\nALL PREVIOUS FAILED ATTEMPTS for this scene (do not repeat ANY of these):\n"
            f"{rows}\n"
            "Write this attempt to avoid every failure above simultaneously — if two "
            "fixes conflicted before, restructure the scene rather than alternating.\n")


def _hex_is_light(hex_color: str) -> bool:
    """True if a #rrggbb hex reads as a light background (needs a dark
    foreground for contrast). Defaults to True (matches today's WHITE
    fallback) when the value is missing/malformed."""
    h = (hex_color or "").lstrip("#")
    if len(h) != 6:
        return True
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return True
    luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return luminance > 0.5


def _manim_identity_block(job_style: dict) -> str:
    """Per-job visual identity for the Manim path — mirrors _build_hf_prompt's
    identity_block so Manim scenes match the HyperFrames scenes in the same
    video (and stay identical scene-to-scene) instead of hardcoding WHITE and
    drifting per generation. Empty string when no job_style (today's WHITE
    fallback + the system prompt's existing dark-color guidance applies)."""
    if not job_style:
        return ""
    bg     = job_style.get("palette_bg", "#f5f5f0")
    fg     = job_style.get("palette_fg", "#1a1a1a")
    accent = job_style.get("palette_accent", "#e63946")
    if _hex_is_light(bg):
        contrast_note = (f'Contrast check: {bg} is a LIGHT background, so text/axes/strokes MUST '
                         f'use the dark {fg} — never WHITE, never a light tint (WHITE-on-{bg} is invisible).')
    else:
        contrast_note = (f'Contrast check: {bg} is a DARK background, so text/axes/strokes MUST '
                         f'use the light {fg} — never BLACK, never a dark tint (BLACK-on-{bg} is invisible).')
    return f"""
## THIS JOB'S VISUAL IDENTITY (applies to this scene AND every other scene in the video)
Override the WHITE default below — use this job's background instead:
  config.background_color = "{bg}"   # MODULE level, OUTSIDE the class — replaces WHITE

- Background: {bg} — this job's canvas color. Use this hex, NOT WHITE.
- Foreground ({fg}): axis labels, titles, body text, neutral strokes — use this instead of BLACK.
- Accent ({accent}): the ONE primary highlighted curve/dot/focal element only.
- Keep these exact three hex values IDENTICAL across every scene in this video —
  do not invent alternate colors or let the palette drift scene-to-scene.
- {contrast_note}
"""


def _build_manim_prompt(scene: object, error_log: str = None, previous_code: str = None,
                        audio_cues=None, error_history=None, job_style: dict = None) -> str:
    """User-prompt body. Style + forbidden-API rules come from the system
    prompt (manim_rules.md). This message only carries scene-specific values
    and a class-name reminder."""
    sid = scene.scene_id
    cue_block = _cue_sheet(audio_cues, "manim")
    identity_block = _manim_identity_block(job_style)

    if error_log and previous_code:
        return f"""Fix this Manim CE scene per the system rules — it failed to render.
{identity_block}
PREVIOUS CODE:
```python
{previous_code}
```

ERROR LOG (last 600 chars):
{error_log[-600:]}
{_history_block(error_history)}
Class name MUST stay `Scene{sid}`. The error often comes from one of the
forbidden APIs in the system rules — re-check those first.
{cue_block}
Return ONLY: {{"python_code": "..."}}"""

    duration = getattr(scene, "estimated_duration_seconds", 0) or 0

    bg_contract = (
        f'`config.background_color = "{job_style.get("palette_bg", "#f5f5f0")}"` MUST be at MODULE '
        f'level — directly under `from manim import *`, OUTSIDE the class (this job\'s background — '
        f'see identity block above). Inside `construct()` it is a no-op.'
        if job_style else
        '`config.background_color = WHITE` MUST be at MODULE level — directly under\n'
        '`from manim import *`, OUTSIDE the class. Inside `construct()` it is a no-op.'
    )

    return f"""Create a Manim CE scene per the system rules.
{pitfalls_block("manim")}
SCENE DETAILS:
Scene #:    {sid}
Duration:   {duration} seconds (the narration plays for this long)
Narration:  {scene.narration_text}
Visual:     {scene.visual_description}
{identity_block}
Class name MUST be exactly `Scene{sid}` (subclass of `Scene`).
No on-screen title text (the HyperFrames layer adds the scene title).
{bg_contract}

PACING — the animation should unfold across the {duration}s of narration, not
race through in a few seconds. Spread the reveals over the whole scene: keep
each `run_time` 0.5-3s and add `self.wait(...)` beats between steps, then end
with a final `self.wait(...)` holding the completed visual. Aim for the sum of
all run_times + waits to land JUST UNDER {duration}s (about {duration}s minus
1-2s) — the final frame is held automatically until narration ends, so finishing
slightly early is correct. Do NOT exceed {duration}s: overshooting pushes the
video past its narration and breaks the overall timing budget.
{cue_block}
FEW-SHOT EXAMPLE (valid output for a different scene):
```json
{_MANIM_FEW_SHOT}
```

Return ONLY: {{"python_code": "..."}}"""


def _syntax_error_log(code: str) -> str | None:
    """Return a compact SyntaxError message if `code` won't parse, else None.
    Pure stdlib `ast.parse` — instant, no render. Lets a syntax/indentation fault
    be caught + repaired locally instead of shipping to the validator's multi-minute
    `manim render` round-trip (which would also burn a retry-count bump)."""
    try:
        ast.parse(code)
        return None
    except SyntaxError as se:
        loc = f"line {se.lineno}" + (f", col {se.offset}" if se.offset else "")
        return f"SyntaxError: {se.msg} ({loc}): {(se.text or '').strip()}"


async def _generate_manim(request):
    scene    = request.scene
    scene_id = scene.scene_id
    set_log_context(scene_id=scene_id)
    is_retry = bool(request.error_log and request.previous_code)
    logger.info("Generating Manim code", extra={"scene_id": scene_id, "is_retry": is_retry})

    # Seed prompt with the validator's error (if this whole request is a retry),
    # then loop locally: a parse failure feeds itself back as the next error_log.
    error_log     = request.error_log
    previous_code = request.previous_code
    code_to_write = None
    candidate     = ""  # last parseable-or-not candidate (JSON-repair path may skip a round)

    try:
        for attempt in range(3):  # ponytail: 1 generate + up to 2 local syntax repairs
            prompt = _build_manim_prompt(scene, error_log, previous_code,
                                         audio_cues=request.audio_cues,
                                         error_history=request.error_history,
                                         job_style=request.job_style)
            llm_start = time.time()
            response  = await _llm_chat(
                messages = [
                    {"role": "system", "content": _MANIM_SYSTEM},
                    {"role": "user",   "content": prompt},
                ],
                max_tokens      = settings.CODE_GENERATOR_MAX_TOKENS,
                temperature     = _sampling_temperature(0.2),
                top_p           = _sampling_top_p(),
                response_format = {"type": "json_object"},
            )
            llm_dur = time.time() - llm_start
            log_llm_call(logger, settings.CODE_GENERATOR_MODEL,
                         prompt_chars=len(prompt),
                         response_chars=len(response.choices[0].message.content),
                         elapsed_s=llm_dur, attempt=attempt + 1,
                         scene_id=scene_id, content_type="manim")

            # Content may arrive fenced/wrapped or (rarely) malformed — a bare
            # json.loads here used to abort the WHOLE scene attempt instead of
            # feeding the local repair loop like every other fault.
            from shared.llm_client import extract_json
            try:
                code_data = json.loads(extract_json(response.choices[0].message.content or ""))
            except (TypeError, ValueError) as je:
                logger.warning("Manim LLM reply was not valid JSON — repairing",
                               extra={"scene_id": scene_id, "attempt": attempt + 1,
                                      "error": str(je)[:160]})
                error_log = f"Your previous reply was not valid JSON ({je}). Return ONLY {{\"python_code\": \"...\"}}."
                previous_code = previous_code or ""
                continue
            code      = code_data.get("python_code", "")

            # Sanitize generated code to replace deprecated/forbidden Manim APIs
            try:
                sanitized_code, sanitize_warnings = sanitize_manim_code(code, scene_id=scene_id)
            except Exception as s_e:
                logger.warning("Sanitizer failed, using original code", extra={"scene_id": scene_id, "error": str(s_e)})
                sanitized_code = code
                sanitize_warnings = []

            if sanitize_warnings:
                for w in sanitize_warnings:
                    logger.warning(f"Sanitizer: {w}", extra={"scene_id": scene_id})

            candidate = sanitized_code if sanitized_code else code

            # Security gate (the STRONG one — shared/security.py constants, same
            # set as the validator's preflight). Violations feed the repair loop
            # instead of writing dangerous code to the workspace.
            violations = check_manim_security(candidate)
            if violations:
                logger.warning("Manim code failed security gate — repairing",
                               extra={"scene_id": scene_id, "attempt": attempt + 1,
                                      "violations": violations[:5]})
                error_log = ("Security violations — remove these entirely "
                             "(no os/subprocess/eval/getattr etc.):\n" + "\n".join(violations))
                previous_code = candidate
                continue

            # Local compile gate: catch syntax faults here, not after a render.
            syn_err = _syntax_error_log(candidate)
            if syn_err is None:
                code_to_write = candidate
                break
            logger.warning("Manim code failed local parse — repairing",
                           extra={"scene_id": scene_id, "attempt": attempt + 1, "error": syn_err})
            error_log     = syn_err      # feed the parse error into the next repair prompt
            previous_code = candidate    # so the LLM edits the exact broken code

        if code_to_write is None:
            # All local attempts still won't parse; ship the last candidate anyway so
            # the validator records a real error_log and the retry-count logic owns it
            # (rather than raising here and looking like a code-gen infra failure).
            code_to_write = candidate
            logger.error("Manim code still unparseable after local repairs — sending last candidate",
                         extra={"scene_id": scene_id})

        temp_dir  = os.path.join(settings.WORKSPACE_DIR, "temp", request.job_id)
        os.makedirs(temp_dir, exist_ok=True)
        file_path = os.path.join(temp_dir, f"scene_{scene_id}.py")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(code_to_write)
        log_file(logger, "written", file_path, scene_id=scene_id, content_type="manim")

        logger.info("Manim code saved", extra={"scene_id": scene_id, "path": file_path, "code_lines": code_to_write.count(chr(10))})
        return CodeGeneratorResponse(scene_id=scene_id, code_path=file_path)

    except Exception as e:
        logger.error("Manim generation error", extra={"scene_id": scene_id}, exc_info=True)
        raise e


# ─────────────────────────────────────────────────────────────────────────────
# Main endpoint
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/generate", response_model=CodeGeneratorResponse)
@traceable(run_type="llm", name="code-generator.generate")
async def generate_code(request: CodeGeneratorRequest):
    scene    = request.scene
    scene_id = scene.scene_id
    set_log_context(job_id=request.job_id, scene_id=scene_id)
    # Render mode forces one engine for the whole job; "hybrid" keeps the
    # per-scene choice (script-writer's content_type, else keyword classify).
    # Per-request render_mode (set per job in the UI) wins over the env default.
    mode = (request.render_mode or settings.RENDER_MODE or "hybrid").strip().lower()
    if mode in ("manim", "hyperframes"):
        content_type = mode
    else:
        # Script-writer's content_type is AUTHORITATIVE. Only fall back to the
        # keyword heuristic when it is genuinely absent (None / missing / blank)
        # — a legitimate value like "hyperframes" must NOT be re-classified.
        script_ct = (scene.content_type or "").strip() if scene.content_type else ""
        content_type = script_ct or classify_scene(scene.narration_text, scene.visual_description)
    logger.info("Code generation request", extra={"scene_id": scene_id, "content_type": content_type,
                                                   "render_mode": mode,
                                                   "model": settings.CODE_GENERATOR_MODEL})

    if content_type == "manim":
        return await _generate_manim(request)
    else:
        return await _generate_hyperframes(request)


@app.get("/health")
def health():
    return {"status": "ok"}
