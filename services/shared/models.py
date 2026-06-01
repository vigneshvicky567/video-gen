from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

class SceneData(BaseModel):
    scene_id: str
    description: str
    narration: str
    manim_code: Optional[str] = None
    rendered_video_path: Optional[str] = None
    voiceover_audio_path: Optional[str] = None
    assembled_video_path: Optional[str] = None
    status: str = "pending"
    errors: List[str] = Field(default_factory=list)
    retry_count: int = 0

class PipelineState(BaseModel):
    user_prompt: str
    scenes: List[SceneData] = Field(default_factory=list)
    final_video_path: Optional[str] = None
    status: str = "initialized"
    global_errors: List[str] = Field(default_factory=list)

class ScriptRequest(BaseModel):
    prompt: str

class ScriptResponse(BaseModel):
    scenes: List[SceneData]

class CodeGenRequest(BaseModel):
    scene_id: str
    description: str
    narration: str
    previous_code: Optional[str] = None
    error_logs: Optional[str] = None

class CodeGenResponse(BaseModel):
    manim_code: str

class ValidationRequest(BaseModel):
    scene_id: str
    manim_code: str

class ValidationResponse(BaseModel):
    success: bool
    video_path: Optional[str] = None
    error_log: Optional[str] = None

class VoiceoverRequest(BaseModel):
    scene_id: str
    narration: str

class VoiceoverResponse(BaseModel):
    audio_path: str

class AssembleRequest(BaseModel):
    scenes: List[Dict[str, str]] # [{'video_path': '...', 'audio_path': '...'}]

class AssembleResponse(BaseModel):
    final_video_path: str

class ReviewRequest(BaseModel):
    video_path: str

class ReviewResponse(BaseModel):
    is_valid: bool
    duration: float
    issues: List[str]
