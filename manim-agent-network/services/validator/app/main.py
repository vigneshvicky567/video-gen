from fastapi import FastAPI, HTTPException
from shared.schemas.requests import ValidatorRequest
from shared.schemas.responses import ValidatorResponse
from shared.config import settings
from shared.log import get_logger, set_log_context, timed_block, log_subprocess, log_file, make_request_logging_middleware
from shared.proc import run_proc, ProcTimeout
from shared.security import FORBIDDEN_MODULES as _FORBIDDEN_MODULES, FORBIDDEN_BUILTINS as _FORBIDDEN_BUILTINS
from langsmith import traceable
import asyncio
import subprocess
import os
import re
import sys
import glob
import ast
import base64
import signal

app = FastAPI(title="Validator Service")
app.add_middleware(make_request_logging_middleware("validator"))
logger = get_logger(__name__)

# Initialised in _on_startup inside the running event loop (Python 3.10+ safe).
_RENDER_SEMAPHORE: asyncio.Semaphore = None  # type: ignore[assignment]


# Env vars carried into the manim subprocess. Manim runs GENERATED code, so it
# must NOT inherit this service's env (which holds every API key + internal
# service URL). We rebuild a minimal, safe env from os.environ selectively:
# only PATH/HOME (for finding manim/latex/ffmpeg + their caches) plus the
# standard locale/tmp/latex/python knobs manim actually needs. Anything not on
# this allowlist — API keys, ASSEMBLER_URL, ORCHESTRATOR_URL, etc. — is dropped.
_MANIM_ENV_ALLOWLIST = (
    "PATH", "HOME", "PYTHONPATH", "PYTHONHASHSEED", "PYTHONUNBUFFERED",
    "LANG", "LC_ALL", "LC_CTYPE", "TERM",
    "TMPDIR", "TEMP", "TMP",
    "TEXINPUTS", "TEXMFHOME", "TEXMFVAR", "TEXMFCONFIG", "TEXMFCACHE",
    "XDG_CACHE_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME",
    "SYSTEMROOT",  # Windows dev host: python/ffmpeg need this to start
)


def _build_manim_env() -> dict:
    """Minimal, safe env for the manim subprocess — no API keys / service URLs."""
    env = {k: os.environ[k] for k in _MANIM_ENV_ALLOWLIST if k in os.environ}
    # PATH is mandatory for locating the manim/latex/ffmpeg binaries.
    env.setdefault("PATH", os.defpath)
    return env


def _run_manim_subprocess(cmd: list, timeout_s: int):
    """Run manim in a blocking thread; kill the whole process GROUP on timeout.

    manim spawns grandchildren (dvisvgm, ffmpeg) that a bare proc.kill() leaks
    as zombies still holding CPU/RAM. We start the child in its own process
    group (preexec_fn=os.setsid, POSIX — the service runs in Linux containers)
    and SIGKILL the whole group on timeout OR on any other exception, then
    drain/wait so nothing is left leaking. The subprocess also runs with a
    stripped env (see _build_manim_env) so generated code never sees our
    secrets. Returns (returncode, stdout, stderr). Raises ProcTimeout — a
    subprocess.TimeoutExpired subclass — so callers' except clauses still match.
    """
    popen_kwargs = dict(stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        text=True, env=_build_manim_env())
    # POSIX: own session/process group so os.killpg reaches the whole tree.
    # preexec_fn is POSIX-only; on the win32 dev host fall back to a new group.
    if hasattr(os, "setsid"):
        popen_kwargs["preexec_fn"] = os.setsid
    else:
        popen_kwargs["creationflags"] = getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

    proc = subprocess.Popen(cmd, **popen_kwargs)

    def _kill_group() -> None:
        try:
            if hasattr(os, "killpg"):
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            else:
                proc.kill()
        except (ProcessLookupError, PermissionError, OSError):
            proc.kill()

    try:
        stdout, stderr = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        _kill_group()
        try:
            stdout, stderr = proc.communicate(timeout=10)  # drain/reap
        except Exception:
            stdout, stderr = "", ""
        raise ProcTimeout(cmd, timeout_s, output=stdout, stderr=stderr)
    except BaseException:
        # ANY other failure (cancellation, OSError, KeyboardInterrupt) must not
        # leak the process group — kill and reap before propagating.
        _kill_group()
        try:
            proc.communicate(timeout=10)
        except Exception:
            pass
        raise

    return proc.returncode, stdout, stderr

# Render budget bounds.
_TIMEOUT_FLOOR_S = 90
_TIMEOUT_PER_PLAY_S = 20
_TIMEOUT_CEILING_S = 600

# Self-test sources. Each MUST be flagged by AST preflight; otherwise image is
# stale. Covers BOTH the deprecated-API branch and the SECURITY branch of the
# gate (a security regression used to be invisible to the self-test).
_SELF_TEST_BAD_SOURCE = (
    "from manim import *\n"
    "config.background = WHITE\n"
    "class S(ThreeDScene):\n"
    "    def construct(self):\n"
    "        self.play(ShowCreation(Circle()), self.camera.animate.set_phi(0))\n"
)
_SELF_TEST_MALICIOUS_SOURCE = (
    "from manim import *\n"
    "import os\n"
    "class S(Scene):\n"
    "    def construct(self):\n"
    "        eval('1+1')\n"
    "        getattr(__builtins__, 'ex' + 'ec')\n"
)
# Each of these MUST be rejected by the security branch on its own — a single
# combined blob could pass on ONE finding while the rest silently regressed.
_SELF_TEST_SECURITY_SOURCES = (
    "import os\n",
    "import subprocess\nsubprocess.run(['id'])\n",
    "eval('1+1')\n",
    "__import__('os')\n",
    "x = ().__class__.__bases__\n",
)


