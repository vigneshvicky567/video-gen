import os
import json
from fastapi import FastAPI, HTTPException
import google.generativeai as genai
from pydantic import BaseModel
from typing import List

# Assume models are accessible or copy them locally if needed
from services.shared.models import ScriptRequest, ScriptResponse, SceneData

app = FastAPI(title="Script Writer Service")

# Configure Gemini
api_key = os.environ.get("GEMINI_API_KEY")
if api_key:
    genai.configure(api_key=api_key)

class SceneFormat(BaseModel):
    scene_id: str
    description: str
    narration: str

class ScriptFormat(BaseModel):
    scenes: list[SceneFormat]

@app.post("/generate_script", response_model=ScriptResponse)
async def generate_script(request: ScriptRequest):
    if not api_key:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY not set")

    prompt = f"""
    You are an expert scriptwriter for mathematical and educational animations (like 3Blue1Brown).
    Break down the following topic into a logical sequence of Manim scenes.
    For each scene, provide:
    1. A unique scene_id (e.g., 'scene_1_intro')
    2. A visual description of what happens in the scene (for the Manim coder).
    3. The voiceover narration script for that scene.

    Topic: {request.prompt}

    Output JSON exactly matching this format:
    {{
        "scenes": [
            {{
                "scene_id": "...",
                "description": "...",
                "narration": "..."
            }}
        ]
    }}
    """

    try:
        model = genai.GenerativeModel('gemini-1.5-pro-latest')
        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
            )
        )

        result_dict = json.loads(response.text)

        scenes_data = []
        for s in result_dict.get("scenes", []):
            scenes_data.append(SceneData(
                scene_id=s["scene_id"],
                description=s["description"],
                narration=s["narration"]
            ))

        return ScriptResponse(scenes=scenes_data)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health():
    return {"status": "ok"}
