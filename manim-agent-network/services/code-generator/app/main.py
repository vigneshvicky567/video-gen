from fastapi import FastAPI
from shared.schemas.requests import CodeGeneratorRequest
from shared.schemas.responses import CodeGeneratorResponse
from shared.config import settings
from shared.llm_client import get_llm_client
from shared.log import get_logger, set_log_context, timed_block, log_llm_call, log_file, make_request_logging_middleware
import os
import sys
from .sanitizer import sanitize_manim_code
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


# ── Mistral fallback (separate provider/quota) ────────────────────────────────
import httpx as _httpx
from types import SimpleNamespace

# Circuit breaker: after NIM fails, route code-gen straight to Mistral for a
# cooldown window so a 40-scene batch doesn't burn the per-scene NIM retry budget
# (~tens of seconds each) before failing over. Resets to trying NIM after cooldown.
_nim_down_until = 0.0
_NIM_COOLDOWN_S = 120


async def _mistral_chat(messages, max_tokens, temperature, response_format=None):
    """One code-gen call against Mistral (OpenAI-compatible). Returns a NIM-shaped
    response so callers read resp.choices[0].message.content unchanged."""
    payload = {
        "model": settings.MISTRAL_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": min(max(temperature or 0.3, 0.0), 1.0),  # Mistral caps temp at 1.0
    }
    if response_format:
        payload["response_format"] = response_format
    url = f"{settings.MISTRAL_BASE_URL.rstrip('/')}/chat/completions"
    async with _httpx.AsyncClient(timeout=150) as c:
        r = await c.post(url, headers={"Authorization": f"Bearer {settings.MISTRAL_API_KEY}",
                                       "Content-Type": "application/json"}, json=payload)
        r.raise_for_status()
        data = r.json()
    choices = [SimpleNamespace(message=SimpleNamespace(content=(ch.get("message") or {}).get("content")))
               for ch in data.get("choices", [])]
    return SimpleNamespace(choices=choices, model=data.get("model"), usage=data.get("usage"))


async def _llm_chat(messages, max_tokens, temperature, top_p=None, response_format=None):
    """Code-gen LLM call: NIM primary, Mistral fallback on any NIM failure (incl.
    429). A process circuit breaker skips NIM during a cooldown after it fails so
    the rest of a batch fails over fast instead of retrying a dead NIM per scene."""
    global _nim_down_until
    has_mistral = bool(settings.MISTRAL_API_KEY)
    if not (has_mistral and time.monotonic() < _nim_down_until):
        try:
            return await client.chat.completions.acreate(
                model=settings.CODE_GENERATOR_MODEL, messages=messages,
                temperature=temperature, top_p=top_p,
                max_tokens=max_tokens, response_format=response_format,
            )
        except Exception as e:
            if not has_mistral:
                raise
            _nim_down_until = time.monotonic() + _NIM_COOLDOWN_S
            logger.warning(f"NIM code-gen failed -> Mistral fallback (cooldown {_NIM_COOLDOWN_S}s)",
                           extra={"error": str(e)[:160], "mistral_model": settings.MISTRAL_MODEL})
    return await _mistral_chat(messages, max_tokens, temperature, response_format)


# ─────────────────────────────────────────────────────────────────────────────
# Scene classification (fallback when script-writer doesn't set content_type)
# ─────────────────────────────────────────────────────────────────────────────
MANIM_KEYWORDS = [
    "equation", "formula", "graph", "plot", "curve", "axes", "matrix",
    "vector", "geometry", "proof", "derivative", "integral", "transform",
    "animate", "draw", "manim", "mathematical", "3d surface", "eigenvalue",
]

def classify_scene(narration: str, visual: str) -> str:
    """Return 'manim' only when the scene genuinely needs math animation."""
    combined = f"{narration} {visual}".lower()
    hits = sum(1 for kw in MANIM_KEYWORDS if kw in combined)
    return "manim" if hits >= 2 else "hyperframes"


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


def _img_data_uri(path: str) -> str:
    with open(path, "rb") as fh:
        raw = fh.read()
    if len(raw) > _IMG_INLINE_MAX_BYTES:
        raise ValueError(f"image too large to inline: {len(raw)} bytes")
    mime = "image/png" if raw[:4] == b"\x89PNG" else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def _inline_images(html: str, image_paths) -> str:
    """Replace each `__IMAGE_k__` placeholder with a base64 data URI. Unmatched or
    unreadable placeholders are blanked so no broken src reaches the renderer."""
    if image_paths:
        for i, p in enumerate(image_paths):
            token = f"__IMAGE_{i}__"
            if token not in html:
                continue
            try:
                html = html.replace(token, _img_data_uri(p))
            except Exception as e:
                logger.warning("Could not inline image", extra={"path": p, "error": str(e)})
                html = html.replace(token, "")
    # Drop any placeholder the model invented past the available image count.
    return _IMG_TOKEN_RE.sub("", html)


def _strip_data_uris(html: str) -> str:
    """Shrink inlined base64 back to a marker so retry prompts stay small (the
    previous_code carried on retry is the already-inlined file)."""
    return _DATA_URI_RE.sub("__IMAGE_0__", html)


