from fastapi import FastAPI
from shared.schemas.requests import ValidatorRequest
from shared.schemas.responses import ValidatorResponse
from shared.config import settings
import subprocess
import os
import logging
import glob
import uuid
import time

# LangSmith Tracing
app = FastAPI(title="Validator Service")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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

@app.post("/validate", response_model=ValidatorResponse)
async def validate_code(request: ValidatorRequest):
    logger.info(f"Validating code for job {request.job_id}, scene {request.scene_id}")

    # Detect content type
    content_type = detect_content_type(request.code_path)
    logger.info(f"Scene {request.scene_id} detected as: {content_type}")
    
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

    # Run manim as a subprocess
    cmd = [
        "manim",
        "render",
        "-qm", # Medium quality 720p30 (1280x720 landscape) - changed from -ql (480p15 portrait)
        "--media_dir", output_dir,
        request.code_path,
        scene_class_name
    ]

    try:
        render_start = time.time()
        logger.info(f"Running manim cmd: {' '.join(cmd)}")
        process = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        render_duration = time.time() - render_start
        logger.info(f"Manim returncode={process.returncode} for scene {request.scene_id} in {render_duration:.1f}s")
        
        # Log render trace
        if _tracer:
            try:
                _tracer.update_run(
                    run_id=run_id,
                    inputs={"code_path": request.code_path, "scene_class": scene_class_name},
                    outputs={"return_code": process.returncode},
                    metrics={"render_latency": render_duration}
                )
            except Exception:
                pass

        if process.returncode == 0:
            logger.info(f"Render successful for scene {request.scene_id}")
            # Find the rendered mp4 file. Manim outputs to: media_dir/videos/filename/720p30/SceneName.mp4
            # We use glob because the exact resolution folder depends on the -q flag
            # -qm produces 720p30, -ql produces 480p15, -qh produces 1080p60
            search_path = os.path.join(output_dir, "videos", "*", "*", f"{scene_class_name}.mp4")
            mp4_files = glob.glob(search_path)

            total_duration = time.time() - start_time
            
            if mp4_files:
                if any("480p15" in p.replace("\\", "/") for p in mp4_files):
                    return ValidatorResponse(
                        scene_id=request.scene_id,
                        success=False,
                        error_log="Manim rendered 480p15 output; validator must run with -qm and produce 720p30."
                    )
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
            error_log="Manim render timed out after 120 seconds"
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
