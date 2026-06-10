from fastapi import FastAPI
from shared.schemas.requests import ValidatorRequest
from shared.schemas.responses import ValidatorResponse
from shared.config import settings
from shared.log import get_logger, set_log_context, timed_block, log_subprocess, log_file, make_request_logging_middleware
import asyncio
import subprocess
import os
import sys
import glob
import uuid
import time
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
    "class S(Scene):\n"
    "    def construct(self):\n"
    "        self.play(ShowCreation(Circle()))\n"
)


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


def validate_hyperframes(code_path: str) -> tuple:
    """Validate HyperFrames HTML structure.
    
    Checks for valid HTML with at least one clip element (data-start + data-duration).
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
            if node.id in _FORBIDDEN_BUILTINS:
                issues.append(f"Security: forbidden builtin '{node.id}'")
            self.generic_visit(node)

        def visit_Call(self, node: ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in _FORBIDDEN_BUILTINS:
                issues.append(f"Security: forbidden builtin call '{node.func.id}()'")
            self.generic_visit(node)

        def visit_Attribute(self, node: ast.Attribute):
            if isinstance(node.value, ast.Name):
                key = f"{node.value.id}.{node.attr}"
                if key == "rate_functions.ease_out":
                    issues.append("Use 'rate_functions.ease_out_sine' instead of 'rate_functions.ease_out'")
                if node.value.id in _FORBIDDEN_MODULES:
                    issues.append(f"Security: forbidden module attribute access '{key}'")
            self.generic_visit(node)

    Checker().visit(tree)

    if issues:
        return False, "\n".join(issues)
    return True, ""

# LangSmith tracer setup
_tracer = None
if os.getenv("LANGSMITH_API_KEY"):
    try:
        import langsmith
        langsmith_client = langsmith.Client()
        _tracer = langsmith_client
        logger.info("LangSmith tracing enabled")
    except ImportError:
        logger.warning("langsmith not installed, tracing disabled")


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
    _RENDER_SEMAPHORE = asyncio.Semaphore(max(1, (os.cpu_count() or 2) // 2))
    _run_self_test()
    await asyncio.to_thread(_warmup_latex)

@app.post("/validate", response_model=ValidatorResponse)
async def validate_code(request: ValidatorRequest):
    set_log_context(job_id=request.job_id, scene_id=request.scene_id)
    content_type = detect_content_type(request.code_path)
    logger.info("Validation request", extra={"scene_id": request.scene_id,
                                              "content_type": content_type,
                                              "code_path": request.code_path})
    
    # Start LangSmith trace
    run_id = str(uuid.uuid4())
    start_time = time.time()
    
    if _tracer:
        try:
            _tracer.create_run(
                name="validator.validate",
                run_type="chain",
                run_id=run_id,
                metadata={
                    "service": "validator",
                    "job_id": request.job_id,
                    "scene_id": request.scene_id,
                    "code_path": request.code_path,
                    "content_type": content_type
                }
            )
        except Exception as e:
            logger.debug(f"LangSmith trace start failed: {e}")

    # Route based on content type
    if content_type == "hyperframes":
        return await _validate_hyperframes(request, run_id, start_time)
    else:
        return await _validate_manim(request, run_id, start_time)


async def _validate_hyperframes(request, run_id, start_time):
    """Validate HyperFrames HTML content."""
    logger.info(f"Validating HyperFrames HTML for scene {request.scene_id}")
    
    try:
        success, render_path, error = validate_hyperframes(request.code_path)
        
        total_duration = time.time() - start_time
        
        if _tracer:
            try:
                _tracer.update_run(
                    run_id=run_id,
                    outputs={"success": success, "render_path": render_path},
                    end_time=time.time(),
                    metrics={"total_latency": total_duration}
                )
            except Exception:
                pass
        
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
        total_duration = time.time() - start_time
        if _tracer:
            try:
                _tracer.update_run(
                    run_id=run_id,
                    error=str(e),
                    end_time=time.time(),
                    metrics={"total_latency": total_duration}
                )
            except Exception:
                pass
        logger.error(f"Error validating HyperFrames: {str(e)}")
        raise e


async def _validate_manim(request, run_id, start_time):
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

            total_duration = time.time() - start_time
            
            if mp4_files:
                if any("480p15" in p.replace("\\", "/") for p in mp4_files):
                    logger.error("Manim produced 480p15 output — wrong quality flag", extra={"paths": mp4_files})
                    return ValidatorResponse(
                        scene_id=request.scene_id, success=False,
                        error_log="Manim rendered 480p15 output; validator must run with -qh and produce 1080p60."
                    )
                log_file(logger, "rendered", mp4_files[0], scene_id=request.scene_id)
                logger.info("Render output found", extra={"scene_id": request.scene_id, "path": mp4_files[0]})
                # Final trace update
                if _tracer:
                    try:
                        _tracer.update_run(
                            run_id=run_id,
                            outputs={"render_path": mp4_files[0], "success": True},
                            end_time=time.time(),
                            metrics={"total_latency": total_duration}
                        )
                    except Exception:
                        pass
                
                return ValidatorResponse(
                    scene_id=request.scene_id,
                    success=True,
                    render_path=mp4_files[0]
                )
            else:
                total_duration = time.time() - start_time
                if _tracer:
                    try:
                        _tracer.update_run(
                            run_id=run_id,
                            outputs={"success": False, "error": "mp4 not found"},
                            end_time=time.time(),
                            metrics={"total_latency": total_duration}
                        )
                    except Exception:
                        pass
                
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
            
            total_duration = time.time() - start_time
            if _tracer:
                try:
                    _tracer.update_run(
                        run_id=run_id,
                        outputs={"success": False, "error": error_log[:500]},
                        end_time=time.time(),
                        metrics={"total_latency": total_duration}
                    )
                except Exception:
                    pass
            
            return ValidatorResponse(
                scene_id=request.scene_id,
                success=False,
                error_log=error_log
            )

    except subprocess.TimeoutExpired:
        total_duration = time.time() - start_time
        if _tracer:
            try:
                _tracer.update_run(
                    run_id=run_id,
                    outputs={"success": False, "error": "timeout"},
                    end_time=time.time(),
                    metrics={"total_latency": total_duration}
                )
            except Exception:
                pass
        
        return ValidatorResponse(
            scene_id=request.scene_id,
            success=False,
            error_log=f"Manim render timed out after {timeout_s} seconds"
        )

    except Exception as e:
        total_duration = time.time() - start_time
        if _tracer:
            try:
                _tracer.update_run(
                    run_id=run_id,
                    error=str(e),
                    end_time=time.time(),
                    metrics={"total_latency": total_duration}
                )
            except Exception:
                pass
        
        logger.error(f"Error validating code: {str(e)}")
        raise e

@app.get("/health")
def health():
    return {"status": "ok"}
