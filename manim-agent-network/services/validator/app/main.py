from fastapi import FastAPI
from shared.schemas.requests import ValidatorRequest
from shared.schemas.responses import ValidatorResponse
from shared.config import settings
from shared.log import get_logger, set_log_context, timed_block, log_subprocess, log_file, make_request_logging_middleware
from langsmith import traceable
import asyncio
import subprocess
import os
import re
import sys
import glob
import ast

app = FastAPI(title="Validator Service")
app.add_middleware(make_request_logging_middleware("validator"))
logger = get_logger(__name__)

# Initialised in _on_startup inside the running event loop (Python 3.10+ safe).
_RENDER_SEMAPHORE: asyncio.Semaphore = None  # type: ignore[assignment]


def _run_manim_subprocess(cmd: list, timeout_s: int):
    """Run manim in a blocking thread; kill the child process on timeout.

    Returns (returncode, stdout, stderr). Raises subprocess.TimeoutExpired
    after killing the child so the caller can distinguish timeout from error.
    """
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        stdout, stderr = proc.communicate(timeout=timeout_s)
        return proc.returncode, stdout, stderr
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        raise

# Render budget bounds.
_TIMEOUT_FLOOR_S = 90
_TIMEOUT_PER_PLAY_S = 20
_TIMEOUT_CEILING_S = 600

# Self-test source. MUST be flagged by AST preflight; otherwise image is stale.
_SELF_TEST_BAD_SOURCE = (
    "from manim import *\n"
    "config.background = WHITE\n"
    "class S(ThreeDScene):\n"
    "    def construct(self):\n"
    "        self.play(ShowCreation(Circle()), self.camera.animate.set_phi(0))\n"
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
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
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
    plays = sum(
        1 for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "play"
    )
    return min(_TIMEOUT_CEILING_S, max(_TIMEOUT_FLOOR_S,
              _TIMEOUT_FLOOR_S + _TIMEOUT_PER_PLAY_S * plays))


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


_FORBIDDEN_MODULES = {
    "os", "subprocess", "socket", "sys", "importlib", "shutil",
    "pathlib", "ctypes", "multiprocessing", "threading", "pty",
    "signal", "resource", "fcntl", "tempfile", "http", "urllib",
    "ftplib", "smtplib", "telnetlib", "xmlrpc",
}
_FORBIDDEN_BUILTINS = {
    "eval", "exec", "compile", "__import__", "open", "breakpoint",
    "memoryview", "globals", "locals",
}
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

    Checker().visit(tree)

    if issues:
        return False, "\n".join(issues)
    return True, ""


def _run_self_test() -> None:
    """Fail-fast on stale images: confirm AST preflight catches a known-bad source."""
    ok, _ = _preflight_ast_checks(_SELF_TEST_BAD_SOURCE, scene_id=0)
    if ok:
        logger.error("STALE IMAGE: AST preflight failed self-test (ShowCreation slipped through)")
        sys.exit(1)
    logger.info("Validator self-test passed: AST preflight active")


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
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
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
    content_type = detect_content_type(request.code_path)
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
                        error_log="Manim rendered 480p15 output; validator must run with -qh and produce 1080p60."
                    )
                log_file(logger, "rendered", mp4_files[0], scene_id=request.scene_id)
                logger.info("Render output found", extra={"scene_id": request.scene_id, "path": mp4_files[0]})
                final_path = await asyncio.to_thread(
                    _reencode_for_seek, mp4_files[0], request.scene_id)

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
