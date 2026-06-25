from pydantic import BaseModel
from typing import Any, Dict, List, Optional
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
    # Per-sentence timing for audio<->animation sync: [{"text","start","duration"}]
    # in seconds, relative to the scene's audio start. Drives the code-gen cue sheet.
    segments: Optional[List[Dict[str, Any]]] = None

class AssemblerResponse(BaseModel):
    final_output_path: str
    # Length of the prepended branded intro (0.0 when no intro asset). The
    # frontend offsets every transcript seek time by this (see TRN-005).
    intro_duration_seconds: float = 0.0

class ImageFetcherResponse(BaseModel):
    image_paths: Dict[int, List[str]]
