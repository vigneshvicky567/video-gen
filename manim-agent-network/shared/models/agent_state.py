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
    image_paths: Dict[int, List[str]]
    retry_counts: Dict[int, int]
    error_logs: Dict[int, str]
    previous_code: Dict[int, str]

    # scene_ids that exhausted retries and were dropped from a degraded job
    dropped_scenes: List[int]

    final_output_path: Optional[str]
    overall_error: Optional[str]
