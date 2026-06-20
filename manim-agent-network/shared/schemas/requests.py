from pydantic import BaseModel
from typing import Any, Dict, List, Optional
from shared.schemas.common import ScenePlan, JobState, GenerationBrief

class ScriptWriterRequest(BaseModel):
    topic: str
    brief: Optional[GenerationBrief] = None
    job_id: Optional[str] = None

class CodeGeneratorRequest(BaseModel):
    scene: ScenePlan
    job_id: str
    error_log: Optional[str] = None # Present if retry
    previous_code: Optional[str] = None # Present if retry
    render_mode: Optional[str] = None # "hybrid"|"manim"|"hyperframes"; None -> server default
    image_paths: Optional[List[str]] = None # Pre-fetched stock images for HF scenes to compose (Option B)
    job_style: Optional[Dict[str, Any]] = None # JobStyle.model_dump() from art_director_node
    neighbor_context: Optional[Dict[str, Any]] = None # {"prev_visual": str|None, "next_visual": str|None}
    # Per-sentence audio cues for sync: [{"text","start","duration"}] (seconds).
    # Voiceover runs BEFORE code-gen so beats can be timed to real speech.
    audio_cues: Optional[List[Dict[str, Any]]] = None

class ValidatorRequest(BaseModel):
    job_id: str
    scene_id: int
    code_path: str

class VoiceoverRequest(BaseModel):
    job_id: str
    scene_id: int
    narration_text: str
    # None = use the configured KOKORO_SPEED default; an explicit value (incl. 1.0)
    # overrides it. >1 = faster narration. Applies to both Kokoro and edge-tts.
    speed: Optional[float] = None

class AssemblerRequest(BaseModel):
    job_id: str
    render_paths: dict[int, str]
    audio_paths: dict[int, str]
    scene_plans: List[ScenePlan]
    image_paths: Dict[int, List[str]]
    script_title: str
    job_style: Optional[Dict[str, Any]] = None

class ImageFetcherRequest(BaseModel):
    job_id: str
    scenes: List[ScenePlan]
