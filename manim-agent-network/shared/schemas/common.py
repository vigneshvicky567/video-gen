from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any


class JobStyle(BaseModel):
    """Visual identity for an entire job. Injected into every scene prompt."""
    name: str                # e.g. "Swiss Pulse"
    palette_bg: str          # canvas background
    palette_fg: str          # primary text / foreground
    palette_accent: str      # single accent hue
    font_serif: str          # serif stack (CSS font-family)
    font_sans: str           # sans stack
    easing_entrance: str     # e.g. "power3.out"
    easing_exit: str         # e.g. "power2.in"
    motion_sig: str          # short motion philosophy for this style
    energy: str              # "calm" | "medium" | "high" — drives transition selection


# 8 named styles; auto-picked by art_director_node from topic classification.
VISUAL_STYLES: Dict[str, JobStyle] = {
    "swiss_pulse": JobStyle(
        name="Swiss Pulse",
        palette_bg="#f5f5f0", palette_fg="#1a1a1a", palette_accent="#e63946",
        font_serif="Georgia, serif",
        font_sans="'Helvetica Neue', Arial, sans-serif",
        easing_entrance="power3.out", easing_exit="power2.in",
        motion_sig="grid precision: tight stagger 0.04s, clean cuts, no drift",
        energy="medium",
    ),
    "velvet_standard": JobStyle(
        name="Velvet Standard",
        palette_bg="#1a0a2e", palette_fg="#f0e6ff", palette_accent="#b388ff",
        font_serif="'Times New Roman', serif",
        font_sans="system-ui, sans-serif",
        easing_entrance="sine.out", easing_exit="sine.in",
        motion_sig="slow luxury: 0.8-1.5s tweens, blur crossfade, stillness after motion",
        energy="calm",
    ),
    "deconstructed": JobStyle(
        name="Deconstructed",
        palette_bg="#0d0d0d", palette_fg="#f0f0f0", palette_accent="#ff6b00",
        font_serif="Georgia, serif",
        font_sans="'Courier New', monospace",
        easing_entrance="expo.out", easing_exit="expo.in",
        motion_sig="fragmented: stagger 0.06s, directional pulls, intentional asymmetry",
        energy="high",
    ),
    "maximalist_type": JobStyle(
        name="Maximalist Type",
        palette_bg="#fffbe6", palette_fg="#1a1a00", palette_accent="#ffcc00",
        font_serif="Georgia, 'Times New Roman', serif",
        font_sans="Impact, 'Arial Black', sans-serif",
        easing_entrance="back.out", easing_exit="power4.in",
        motion_sig="bold: weight contrast, scale surprises, stagger 0.03s fast",
        energy="high",
    ),
    "data_drift": JobStyle(
        name="Data Drift",
        palette_bg="#0a0f1c", palette_fg="#e8f4fd", palette_accent="#00d4ff",
        font_serif="Georgia, serif",
        font_sans="'Roboto Mono', 'Courier New', monospace",
        easing_entrance="power2.out", easing_exit="power2.in",
        motion_sig="analytical: stagger 0.05s, chart reveals, fade precision",
        energy="medium",
    ),
    "soft_signal": JobStyle(
        name="Soft Signal",
        palette_bg="#f7f0e8", palette_fg="#2d2820", palette_accent="#7ec8a4",
        font_serif="Georgia, serif",
        font_sans="system-ui, sans-serif",
        easing_entrance="power1.out", easing_exit="power1.in",
        motion_sig="organic: gentle stagger 0.1s, natural drift, warmth",
        energy="calm",
    ),
    "folk_frequency": JobStyle(
        name="Folk Frequency",
        palette_bg="#2d1b0e", palette_fg="#f5e6d3", palette_accent="#e8a87c",
        font_serif="Georgia, 'Palatino Linotype', serif",
        font_sans="system-ui, sans-serif",
        easing_entrance="sine.out", easing_exit="sine.in",
        motion_sig="handcrafted: gentle stagger 0.08s, warm fades, textural depth",
        energy="calm",
    ),
    "shadow_cut": JobStyle(
        name="Shadow Cut",
        palette_bg="#121212", palette_fg="#ffffff", palette_accent="#ff3366",
        font_serif="Georgia, serif",
        font_sans="'Arial Black', Impact, sans-serif",
        easing_entrance="power4.out", easing_exit="power4.in",
        motion_sig="cinematic: hard cuts, dramatic reveals, 0.15-0.3s urgency",
        energy="high",
    ),
}

# Map topic_classification keywords → style key (first match wins)
TOPIC_STYLE_MAP = [
    ("mathemat", "data_drift"),
    ("physics", "data_drift"),
    ("science", "data_drift"),
    ("computer", "swiss_pulse"),
    ("programming", "swiss_pulse"),
    ("software", "swiss_pulse"),
    ("technology", "swiss_pulse"),
    ("engineer", "swiss_pulse"),
    ("economics", "swiss_pulse"),
    ("business", "swiss_pulse"),
    ("history", "folk_frequency"),
    ("humanit", "folk_frequency"),
    ("philosophy", "velvet_standard"),
    ("art", "velvet_standard"),
    ("music", "folk_frequency"),
    ("health", "soft_signal"),
    ("biology", "soft_signal"),
    ("medicine", "soft_signal"),
]


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