def _reencode_for_seek(path: str, scene_id: int) -> str:
    """Re-encode a manim render with dense keyframes for the HyperFrames player.

    Manim's default h264 output has keyframe intervals of 4s+; the HyperFrames
    capture engine seeks the <video> element frame-by-frame and sparse
    keyframes cause seek failures — observed as black/frozen scene slots in
    the final video (the compositor lint warns about exactly this). 30fps with
    g=30 puts a keyframe every second. Permissive: returns the original path
    if ffmpeg fails, so a re-encode hiccup never fails an otherwise good scene.
    """
    out_path = os.path.splitext(path)[0] + "_seek.mp4"
    cmd = [
        "ffmpeg", "-y", "-v", "error", "-i", path,
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-r", "30", "-g", "30", "-keyint_min", "30",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        "-an",
        out_path,
    ]
    try:
        result = run_proc(cmd, timeout=300)
        if result.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            logger.info("Re-encoded render for seekability",
                        extra={"scene_id": scene_id, "path": out_path})
            return out_path
        if settings.COMPOSITOR_FAIL_CLOSED:
            raise RuntimeError(
                f"Seek re-encode failed (rc={result.returncode}): "
                f"{(result.stderr or '')[:300]}"
            )
        logger.warning("Seek re-encode failed, using original render",
                       extra={"scene_id": scene_id, "rc": result.returncode,
                              "stderr": (result.stderr or "")[:300]})
    except RuntimeError:
        raise
    except Exception as exc:
        if settings.COMPOSITOR_FAIL_CLOSED:
            raise RuntimeError(f"Seek re-encode error: {exc}")
        logger.warning("Seek re-encode error, using original render",
                       extra={"scene_id": scene_id, "error": str(exc)[:200]})
    return path


