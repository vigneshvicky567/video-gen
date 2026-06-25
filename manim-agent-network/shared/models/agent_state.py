from typing import TypedDict, Optional, Dict, List
from shared.schemas.common import ScriptResponse

class LangGraphState(TypedDict):
    job_id: str
    topic: str
    status: str
    script: Optional[ScriptResponse]

    # GenerationBrief.model_dump() or None (legacy jobs); read with .get()
    brief: Optional[dict]
    # ScriptWriterResponse.meta passthrough (duration audit, council mode)
    script_meta: Optional[dict]

    # scene_id -> absolute path in workspace
    code_paths: Dict[int, str]
    render_paths: Dict[int, str]
    audio_paths: Dict[int, str]
    # scene_id -> [{"text","start","duration"}] per-sentence audio timing, produced
    # by voiceover (which now runs BEFORE code-gen) and fed to code-gen as a cue
    # sheet so animation beats land on the spoken words.
    audio_segments: Dict[int, list]
    image_paths: Dict[int, List[str]]
    retry_counts: Dict[int, int]
    error_logs: Dict[int, str]
    previous_code: Dict[int, str]

    # scene_ids that exhausted retries and were dropped from a degraded job
    dropped_scenes: List[int]

    # JobStyle.model_dump() set by art_director_node; injected into every scene prompt
    job_style: Optional[dict]

    final_output_path: Optional[str]
    # Length of the prepended branded intro (0.0 / absent when no intro asset);
    # frontend transcript offsets seek times by this (TRN-005).
    intro_duration_seconds: float
    overall_error: Optional[str]
