from pydantic import BaseModel
from typing import Optional
from shared.schemas.common import ScriptResponse

class ScriptWriterResponse(BaseModel):
    script: ScriptResponse

class CodeGeneratorResponse(BaseModel):
    scene_id: int
    code_path: str

class ValidatorResponse(BaseModel):
    scene_id: int
    success: bool
    render_path: Optional[str] = None
    error_log: Optional[str] = None

class VoiceoverResponse(BaseModel):
    scene_id: int
    audio_path: str

class AssemblerResponse(BaseModel):
    final_output_path: str
