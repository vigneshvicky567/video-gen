from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

class ScenePlan(BaseModel):
    scene_id: int
    narration_text: str
    visual_description: str
    estimated_duration_seconds: int

class ScriptResponse(BaseModel):
    title: str
    scenes: List[ScenePlan]

class JobState(BaseModel):
    job_id: str
    topic: str
    status: str = "pending" # pending, script_generation, code_generation, validation, voiceover, assembly, completed, failed
    script: Optional[ScriptResponse] = None

    # Dictionary mapping scene_id to absolute path in the workspace
    code_paths: Dict[int, str] = Field(default_factory=dict)

    # Dictionary mapping scene_id to rendered mp4 path
    render_paths: Dict[int, str] = Field(default_factory=dict)

    # Dictionary mapping scene_id to rendered audio wav path
    audio_paths: Dict[int, str] = Field(default_factory=dict)

    # Dictionary tracking retry counts for code generation per scene
    retry_counts: Dict[int, int] = Field(default_factory=dict)

    # Dictionary mapping scene_id to the latest error log if validation failed
    error_logs: Dict[int, str] = Field(default_factory=dict)

    final_output_path: Optional[str] = None
    overall_error: Optional[str] = None

class GenerationRequest(BaseModel):
    topic: str
