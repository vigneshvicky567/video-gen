from fastapi import FastAPI
from shared.schemas.requests import CodeGeneratorRequest
from shared.schemas.responses import CodeGeneratorResponse
from shared.config import settings
from google import genai
import os
import logging
from pydantic import BaseModel

app = FastAPI(title="Code Generator Service")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

client = genai.Client(api_key=settings.GEMINI_API_KEY)

class CodeGenOutput(BaseModel):
    python_code: str

@app.post("/generate", response_model=CodeGeneratorResponse)
async def generate_code(request: CodeGeneratorRequest):
    logger.info(f"Generating Manim code for job {request.job_id}, scene {request.scene.scene_id}")

    # Construct prompt based on whether this is a retry or first attempt
    if request.error_log and request.previous_code:
        logger.info(f"Retry attempt for scene {request.scene.scene_id}. Providing error context.")
        prompt = f"""
        You are an expert Python developer using Manim Community Edition (Manim CE).
        You previously wrote Manim code for a scene, but it failed to render.

        Previous Code:
        ```python
        {request.previous_code}
        ```

        Error Log:
        {request.error_log}

        Please fix the code. Ensure you are using correct Manim CE syntax (e.g., `manim` instead of `manimlib`, `MathTex` instead of `TexMobject`, etc.).
        The class name MUST be Scene{request.scene.scene_id}.

        Return ONLY valid python code.
        """
    else:
        prompt = f"""
        You are an expert Python developer using Manim Community Edition (Manim CE).
        Write a complete, valid Manim CE python script for the following scene.

        Narration: {request.scene.narration_text}
        Visual Description: {request.scene.visual_description}

        Requirements:
        1. Import Manim CE: `from manim import *`
        2. Create a Scene class named EXACTLY `Scene{request.scene.scene_id}`.
        3. Keep the animation clean and mathematically accurate.
        4. Do not include any standard file running blocks at the bottom, just the class definition and imports.

        Return ONLY valid python code.
        """

    try:
        response = client.models.generate_content(
            model="gemini-2.5-pro", # Use pro for coding tasks
            contents=prompt,
            config=genai.types.GenerateContentConfig(
                temperature=0.2,
                response_mime_type="application/json",
                response_schema=CodeGenOutput
            )
        )

        code = response.parsed.python_code if response.parsed else json.loads(response.text)["python_code"]

        # Save code to workspace
        temp_dir = os.path.join(settings.WORKSPACE_DIR, "temp", request.job_id)
        os.makedirs(temp_dir, exist_ok=True)

        file_path = os.path.join(temp_dir, f"scene_{request.scene.scene_id}.py")
        with open(file_path, "w") as f:
            f.write(code)

        return CodeGeneratorResponse(
            scene_id=request.scene.scene_id,
            code_path=file_path
        )

    except Exception as e:
        logger.error(f"Error generating code: {str(e)}")
        raise e

@app.get("/health")
def health():
    return {"status": "ok"}
