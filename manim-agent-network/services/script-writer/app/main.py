from fastapi import FastAPI
from shared.schemas.requests import ScriptWriterRequest
from shared.schemas.responses import ScriptWriterResponse
from shared.schemas.common import ScriptResponse
from shared.config import settings
from google import genai
from google.genai.types import GenerateContentConfig, HttpOptions
import json
import logging

app = FastAPI(title="Script Writer Service")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Gemini Client
client = genai.Client(
    api_key=settings.GEMINI_API_KEY,
    http_options=HttpOptions(timeout=settings.GEMINI_REQUEST_TIMEOUT_MS),
)

@app.post("/generate", response_model=ScriptWriterResponse)
async def generate_script(request: ScriptWriterRequest):
    logger.info(f"Generating script for topic: {request.topic}")

    prompt = f"""
    You are an expert technical director and script writer for mathematical and technical animations.
    Create a highly detailed script and scene-by-scene breakdown for a Manim CE animation about: {request.topic}.

    Break the topic down into 2-5 distinct scenes.
    For each scene, provide:
    1. A clear narration text that will be spoken via Text-to-Speech.
    2. A detailed visual description of what should happen in the Manim CE animation. Be specific about shapes, text, formulas, and animations (e.g., FadeIn, Transform).
    3. An estimated duration in seconds.
    """

    try:
        response = client.models.generate_content(
            model=settings.SCRIPT_WRITER_MODEL,
            contents=prompt,
            config=GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ScriptResponse,
                temperature=0.7,
            )
        )

        script_data = response.parsed
        if not script_data:
            # Fallback if parsed is empty
            script_dict = json.loads(response.text)
            script_data = ScriptResponse(**script_dict)

        logger.info(f"Script generated successfully with {len(script_data.scenes)} scenes.")
        return ScriptWriterResponse(script=script_data)

    except Exception as e:
        logger.error(f"Error generating script: {str(e)}")
        raise e

@app.get("/health")
def health():
    return {"status": "ok"}
