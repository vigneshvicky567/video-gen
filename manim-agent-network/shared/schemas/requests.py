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
    # Trail of ALL prior failed attempts [{attempt, source, error}] so late
    # retries can avoid repeating every earlier mistake, not just the last one.
    error_history: Optional[List[Dict[str, Any]]] = None
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
    # Authoritative content type from the script-writer ("manim"|"hyperframes").
    # When present the validator routes on it directly instead of sniffing the
    # file contents (the sniff misfires on BOMs / manim-in-comments).
    content_type: Optional[str] = None
    # Scene intent for the vision quality gate: with these present the validator
    # scores rendered frames on a rubric (matches narration / legible / adds
    # insight) instead of only "is it broken" — a scene that renders but teaches
    # nothing gets a critique fed back into the code-gen retry prompt.
    narration_text: Optional[str] = None
    visual_description: Optional[str] = None
    # Planned scene slot (narration-budgeted). A Manim render that overshoots
    # this leaves DEAD AIR in the film (slot = max(video, audio) — the visual
    # keeps going after narration ends). The validator rejects overshoots with
    # a pacing critique instead of shipping the gap.
    expected_duration_seconds: Optional[float] = None

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
    # Per-scene per-sentence TTS cue sheet {scene_id: [{text,start,duration}]} —
    # used to build the soft WebVTT caption track timed to the real audio.
    audio_segments: Optional[Dict[int, list]] = None

class ImageFetcherRequest(BaseModel):
    job_id: str
    scenes: List[ScenePlan]
