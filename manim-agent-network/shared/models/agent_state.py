from typing import TypedDict, Optional, Dict, List, Any
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
    # Transient-infra failures (service down / 5xx) tracked separately so a brief
    # outage never consumes the content retry budget. See graph._scene_retryable.
    infra_retry_counts: Dict[int, int]
    error_logs: Dict[int, str]
    # FULL failure history per scene [{attempt, source, error}] — later retries
    # send the whole trail to code-gen so attempt 5 learns from attempts 1-4
    # instead of only seeing the latest error.
    error_history: Dict[int, list]
    previous_code: Dict[int, str]

    # scene_ids that exhausted retries and were dropped from a degraded job
    dropped_scenes: List[int]

    # scene_ids the post-assembly film QA sent back for regeneration this round;
    # non-empty routes assembler_node -> code_generator_node, cleared ([]) when
    # the assembler ships the film so the route can't re-fire on stale state.
    qa_retry_scenes: List[int]

    # JobStyle.model_dump() set by art_director_node; injected into every scene prompt
    job_style: Optional[dict]

    final_output_path: Optional[str]
    # Length of the prepended branded intro (0.0 / absent when no intro asset);
    # frontend transcript offsets seek times by this (TRN-005).
    intro_duration_seconds: float
    overall_error: Optional[str]

    # ETA / stage timing (injected by run_pipeline, not by graph nodes)
    # eta_seconds: remaining wall-clock estimate; None = not enough data yet
    eta_seconds: Optional[float]
    # stage -> actual elapsed seconds (filled as each stage completes)
    stage_timings: Dict[str, float]

    # Per-node execution spans appended by every graph node (observability).
    node_timings: List[dict]