def _compute_timeout(source: str) -> int:
    """Adaptive timeout: floor + per-play surcharge, capped."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return _TIMEOUT_FLOOR_S
    # Count only self.play(...) — a stray `sound.play()` or similar on another
    # object must not inflate the render budget.
    plays = sum(
        1 for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "play"
        and isinstance(n.func.value, ast.Name)
        and n.func.value.id == "self"
    )
    return min(_TIMEOUT_CEILING_S, max(_TIMEOUT_FLOOR_S,
              _TIMEOUT_FLOOR_S + _TIMEOUT_PER_PLAY_S * plays))


# ─────────────────────────────────────────────────────────────────────────────
# Phase 0: Static visual QA for HyperFrames scenes
# ─────────────────────────────────────────────────────────────────────────────

_PURE_WHITE = re.compile(r'background(?:-color)?\s*:\s*(?:#fff(?:fff)?|white)\b', re.IGNORECASE)
_PURE_BLACK = re.compile(r'background(?:-color)?\s*:\s*(?:#000(?:000)?|black)\b', re.IGNORECASE)
# window.__timelines registration key extraction
_TIMELINE_KEY_RE = re.compile(r'window\.__timelines\[\s*["\']([^"\']+)["\']\s*\]\s*=')
# Composition id on root
_COMP_ID_RE = re.compile(r'data-composition-id\s*=\s*["\']([^"\']+)["\']')


def _check_hf_visual_issues(html_content: str) -> tuple:
    """Static visual QA checks for HyperFrames HTML.

    Catches common LLM anti-patterns that produce blank/invisible scenes:
    - Pure #fff or #000 backgrounds (banned by hf_rules)
    - Clip elements with opacity:0 in inline style (framework ignores it, element stays invisible)
    - Missing background-color on #composition

    Returns (ok: bool, issues: str). Fail-open on parse errors.
    """
    issues = []

    # 1. Pure white/black background on #composition or body
    comp_style_m = re.search(
        r'id\s*=\s*["\']composition["\'][^>]*style\s*=\s*["\']([^"\']+)["\']',
        html_content, re.IGNORECASE | re.DOTALL,
    )
    comp_style = comp_style_m.group(1) if comp_style_m else ""
    body_style_m = re.search(r'<body[^>]*style\s*=\s*["\']([^"\']+)["\']', html_content, re.IGNORECASE)
    body_style = body_style_m.group(1) if body_style_m else ""

    for label, style_block in [("#composition", comp_style), ("body", body_style)]:
        if _PURE_WHITE.search(style_block):
            issues.append(
                f"visual: pure white background (#fff/#ffffff) on {label} — "
                "reads as 'nothing loaded'. Use a tinted near-neutral (e.g. #f4f1ea) per hf_rules."
            )
        if _PURE_BLACK.search(style_block):
            issues.append(
                f"visual: pure black background (#000/#000000) on {label} — "
                "use a dark near-neutral (e.g. #0e1116) instead."
            )

    # 2. Missing explicit background-color on #composition
    if comp_style and "background" not in comp_style.lower():
        issues.append(
            "visual: #composition has no background-color — scene will render transparent/white. "
            "Add an explicit background-color per hf_rules visibility checklist."
        )

    # 3. Clip elements with opacity:0 in inline style (framework overrides CSS opacity on active clips)
    # Two-pass: find all opening tags with data-start, then check each tag's style attr.
    # Order-independent — avoids false-negatives from attribute ordering.
    _tag_with_start = re.compile(r'<[a-zA-Z][^>]*\bdata-start\b[^>]*>', re.IGNORECASE | re.DOTALL)
    _opacity_zero = re.compile(r'\bopacity\s*:\s*0(?!\.\d)', re.IGNORECASE)
    clip_opacity_hits = []
    for tag in _tag_with_start.findall(html_content):
        style_m = re.search(r'\bstyle\s*=\s*["\']([^"\']*)["\']', tag, re.IGNORECASE)
        if style_m and _opacity_zero.search(style_m.group(1)):
            clip_opacity_hits.append(tag)
    for hit in clip_opacity_hits[:3]:  # cap report length
        elem_id_m = re.search(r'\bid\s*=\s*["\']([^"\']+)["\']', hit, re.IGNORECASE)
        elem_id = elem_id_m.group(1) if elem_id_m else "?"
        issues.append(
            f"visual: element '{elem_id}' has data-start AND opacity:0 in inline style — "
            "the HyperFrames framework forces opacity:1 on active clips, so CSS opacity:0 is silently overwritten. "
            "Wrap in a no-data-attr div and animate the wrapper, or use autoAlpha via gsap.from()."
        )

    if issues:
        return False, "\n".join(issues)
    return True, ""


# ─────────────────────────────────────────────────────────────────────────────
# Phase 4: Vision model keyframe inspection for Manim renders
# ─────────────────────────────────────────────────────────────────────────────

_VISION_FRAME_TIMES = (0.25, 0.50, 0.75)  # fraction of duration to sample
_VISION_MAX_IMG_BYTES = 4 * 1024 * 1024


def _video_duration(path: str) -> float | None:
    """Container duration in seconds via ffprobe; None when unprobeable."""
    try:
        r = run_proc(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            timeout=30,
        )
        return float(r.stdout.strip())
    except (ProcTimeout, ValueError, AttributeError):
        return None


# Overshoot tolerance: renders may exceed the narration slot by 20% + 2s before
# they're rejected — beyond that the film shows silent, static video (dead air)
# for the difference, and manim beats drift off the narration entirely.
_DURATION_OVERSHOOT_RATIO = 1.20
_DURATION_OVERSHOOT_SLACK_S = 2.0


def _extract_frame(video_path: str, frac: float, out_path: str) -> bool:
    """Extract one frame at `frac` of video duration into out_path via ffmpeg."""
    try:
        probe = run_proc(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", video_path],
            timeout=30,
        )
        duration = float(probe.stdout.strip())
    except (ProcTimeout, ValueError, AttributeError):
        return False
    seek_s = max(0.1, duration * frac)
    try:
        result = run_proc(
            ["ffmpeg", "-y", "-ss", str(seek_s), "-i", video_path,
             "-vframes", "1", "-q:v", "2", out_path],
            timeout=30,
        )
    except ProcTimeout:
        return False
    return result.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 0


def _data_url_for_frame(path: str) -> str | None:
    try:
        raw = open(path, "rb").read()
        if len(raw) > _VISION_MAX_IMG_BYTES:
            return None
        b64 = base64.b64encode(raw).decode("ascii")
        mime = "image/png" if raw[:4] == b"\x89PNG" else "image/jpeg"
        return f"data:{mime};base64,{b64}"
    except Exception:
        return None


async def _vision_quality_rubric(vision_client, data_url: str, scene_id: int,
                                 narration: str, visual_desc: str) -> tuple:
    """Score one rendered frame against the scene's INTENT (the quality gate).

    The binary broken/empty check certifies renderability; this rubric is the
    content-quality feedback loop: a scene that renders fine but teaches
    nothing, mismatches its narration, or is illegible gets a concrete critique
    that flows back into the code-gen retry prompt. Returns (ok, critique).
    """
    from shared.llm_client import extract_json
    prompt = (
        "You are reviewing one frame of an educational animation scene.\n"
        f"The narration for this scene says: \"{(narration or '')[:600]}\"\n"
        f"The intended visual: \"{(visual_desc or '')[:400]}\"\n\n"
        "Score 1-5 (5 = excellent):\n"
        "- match_narration: does what's on screen SHOW what the narration talks about?\n"
        "- legibility: clear focal point, readable sizes, sane contrast, not cluttered?\n"
        "- adds_insight: does the visual add understanding beyond the words (a real\n"
        "  diagram/graph/relationship), or is it decorative filler?\n"
        "Then name the single worst problem in one sentence (or \"none\").\n\n"
        'Reply with ONLY JSON: {"match_narration": N, "legibility": N, '
        '"adds_insight": N, "worst_problem": "..."}'
    )
    resp = await vision_client.chat.completions.acreate(
        model=settings.IMAGE_EVAL_MODEL,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": data_url}},
                {"type": "text", "text": prompt},
            ],
        }],
        max_tokens=200,
        temperature=0.0,
    )
    import json as _json
    data = _json.loads(extract_json(resp.choices[0].message.content or ""))
    scores = {k: int(data.get(k, 3)) for k in ("match_narration", "legibility", "adds_insight")}
    worst = str(data.get("worst_problem") or "").strip()
    logger.info("Vision quality rubric", extra={"scene_id": scene_id, **scores,
                                                "worst_problem": worst[:160]})
    if min(scores.values()) < 3:
        failing = ", ".join(f"{k}={v}" for k, v in scores.items() if v < 3)
        return False, (
            f"quality: rendered scene scored low on {failing} (1-5 scale). "
            f"Reviewer's worst problem: {worst or 'unspecified'}. "
            "Regenerate so the visual directly SHOWS what the narration explains, "
            "with one clear focal point and readable sizes."
        )
    return True, ""


async def _vision_inspect_manim(render_path: str, scene_id: int,
                                narration: str | None = None,
                                visual_desc: str | None = None) -> tuple:
    """Sample keyframes from a Manim render: (1) binary broken/empty check across
    3 frames, (2) when narration is provided, a quality RUBRIC on the midpoint
    frame (matches-narration / legibility / adds-insight — the content-quality
    feedback loop). Returns (ok: bool, error_message: str). Fail-open on gate
    outage, with a loud gate_skipped log.
    """
    if not settings.VISION_INSPECT_ENABLED:
        return True, ""
    if not settings.IMAGE_EVAL_MODEL:
        return True, ""

    import tempfile
    verdicts = []
    mid_frame_url = None

    try:
        from shared.llm_client import get_llm_client
        vision_client = get_llm_client()
    except Exception as exc:
        logger.warning("Vision inspect: could not get LLM client", extra={"error": str(exc)})
        return True, ""

    with tempfile.TemporaryDirectory() as td:
        for i, frac in enumerate(_VISION_FRAME_TIMES):
            frame_path = os.path.join(td, f"frame_{i}.jpg")
            try:
                ok = await asyncio.to_thread(_extract_frame, render_path, frac, frame_path)
                if not ok:
                    continue
                data_url = _data_url_for_frame(frame_path)
                if not data_url:
                    continue
                if frac == 0.50:
                    mid_frame_url = data_url
                resp = await vision_client.chat.completions.acreate(
                    model=settings.IMAGE_EVAL_MODEL,
                    messages=[{
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": data_url}},
                            {"type": "text", "text": (
                                "This is a frame from an educational animation video. "
                                "Is this frame: (a) ok — has visible, legible content; "
                                "(b) broken — mostly black, white, or corrupt; "
                                "(c) empty — nothing visible; "
                                "(d) cluttered — unreadable due to too many overlapping elements. "
                                "Reply with exactly one word: ok, broken, empty, or cluttered."
                            )},
                        ],
                    }],
                    max_tokens=10,
                    temperature=0.0,
                )
                verdict = (resp.choices[0].message.content or "").strip().lower().split()[0]
                verdicts.append((frac, verdict))
                logger.info("Vision inspect frame", extra={
                    "scene_id": scene_id, "frac": frac, "verdict": verdict,
                })
            except Exception as exc:
                logger.warning("Vision inspect frame failed", extra={
                    "scene_id": scene_id, "frac": frac, "error": str(exc)[:200],
                })

    if not verdicts:
        # We reached the sampling loop (client + model configured, gate ENABLED)
        # yet not one frame yielded a verdict — frame extraction or every vision
        # call failed. This is NOT "tooling unavailable" (that soft-skips
        # earlier with a client-missing log); the gate was asked to run and
        # could not. Fail CLOSED so a broken render can't slip through on a QA
        # outage, and emit a loud, greppable signal.
        logger.error("Vision inspect gate FAILED CLOSED (enabled but no frames sampled)",
                     extra={"scene_id": scene_id, "gate_failed_closed": True})
        return False, (
            "vision: QA gate was enabled but could not sample any frame from the "
            "render (frame extraction or the vision model all failed). Treated as "
            "broken. Verify the render produced a readable video."
        )

    bad = [(f, v) for f, v in verdicts if v in ("broken", "empty", "cluttered")]
    # Fail when a TRUE majority (>50%) of the frames ACTUALLY sampled are bad,
    # relative to what we collected (min 1 collected, guaranteed above) — the
    # old absolute `>= 2` could never fail a 1-frame sample and mis-weighted a
    # 2-frame one.
    if len(bad) > len(verdicts) / 2:
        details = "; ".join(f"{v} at {int(f*100)}%" for f, v in bad)
        labels = sorted({v for _, v in bad})
        return False, f"vision: render appears {'/'.join(labels)} ({details}). Check that construct() produces visible content."

    # Quality rubric (the content-quality gate) — only when the frames pass the
    # binary check AND we know the scene's intent. One extra vision call on the
    # midpoint frame.
    if narration and mid_frame_url:
        try:
            return await _vision_quality_rubric(vision_client, mid_frame_url,
                                                scene_id, narration, visual_desc or "")
        except Exception as exc:
            logger.warning("Vision quality rubric SKIPPED (gate error)",
                           extra={"scene_id": scene_id, "gate_skipped": True,
                                  "error": str(exc)[:200]})
    return True, ""


def _assert_path_in_workspace(code_path: str) -> None:
    """Reject any code_path that resolves outside the job workspace.

    request.code_path is attacker-influenced (it names a file the validator
    then opens and hands to manim). Without containment a '../' or absolute
    path could read arbitrary host files (secrets, /etc/passwd) or feed manim
    a file outside the sandboxed workspace. realpath() collapses symlinks and
    '..' before the prefix check. Raises HTTPException(400) on escape.
    """
    workspace = os.path.realpath(settings.WORKSPACE_DIR)
    resolved = os.path.realpath(code_path)
    if resolved != workspace and not resolved.startswith(workspace + os.sep):
        logger.error("code_path escapes workspace",
                     extra={"code_path": code_path, "resolved": resolved,
                            "workspace": workspace})
        raise HTTPException(
            status_code=400,
            detail="code_path must be inside the job workspace",
        )


def detect_content_type(code_path: str) -> str:
    """Detect content type based on file content.

    Args:
        code_path: Path to the code file

    Returns:
        "manim" for Python/Manim code, "hyperframes" for HTML
    """
    try:
        with open(code_path, "r", encoding="utf-8") as f:
            content = f.read().strip()
        
        # Check for HTML content
        if content.startswith("<!DOCTYPE html") or content.startswith("<html"):
            return "hyperframes"
        
        # Check for Manim import
        if "from manim import" in content or "import manim" in content:
            return "manim"
        
        # Default to manim
        return "manim"
    except Exception as e:
        logger.warning(f"Error detecting content type: {e}, defaulting to manim")
        return "manim"


def validate_hyperframes(code_path: str, scene_id: int = None) -> tuple:
    """Validate HyperFrames HTML structure.

    Checks for valid HTML with at least one clip element (data-start + data-duration),
    and — when scene_id is given — that the composition id and timeline registry key
    both equal "scene-{scene_id}". The compositor mounts the scene with
    data-composition-id="scene-{scene_id}"; the HyperFrames runtime auto-nests the
    scene timeline ONLY when the registered key matches that id, so a mismatch
    renders as a blank scene.
    Returns (success, render_path, error_message).
    """
    try:
        with open(code_path, "r", encoding="utf-8") as f:
            html_content = f.read()

        if not html_content.strip():
            return False, "", "HTML file is empty"

        # Must be valid HTML
        if "<!DOCTYPE html" not in html_content.lower() and "<html" not in html_content.lower():
            return False, "", "File does not appear to be valid HTML"

        # Must have at least one clip with data-start (HyperFrames requirement)
        if "data-start" not in html_content:
            return False, "", "HyperFrames HTML has no elements with data-start attribute"

        if "data-duration" not in html_content:
            return False, "", "HyperFrames HTML has no elements with data-duration attribute"

        if "data-composition-id" not in html_content:
            return False, "", "HyperFrames HTML root is missing data-composition-id"

        if "data-width" not in html_content or "data-height" not in html_content:
            return False, "", "HyperFrames HTML root is missing data-width or data-height"

        if "window.__timelines.push" in html_content:
            return False, "", "HyperFrames HTML must register timelines with window.__timelines['id'] = tl, not push()"

        if "window.__timelines[" not in html_content:
            return False, "", "HyperFrames HTML is missing window.__timelines['id'] registration"

        if scene_id is not None:
            expected = f"scene-{scene_id}"
            comp_ids = re.findall(r'data-composition-id\s*=\s*["\']([^"\']+)["\']', html_content)
            if expected not in comp_ids:
                return False, "", (
                    f"Root data-composition-id must be \"{expected}\" "
                    f"(found: {comp_ids or 'none'}). The compositor mounts this scene "
                    f"by that exact id."
                )
            timeline_keys = re.findall(
                r'window\.__timelines\[\s*["\']([^"\']+)["\']\s*\]\s*=', html_content
            )
            if expected not in timeline_keys:
                return False, "", (
                    f"Timeline must be registered as window.__timelines[\"{expected}\"] "
                    f"(found keys: {timeline_keys or 'none'}). The runtime auto-nests the "
                    f"timeline only when the key equals data-composition-id."
                )
            if "repeat: -1" in html_content or "repeat:-1" in html_content:
                return False, "", "repeat: -1 (infinite) breaks the capture engine — compute finite repeats from data-duration"

        logger.info(f"HyperFrames validation passed for {code_path}")
        # Return the HTML path as render_path — actual rendering happens in compositor
        return True, code_path, ""

    except Exception as e:
        logger.error(f"Error validating HyperFrames: {e}")
        return False, "", str(e)


# _FORBIDDEN_MODULES / _FORBIDDEN_BUILTINS come from shared/security.py (single
# source shared with the code-generator sanitizer — see the import at the top).
# Color constants the LLM keeps inventing that do not exist in Manim CE.
# Value = suggested replacement (fed back to the code-generator on retry).
_INVALID_COLOR_NAMES = {
    "DARK_RED": "RED_E or MAROON_E",
    "DARK_BLUE": "BLUE_E",
    "DARK_GREEN": "GREEN_E",
    "LIGHT_GRAY": "GREY_A or LIGHT_GREY",
    "DARK_GRAY": "GREY_E or DARK_GREY",
}


def _preflight_ast_checks(source: str, scene_id: int) -> tuple:
    """Run lightweight AST checks to detect deprecated/forbidden constructs.

    Includes a security gate that blocks dangerous modules and builtins before
    the code is ever passed to manim render.

    Returns (passed: bool, error_message: str).
    """
    issues = []
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return False, f"SyntaxError at line {e.lineno}: {e.msg}"

    class Checker(ast.NodeVisitor):
        def visit_Import(self, node: ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in _FORBIDDEN_MODULES:
                    issues.append(f"Security: forbidden module import '{alias.name}'")
            self.generic_visit(node)

        def visit_ImportFrom(self, node: ast.ImportFrom):
            if node.module and ("manimlib" in node.module or "manimgl" in node.module):
                issues.append(f"Legacy import detected: from {node.module} - use 'from manim import *' instead")
            if node.module:
                root = node.module.split(".")[0]
                if root in _FORBIDDEN_MODULES:
                    issues.append(f"Security: forbidden from-import '{node.module}'")
            self.generic_visit(node)

        def visit_Name(self, node: ast.Name):
            deprecated = {"SVGMobject", "SVGCircle", "ShowCreation", "ShowCreationThenFadeOut", "VGraph", "there_and_back_once"}
            if node.id in deprecated:
                issues.append(f"Forbidden identifier used: {node.id}")
            if node.id in _INVALID_COLOR_NAMES:
                issues.append(
                    f"Invalid color constant '{node.id}' (not in Manim CE): "
                    f"use {_INVALID_COLOR_NAMES[node.id]}"
                )
            if node.id in _FORBIDDEN_BUILTINS:
                issues.append(f"Security: forbidden builtin '{node.id}'")
            self.generic_visit(node)

        def visit_Call(self, node: ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in _FORBIDDEN_BUILTINS:
                issues.append(f"Security: forbidden builtin call '{node.func.id}()'")
            if isinstance(node.func, ast.Name):
                kwargs = {kw.arg for kw in node.keywords if kw.arg}
                if node.func.id == "Rotating" and ("radians" in kwargs or "axis" in kwargs):
                    issues.append(
                        "Rotating(radians=/axis=) was removed in current Manim CE: "
                        "use self.play(Rotate(mob, angle=...)) or mob.rotate(angle)"
                    )
                if node.func.id in {"Circle", "Arc"} and "arc_length" in kwargs:
                    issues.append(
                        f"{node.func.id}(arc_length=...) is not a valid kwarg: use radius= / angle="
                    )
                if node.func.id == "Code" and "code" in kwargs:
                    issues.append(
                        "Code(code=...) was removed in Manim CE 0.20+: use Text(...) or "
                        "Paragraph(...) for text blocks"
                    )
            # Caption safe-zone: the compositor overlays narration captions in the
            # bottom ~160px (y < -2.8). A bare .to_edge(DOWN) / .to_corner(DL|DR)
            # uses the default buff=0.5, dropping content into that band.
            if isinstance(node.func, ast.Attribute) and node.func.attr in {"to_edge", "to_corner"}:
                first = node.args[0] if node.args else None
                edge = first.id if isinstance(first, ast.Name) else None
                if edge in {"DOWN", "DL", "DR"}:
                    # buff may be the 2nd positional arg (to_edge(edge, buff)) or
                    # a keyword. Resolve from either; only flag when none is
                    # supplied at all, or a resolved numeric buff is < 1.2.
                    buff_kw = next((kw for kw in node.keywords if kw.arg == "buff"), None)
                    pos_buff = node.args[1] if len(node.args) > 1 else None
                    buff_node = buff_kw.value if buff_kw is not None else pos_buff
                    buff_val = (
                        buff_node.value
                        if isinstance(buff_node, ast.Constant)
                        and isinstance(buff_node.value, (int, float))
                        else None
                    )
                    if buff_node is None or (buff_val is not None and buff_val < 1.2):
                        issues.append(
                            f".{node.func.attr}({edge}) without buff>=1.2 places content in the "
                            "caption safe-zone (bottom ~160px reserved). Use buff=1.2 or larger."
                        )
            self.generic_visit(node)

        def visit_Attribute(self, node: ast.Attribute):
            # Reflection/dunder escape: any `.__something__` access lets a
            # name-based denylist be bypassed (().__class__.__bases__[0].
            # __subclasses__(), obj.__globals__['__builtins__'], etc.). The
            # denylist can never enumerate these, so block the whole shape.
            if (len(node.attr) > 4
                    and node.attr.startswith("__")
                    and node.attr.endswith("__")):
                issues.append(
                    f"Security: forbidden dunder attribute access '.{node.attr}' "
                    "(reflection escape)"
                )
            if isinstance(node.value, ast.Name):
                key = f"{node.value.id}.{node.attr}"
                if key == "rate_functions.ease_out":
                    issues.append("Use 'rate_functions.ease_out_sine' instead of 'rate_functions.ease_out'")
                if key == "config.background":
                    issues.append("'config.background' does not exist: use 'config.background_color'")
                if node.value.id in _FORBIDDEN_MODULES:
                    issues.append(f"Security: forbidden module attribute access '{key}'")
            # <anything>.camera.animate is invalid: ThreeDCamera (and camera in
            # general) is not animatable via .animate in CE.
            if node.attr == "animate" and isinstance(node.value, ast.Attribute) and node.value.attr == "camera":
                issues.append(
                    "camera has no '.animate': use self.move_camera(phi=..., theta=...) "
                    "or self.begin_ambient_camera_rotation(...) in a ThreeDScene"
                )
            self.generic_visit(node)

        def visit_Subscript(self, node: ast.Subscript):
            # Block indexing the namespace dicts: globals()['os'],
            # builtins['eval'], __builtins__['__import__'] — the classic way to
            # reach a forbidden name without ever writing it as a bare Name.
            if isinstance(node.value, ast.Name) and node.value.id in {
                "globals", "builtins", "__builtins__"
            }:
                issues.append(
                    f"Security: forbidden subscript on '{node.value.id}' "
                    "(namespace-dict escape)"
                )
            self.generic_visit(node)

    Checker().visit(tree)

    if issues:
        return False, "\n".join(issues)
    return True, ""


def _run_self_test() -> None:
    """Fail-fast on stale images: confirm AST preflight catches known-bad sources."""
    ok, _ = _preflight_ast_checks(_SELF_TEST_BAD_SOURCE, scene_id=0)
    if ok:
        logger.error("STALE IMAGE: AST preflight failed self-test (ShowCreation slipped through)")
        sys.exit(1)
    sec_ok, sec_issues = _preflight_ast_checks(_SELF_TEST_MALICIOUS_SOURCE, scene_id=0)
    if sec_ok or "Security" not in (sec_issues or ""):
        logger.error("STALE IMAGE: security branch of AST preflight failed self-test "
                     f"(import os / eval / getattr slipped through: {sec_issues!r})")
        sys.exit(1)
    # Each escape shape must be rejected on its own — import/subprocess/eval/
    # __import__ and a dunder-traversal reflection escape.
    for src in _SELF_TEST_SECURITY_SOURCES:
        s_ok, s_issues = _preflight_ast_checks(src, scene_id=0)
        if s_ok or "Security" not in (s_issues or ""):
            logger.error("STALE IMAGE: security branch of AST preflight failed self-test "
                         f"(source slipped through): {src!r} -> {s_issues!r}")
            sys.exit(1)
    logger.info("Validator self-test passed: AST preflight active (deprecated + security branches)")


def _warmup_latex() -> None:
    """Render a one-time warmup scene to seed LaTeX/dvisvgm caches.

    Cold-cache renders take ~30s for first Tex; warmup brings it to ~3s.
    Failure is non-fatal — log and continue.
    """
    warmup_dir = os.path.join(settings.WORKSPACE_DIR, "_warmup")
    flag_path = os.path.join(warmup_dir, ".done")
    if os.path.exists(flag_path):
        logger.info("LaTeX warmup skipped (already done)")
        return
    try:
        os.makedirs(warmup_dir, exist_ok=True)
        scene_path = os.path.join(warmup_dir, "warmup_scene.py")
        with open(scene_path, "w", encoding="utf-8") as f:
            f.write(
                "from manim import *\n"
                "class Warmup(Scene):\n"
                "    def construct(self):\n"
                "        self.add(Tex('warmup'))\n"
                "        self.add(MathTex('x^2'))\n"
                "        self.wait(0.1)\n"
            )
        cmd = ["manim", "render", "-ql", "--media_dir", warmup_dir, scene_path, "Warmup"]
        with timed_block(logger, "latex warmup"):
            proc = run_proc(cmd, timeout=180)
        if proc.returncode == 0:
            with open(flag_path, "w") as f:
                f.write("ok")
            logger.info("LaTeX warmup complete")
        else:
            logger.warning(f"LaTeX warmup exit={proc.returncode}; continuing")
    except Exception as e:
        logger.warning(f"LaTeX warmup failed (non-fatal): {e}")


@app.on_event("startup")
async def _on_startup() -> None:
    global _RENDER_SEMAPHORE
    n = settings.VALIDATOR_MAX_CONCURRENT_RENDERS or max(1, (os.cpu_count() or 2) // 2)
    _RENDER_SEMAPHORE = asyncio.Semaphore(n)
    _run_self_test()
    await asyncio.to_thread(_warmup_latex)

@app.post("/validate", response_model=ValidatorResponse)
@traceable(run_type="chain", name="validator.validate")
async def validate_code(request: ValidatorRequest):
    set_log_context(job_id=request.job_id, scene_id=request.scene_id)
    # Containment gate: request.code_path is opened here and by every
    # downstream path (detect_content_type, _validate_manim, _validate_hyperframes,
    # and the manim subprocess). Reject anything resolving outside the workspace
    # BEFORE the first open, so all of them are covered by one check.
    _assert_path_in_workspace(request.code_path)
    # Prefer the script-writer's authoritative content_type (sent by the
    # orchestrator); only fall back to sniffing the file when absent.
    content_type = (request.content_type or "").strip().lower() or detect_content_type(request.code_path)
    logger.info("Validation request", extra={"scene_id": request.scene_id,
                                              "content_type": content_type,
                                              "code_path": request.code_path})

    # Route based on content type
    if content_type == "hyperframes":
        return await _validate_hyperframes(request)
    else:
        return await _validate_manim(request)


async def _lint_hyperframes_remote(code_path: str) -> tuple:
    """Ask the compositor (which ships the hyperframes CLI) to lint the scene.

    Returns (ok, error_message). Permissive when the lint service is
    unreachable — the structural checks above still apply.
    """
    try:
        import httpx
        async with httpx.AsyncClient(timeout=180) as client:
            resp = await client.post(
                f"{settings.ASSEMBLER_URL}/lint", json={"html_path": code_path}
            )
            resp.raise_for_status()
            data = resp.json()
        if data.get("warnings"):
            for w in data["warnings"]:
                logger.warning(f"hyperframes lint warning: {w}")
        if not data.get("ok", True):
            return False, "HyperFrames lint errors:\n" + "\n".join(data.get("errors", []))
        return True, ""
    except Exception as exc:
        if settings.COMPOSITOR_FAIL_CLOSED:
            logger.error(f"hyperframes lint unavailable (fail-closed): {exc}")
            return False, f"HyperFrames lint unavailable: {exc}"
        logger.warning(f"hyperframes lint unavailable ({exc}); proceeding without it")
        return True, ""


async def _validate_hyperframes(request):
    """Validate HyperFrames HTML content."""
    logger.info(f"Validating HyperFrames HTML for scene {request.scene_id}")

    try:
        success, render_path, error = validate_hyperframes(request.code_path, request.scene_id)

        # Structural checks passed — run the real HyperFrames linter for the
        # blank-scene classes regex can't see (opacity no-ops, orphan tweens,
        # nondeterminism). Lint errors fail validation so the code-generator
        # retries with the lint findings (and their FIX hints) as feedback.
        if success:
            lint_ok, lint_error = await _lint_hyperframes_remote(request.code_path)
            if not lint_ok:
                success, render_path, error = False, "", lint_error

        # Phase 0: static visual QA (invisible elements, banned backgrounds)
        if success:
            try:
                with open(request.code_path, "r", encoding="utf-8") as f:
                    html_content = f.read()
                qa_ok, qa_error = _check_hf_visual_issues(html_content)
                if not qa_ok:
                    success, render_path, error = False, "", qa_error
            except Exception as qa_exc:
                logger.warning("Visual QA check failed (non-fatal)", extra={"error": str(qa_exc)[:200]})

        if success:
            return ValidatorResponse(
                scene_id=request.scene_id,
                success=True,
                render_path=render_path
            )
        else:
            return ValidatorResponse(
                scene_id=request.scene_id,
                success=False,
                error_log=error
            )

    except Exception as e:
        logger.error(f"Error validating HyperFrames: {str(e)}")
        raise e


async def _validate_manim(request):
    """Validate Manim Python code."""
    logger.info(f"Validating Manim code for scene {request.scene_id}")

    output_dir = os.path.join(settings.WORKSPACE_DIR, "temp", request.job_id, f"render_scene_{request.scene_id}")
    os.makedirs(output_dir, exist_ok=True)

    scene_class_name = f"Scene{request.scene_id}"

    # Quick syntax check before invoking manim — catches truncated strings, etc.
    try:
        with open(request.code_path, "r", encoding="utf-8") as f:
            source = f.read()
        # Run a lightweight AST preflight to catch deprecated/forbidden constructs
        ok, ast_err = _preflight_ast_checks(source, request.scene_id)
        if not ok:
            logger.error("AST preflight failed", extra={"scene_id": request.scene_id, "error": ast_err})
            return ValidatorResponse(
                scene_id=request.scene_id,
                success=False,
                error_log=ast_err,
            )
        compile(source, request.code_path, "exec")
    except SyntaxError as e:
        logger.error("Python syntax error before render", extra={"scene_id": request.scene_id,
                                                                   "error": str(e), "line": e.lineno})
        return ValidatorResponse(
            scene_id=request.scene_id,
            success=False,
            error_log=f"SyntaxError at line {e.lineno}: {e.msg}\n{e.text}",
        )
    # -qh = 1080p30, matches the 1920x1080 composition canvas so no letterboxing.
    # No --transparent: manim's default dark bg is intentional; keeping it avoids
    # the near-black composition bg bleeding through transparent areas.
    cmd = [
        "manim",
        "render",
        "-qh",
        "--media_dir", output_dir,
        request.code_path,
        scene_class_name
    ]

    timeout_s = _compute_timeout(source)
    try:
        async with _RENDER_SEMAPHORE:
            with timed_block(logger, "manim render", scene_id=request.scene_id):
                logger.info("Running manim", extra={"cmd": " ".join(cmd), "timeout_s": timeout_s})
                returncode, stdout, stderr = await asyncio.to_thread(
                    _run_manim_subprocess, cmd, timeout_s,
                )

        class _Result:
            pass
        process = _Result()
        process.returncode = returncode
        process.stdout = stdout
        process.stderr = stderr
        log_subprocess(logger, cmd, process, label="manim", scene_id=request.scene_id)

        if process.returncode == 0:
            logger.info("Manim render succeeded", extra={"scene_id": request.scene_id})
            search_mov = os.path.join(output_dir, "videos", "*", "*", f"{scene_class_name}.mov")
            search_mp4 = os.path.join(output_dir, "videos", "*", "*", f"{scene_class_name}.mp4")
            mp4_files = glob.glob(search_mov) or glob.glob(search_mp4)

            if mp4_files:
                if any("480p15" in p.replace("\\", "/") for p in mp4_files):
                    logger.error("Manim produced 480p15 output — wrong quality flag", extra={"paths": mp4_files})
                    return ValidatorResponse(
                        scene_id=request.scene_id, success=False,
                        error_log="Manim rendered 480p15 output; validator must run with -qh and produce 1080p30."
                    )
                log_file(logger, "rendered", mp4_files[0], scene_id=request.scene_id)
                logger.info("Render output found", extra={"scene_id": request.scene_id, "path": mp4_files[0]})

                # A/V pacing gate: an overshooting render = dead air in the film
                # (slot is narration-budgeted; extra video plays in silence) and
                # animation beats drifting off the spoken words. Reject with a
                # concrete pacing critique that feeds the retry prompt.
                expected = request.expected_duration_seconds
                if expected and expected > 0:
                    actual = await asyncio.to_thread(_video_duration, mp4_files[0])
                    limit = expected * _DURATION_OVERSHOOT_RATIO + _DURATION_OVERSHOOT_SLACK_S
                    if actual and actual > limit:
                        logger.warning("Render overshoots narration slot",
                                       extra={"scene_id": request.scene_id,
                                              "actual_s": round(actual, 1),
                                              "expected_s": round(float(expected), 1)})
                        return ValidatorResponse(
                            scene_id=request.scene_id, success=False,
                            error_log=(
                                f"pacing: the render runs {actual:.1f}s but the narration slot is "
                                f"{float(expected):.0f}s — the extra {actual - float(expected):.1f}s plays as "
                                "SILENT static video and desyncs every beat from the voiceover. "
                                f"Reduce total run_time + waits to land JUST UNDER {float(expected):.0f}s "
                                "(shorten run_time values and trim self.wait() calls; do not drop content)."
                            ),
                        )

                final_path = await asyncio.to_thread(
                    _reencode_for_seek, mp4_files[0], request.scene_id)

                # Phase 4: vision keyframe inspect + quality rubric (gated on
                # VISION_INSPECT_ENABLED). The rubric critique feeds the
                # code-gen retry prompt via error_log — the regenerate loop.
                vision_ok, vision_error = await _vision_inspect_manim(
                    final_path, request.scene_id,
                    narration=request.narration_text,
                    visual_desc=request.visual_description,
                )
                if not vision_ok:
                    return ValidatorResponse(
                        scene_id=request.scene_id,
                        success=False,
                        error_log=vision_error,
                    )

                return ValidatorResponse(
                    scene_id=request.scene_id,
                    success=True,
                    render_path=final_path
                )
            else:
                return ValidatorResponse(
                    scene_id=request.scene_id,
                    success=False,
                    error_log="Manim render command succeeded but .mp4 file was not found in expected directory structure."
                )
        else:
            logger.warning(f"Render failed for scene {request.scene_id}")
            error_log = process.stderr if process.stderr else process.stdout
            # Log full error for debugging
            logger.error(f"=== MANIM STDERR scene {request.scene_id} ===\n{process.stderr}")
            logger.error(f"=== MANIM STDOUT scene {request.scene_id} ===\n{process.stdout}")
            logger.error(f"=== CODE PATH: {request.code_path} ===")
            # Log the actual code that failed
            try:
                with open(request.code_path, "r") as f:
                    code_content = f.read()
                logger.error(f"=== FAILED CODE scene {request.scene_id} ===\n{code_content}")
            except Exception as read_err:
                logger.error(f"Could not read code file: {read_err}")

            return ValidatorResponse(
                scene_id=request.scene_id,
                success=False,
                error_log=error_log
            )

    except subprocess.TimeoutExpired:
        return ValidatorResponse(
            scene_id=request.scene_id,
            success=False,
            error_log=f"Manim render timed out after {timeout_s} seconds"
        )

    except Exception as e:
        logger.error(f"Error validating code: {str(e)}")
        raise e

@app.get("/health")
def health():
    return {"status": "ok"}
