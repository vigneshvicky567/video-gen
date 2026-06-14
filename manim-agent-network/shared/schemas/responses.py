from pydantic import BaseModel
from typing import Dict, List, Optional
from shared.schemas.common import ScriptResponse

class ScriptWriterResponse(BaseModel):
    script: ScriptResponse
    # {"mode": "single"|"council", "duration_audit": {...}, "warnings": [...]}
    meta: Optional[dict] = None

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
    provider_used: Optional[str] = None
    fallback_used: bool = False
    warning: Optional[str] = None

class AssemblerResponse(BaseModel):
    final_output_path: str

class ImageFetcherResponse(BaseModel):
    image_paths: Dict[int, List[str]]
