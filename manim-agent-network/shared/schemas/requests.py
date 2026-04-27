from pydantic import BaseModel
from typing import Dict, List, Optional
from shared.schemas.common import ScenePlan, JobState

class ScriptWriterRequest(BaseModel):
    topic: str

class CodeGeneratorRequest(BaseModel):
    scene: ScenePlan
    job_id: str
    error_log: Optional[str] = None # Present if retry
    previous_code: Optional[str] = None # Present if retry

class ValidatorRequest(BaseModel):
    job_id: str
    scene_id: int
    code_path: str

class VoiceoverRequest(BaseModel):
    job_id: str
    scene_id: int
    narration_text: str

class AssemblerRequest(BaseModel):
    job_id: str
    render_paths: dict[int, str]
    audio_paths: dict[int, str]
    scene_plans: List[ScenePlan]
    image_paths: Dict[int, List[str]]
    script_title: str

class ImageFetcherRequest(BaseModel):
    job_id: str
    scenes: List[ScenePlan]
