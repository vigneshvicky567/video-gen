"""Compositor service main FastAPI application.

This service replaces the assembler service and provides:
1. Duration probing with ffprobe
2. LLM-based HyperFrames HTML composition
3. HTML validation
4. HyperFrames rendering to final MP4
"""

import subprocess
from pathlib import Path
from typing import Dict

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from shared.config import settings
from shared.schemas.requests import AssemblerRequest
from shared.schemas.responses import AssemblerResponse

from .duration_prober import compute_scene_timings, AssemblyError
from .llm_composer import compose_html
from .html_validator import validate_composition


app = FastAPI(title="Compositor Service")


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "compositor"}


@app.post("/assemble", response_model=AssemblerResponse)
async def assemble(request: AssemblerRequest):
    """Assemble final video using HyperFrames compositor pipeline.
    
    Pipeline:
    1. Probe media durations with ffprobe
    2. Compute scene start times by accumulation
    3. Generate HyperFrames HTML composition with LLM
    4. Validate HTML and verify media file references
    5. Render final MP4 with npx hyperframes render
    6. Verify output file exists and has size > 0
    
    Args:
        request: AssemblerRequest with job_id, render_paths, audio_paths, 
                 scene_plans, and image_paths
                 
    Returns:
        AssemblerResponse with final_output_path
        
    Raises:
        HTTPException: 500 if any step fails
    """
    try:
        # Step 1: Compute scene timings using duration prober
        scene_timings = compute_scene_timings(
            request.render_paths,
            request.audio_paths
        )
        
        # Step 2: Generate HyperFrames HTML composition using LLM
        html_path = compose_html(
            script_title=request.script_title,
            scene_timings=scene_timings,
            image_paths=request.image_paths,
            job_id=request.job_id
        )
        
        # Step 3: Validate HTML composition
        validate_composition(html_path)
        
        # Step 4: Render final MP4 with HyperFrames
        output_path = Path(settings.WORKSPACE_DIR) / "outputs" / f"{request.job_id}_final.mp4"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # HyperFrames render runs from the project directory (where index.html lives)
        composition_dir = Path(html_path).parent
        index_path = composition_dir / "index.html"

        # Rename composition.html → index.html if needed (only if file exists)
        if Path(html_path).name != "index.html" and Path(html_path).exists():
            Path(html_path).rename(index_path)
        elif not index_path.exists() and Path(html_path).exists():
            Path(html_path).rename(index_path)

        render_command = [
            "npx", "hyperframes", "render",
            "--output", str(output_path),
            "--fps", "30",
            "--quality", "standard",
            "--workers", "1",
        ]

        result = subprocess.run(
            render_command,
            capture_output=True,
            text=True,
            cwd=str(composition_dir)  # run from the project directory
        )
        
        if result.returncode != 0:
            raise AssemblyError(
                f"HyperFrames render failed:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
            )
        
        # Step 5: Verify output file exists and has size > 0
        if not output_path.exists():
            raise AssemblyError(
                f"Output file does not exist after successful render: {output_path}"
            )
        
        if output_path.stat().st_size == 0:
            raise AssemblyError(
                f"Output file has zero size: {output_path}"
            )
        
        return AssemblerResponse(final_output_path=str(output_path))
        
    except AssemblyError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error during assembly: {str(e)}"
        )


@app.exception_handler(AssemblyError)
async def assembly_error_handler(request, exc: AssemblyError):
    """Handle AssemblyError exceptions and return HTTP 500 with detail."""
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc)}
    )
