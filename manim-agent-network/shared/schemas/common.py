from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

class ScenePlan(BaseModel):
    scene_id: int
    title: Optional[str] = None          # Short scene title shown in the title bar
    narration_text: str
    visual_description: str
    estimated_duration_seconds: int
    content_type: Optional[str] = None  # "hyperframes" or "manim"

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

class SceneTimingRecord(BaseModel):
    scene_id: int
    render_path: str
    audio_path: str
    actual_video_duration_seconds: float
    actual_audio_duration_seconds: float
    start_time_seconds: float

class BriefAnswer(BaseModel):
    question_id: str
    selected: List[str] = Field(default_factory=list)
    custom_text: Optional[str] = None

class GenerationBrief(BaseModel):
    target_duration_seconds: int = Field(ge=60, le=2400)
    max_duration_seconds: Optional[int] = None  # analyzer cap, echoed for server-side clamp
    is_study_material: bool = False
    audience_level: Optional[str] = None
    focus_areas: List[str] = Field(default_factory=list)
    visual_style: Optional[str] = None
    pacing: Optional[str] = None
    answers: List[BriefAnswer] = Field(default_factory=list)

class QuestionOption(BaseModel):
    label: str
    description: str = ""

class AnalyzeQuestion(BaseModel):
    id: str
    question: str
    header: str
    options: List[QuestionOption]
    multi_select: bool = False
    allows_custom: bool = True

class AnalyzeRequest(BaseModel):
    topic: str

class TopicAnalysis(BaseModel):
    topic: str
    feasibility_summary: str
    recommended_duration_seconds: int
    max_duration_seconds: int
    duration_presets: List[int]            # seconds, e.g. [180, 300, 600, 900]
    is_study_material: bool
    topic_classification: str
    questions: List[AnalyzeQuestion]       # 3-5, always includes a "duration" question
    degraded: bool = False                 # True when LLM analysis failed -> static defaults

class GenerationRequest(BaseModel):
    topic: str
    brief: Optional[GenerationBrief] = None
    # "hybrid" (per-scene auto-pick), "manim", or "hyperframes". None -> server default.
    render_mode: Optional[str] = None
