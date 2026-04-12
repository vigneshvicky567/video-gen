from typing import TypedDict, Optional, Dict
from shared.schemas.common import ScriptResponse

class LangGraphState(TypedDict):
    job_id: str
    topic: str
    status: str
    script: Optional[ScriptResponse]

    # scene_id -> absolute path in workspace
    code_paths: Dict[int, str]
    render_paths: Dict[int, str]
    audio_paths: Dict[int, str]
    retry_counts: Dict[int, int]
    error_logs: Dict[int, str]
    previous_code: Dict[int, str]

    final_output_path: Optional[str]
    overall_error: Optional[str]
