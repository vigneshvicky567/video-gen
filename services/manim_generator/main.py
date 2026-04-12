import os
import re
from fastapi import FastAPI, HTTPException
import google.generativeai as genai

from services.shared.models import CodeGenRequest, CodeGenResponse

app = FastAPI(title="Manim Generator Service")

api_key = os.environ.get("GEMINI_API_KEY")
if api_key:
    genai.configure(api_key=api_key)

def extract_python_code(text: str) -> str:
    # Match python code blocks
    pattern = r"```python(.*?)```"
    matches = re.findall(pattern, text, re.DOTALL)
    if matches:
        return matches[0].strip()
    return text.strip()

@app.post("/generate_code", response_model=CodeGenResponse)
async def generate_code(request: CodeGenRequest):
    if not api_key:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY not set")

    system_instruction = """
    You are an expert Manim Community Edition (CE) developer.
    Your task is to write a self-contained Python script using Manim CE to render the described scene.

    CRITICAL RULES:
    1. Only use Manim CE syntax (from manim import *).
    2. The script must contain exactly one class that inherits from Scene or 3DScene.
    3. Ensure the class is named `GeneratedScene`.
    4. Do not include any placeholder or pseudo-code.
    5. The animation timing should roughly match the length of the narration.
    6. Return ONLY the raw Python code. Do not wrap it in markdown block unless necessary, but code extraction will handle it.
    """

    prompt = f"""
    Scene ID: {request.scene_id}
    Visual Description: {request.description}
    Narration (for timing context): {request.narration}
    """

    if request.error_logs and request.previous_code:
        prompt += f"""

    The previous code failed with the following errors. Please fix it.

    Previous Code:
    ```python
    {request.previous_code}
    ```

    Error Logs:
    {request.error_logs}
    """

    try:
        model = genai.GenerativeModel(
            'gemini-1.5-pro-latest',
            system_instruction=system_instruction
        )
        response = model.generate_content(prompt)

        raw_text = response.text
        code = extract_python_code(raw_text)

        return CodeGenResponse(manim_code=code)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health():
    return {"status": "ok"}