def _image_guidance(n: int, duration: int) -> str:
    if n <= 0:
        return ""
    toks = ", ".join(f"__IMAGE_{i}__" for i in range(n))
    plural = "s" if n > 1 else ""
    return f"""

BACKGROUND IMAGERY — {n} relevant photo{plural} available; use the BEST one as a full-bleed background:
- Reference images ONLY by these exact placeholders in src: {toks}. Never invent other src values, never use http(s) URLs.
- Full-bleed bg layer: <img id="bg-photo" src="__IMAGE_0__" style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover;z-index:0;"> — object-fit:cover, never stretch.
- Scrim for legibility: a <div style="position:absolute;inset:0;z-index:1;background:linear-gradient(...)"> using the palette's dark base at 0.55-0.85 alpha, heaviest where text sits, so all text keeps WCAG 4.5:1.
- The `#composition` div still needs its opaque palette background-color (shows if the image fails to load). All .scene-content text/decoratives sit ABOVE the scrim (z-index:2+).
- Ken-Burns the bg on the timeline, subtle and slow: tl.fromTo("#bg-photo", {{scale:1.0}}, {{scale:1.08, ease:"power1.inOut", duration:{duration}}}, 0).
- You MUST use __IMAGE_0__ as the background. Do NOT skip it — these images were pre-selected for this scene."""


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
                     neighbor_context: dict = None, audio_cues=None) -> str:
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

Fix the error while keeping the scene's content and design intent.

{contract}{img_block}{cue_block}"""

    return f"""Create a HyperFrames HTML scene per the system rules.
{neighbor_block}
Scene ID: {scene_id}
Total duration: {duration} seconds
Narration (spoken, NOT on-screen): {narration}
Visual description: {visual}
{identity_block}
{contract}{img_block}{cue_block}"""


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
- Background MUST be set at MODULE level — directly under `from manim import *`,
  OUTSIDE the class, BEFORE the class definition:
    config.background_color = WHITE
  Setting it inside `construct()` is a SILENT NO-OP (camera is created before
  construct runs). The white canvas is provided by the HyperFrames composition
  layer; never render white text/strokes on it.
- Use rich dark colors for math: axes `"#1a1a2e"`, curves `"#e63946"` or
  `"#2196f3"`, dots `"#ff9800"`.
- The class name MUST be exactly `Scene{N}` (one integer the caller fills in).
- No external asset loads, no `SVGMobject("...")`, no web calls."""


_MANIM_FEW_SHOT = (
    '{"python_code": "from manim import *\\n'
    'config.background_color = WHITE  # MODULE level — outside the class\\n\\n'
    'class Scene1(Scene):\\n'
    '    def construct(self):\\n'
    '        axes = Axes(x_range=[-3,3], y_range=[0,9], x_length=8, y_length=5,'
    ' axis_config={\\\"color\\\": \\\"#1a1a2e\\\", \\\"stroke_width\\\": 3})'
    '.move_to(DOWN*0.3)\\n'
    '        labels = axes.get_axis_labels(x_label=\\\"x\\\", y_label=\\\"y\\\")'
    '.set_color(BLACK)\\n'
    '        curve = axes.plot(lambda x: x**2, color=\\\"#e63946\\\", stroke_width=4)\\n'
    '        self.play(Create(axes), Write(labels))\\n'
    '        self.play(Create(curve), run_time=2)\\n'
    '        dot = Dot(axes.c2p(-2, 4), color=\\\"#ff9800\\\", radius=0.12)\\n'
    '        self.play(FadeIn(dot))\\n'
    '        self.play(MoveAlongPath(dot, curve), run_time=2,'
    ' rate_func=rate_functions.there_and_back)\\n'
    '        self.wait(1)\\n"}'
)


def _build_manim_prompt(scene: object, error_log: str = None, previous_code: str = None,
                        audio_cues=None) -> str:
    """User-prompt body. Style + forbidden-API rules come from the system
    prompt (manim_rules.md). This message only carries scene-specific values
    and a class-name reminder."""
    sid = scene.scene_id
    cue_block = _cue_sheet(audio_cues, "manim")

    if error_log and previous_code:
        return f"""Fix this Manim CE scene per the system rules — it failed to render.

PREVIOUS CODE:
```python
{previous_code}
```

ERROR LOG (last 600 chars):
{error_log[-600:]}

Class name MUST stay `Scene{sid}`. The error often comes from one of the
forbidden APIs in the system rules — re-check those first.
{cue_block}
Return ONLY: {{"python_code": "..."}}"""

    duration = getattr(scene, "estimated_duration_seconds", 0) or 0

    return f"""Create a Manim CE scene per the system rules.

SCENE DETAILS:
Scene #:    {sid}
Duration:   {duration} seconds (the narration plays for this long)
Narration:  {scene.narration_text}
Visual:     {scene.visual_description}

Class name MUST be exactly `Scene{sid}` (subclass of `Scene`).
No on-screen title text (the HyperFrames layer adds the scene title).
`config.background_color = WHITE` MUST be at MODULE level — directly under
`from manim import *`, OUTSIDE the class. Inside `construct()` it is a no-op.

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


async def _generate_manim(request):
    scene    = request.scene
    scene_id = scene.scene_id
    set_log_context(scene_id=scene_id)
    is_retry = bool(request.error_log and request.previous_code)
    logger.info("Generating Manim code", extra={"scene_id": scene_id, "is_retry": is_retry})

    prompt = _build_manim_prompt(scene, request.error_log, request.previous_code,
                                 audio_cues=request.audio_cues)

    try:
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
                     elapsed_s=llm_dur, scene_id=scene_id, content_type="manim")

        code_data = json.loads(response.choices[0].message.content)
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

        temp_dir  = os.path.join(settings.WORKSPACE_DIR, "temp", request.job_id)
        os.makedirs(temp_dir, exist_ok=True)
        file_path = os.path.join(temp_dir, f"scene_{scene_id}.py")
        # Write sanitized code when available
        code_to_write = sanitized_code if sanitized_code else code
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(code_to_write)
        log_file(logger, "written", file_path, scene_id=scene_id, content_type="manim")

        logger.info("Manim code saved", extra={"scene_id": scene_id, "path": file_path, "code_lines": code.count(chr(10))})
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
        content_type = scene.content_type or classify_scene(scene.narration_text, scene.visual_description)
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
