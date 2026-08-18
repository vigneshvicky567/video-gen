from pydantic_settings import BaseSettings
import os


class Settings(BaseSettings):
    # ── NVIDIA NIM ───────────────────────────────────────────────────────────
    # All LLM calls (script writing, code generation, composition, keywords)
    # are routed through NVIDIA's chat endpoint.
    NVIDIA_API_KEY: str = os.getenv("NVIDIA_API_KEY", "")
    NVIDIA_BASE_URL: str = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
    NVIDIA_TIMEOUT_SECONDS: int = int(os.getenv("NVIDIA_TIMEOUT_SECONDS", "300"))
    NVIDIA_CONNECT_TIMEOUT_SECONDS: int = int(os.getenv("NVIDIA_CONNECT_TIMEOUT_SECONDS", "10"))
    # read == total by default: a read timeout below the total just wasted the
    # difference (read always fired first). Code-gen overrides both via compose.
    NVIDIA_READ_TIMEOUT_SECONDS: int = int(os.getenv("NVIDIA_READ_TIMEOUT_SECONDS", "300"))
    NVIDIA_RPM: int = int(os.getenv("NVIDIA_RPM", "35"))  # requests per minute (stay under 40)

    # ── Mistral (separate provider, separate quota) — code-gen fallback ──────────
    # When NIM fails/429s, code-gen retries the same call against Mistral (OpenAI-
    # compatible API). Empty key = no fallback (NIM-only). mistral-large-latest is
    # the most capable general model for following the big HF/Manim rulesets.
    MISTRAL_API_KEY: str = os.getenv("MISTRAL_API_KEY", "")
    MISTRAL_BASE_URL: str = os.getenv("MISTRAL_BASE_URL", "https://api.mistral.ai/v1")
    MISTRAL_MODEL: str = os.getenv("MISTRAL_MODEL", "mistral-large-latest")

    # ── Anthropic Claude API ──────────────────────────────────────────────────
    # Opus 4.8: 1M ctx, adaptive thinking only (budget_tokens 400s). Concurrency
    # is client-side — the API has no native knob; cap in-flight calls with a
    # semaphore (mirrors NIM_MAX_CONCURRENT in shared/llm_client.py).
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-8")
    ANTHROPIC_RPM: int = int(os.getenv("ANTHROPIC_RPM", "50"))
    ANTHROPIC_MAX_CONCURRENT: int = int(os.getenv("ANTHROPIC_MAX_CONCURRENT", "5"))

    WORKSPACE_DIR: str = "/workspace"

    # ── LLM models (all via NVIDIA NIM) ──────────────────────────────────────
    SCRIPT_WRITER_MODEL: str = os.getenv("SCRIPT_WRITER_MODEL", "moonshotai/kimi-k2-instruct")
    CODE_GENERATOR_MODEL: str = os.getenv("CODE_GENERATOR_MODEL", "qwen/qwen3-coder-480b-a35b-instruct")
    COMPOSITOR_LLM_MODEL: str = os.getenv("COMPOSITOR_LLM_MODEL", "moonshotai/kimi-k2-instruct")
    # Watch-page grounded chat. Wants FAST + cheap (short Q&A over a transcript
    # slice), not the heavy code/script model. Defaults to the small Mistral NIM
    # model (~1s) that the compositor already uses for keywords.
    CHAT_MODEL: str = os.getenv("CHAT_MODEL", "mistralai/mistral-small-4-119b-2603")
    # Optional sampling overrides for the code generator. Reasoning models
    # (e.g. nvidia/nemotron-3-*) want temperature 1.0 / top_p 0.95 and a large
    # max_tokens budget because hidden reasoning tokens count against the
    # completion limit. Empty temperature -> per-path defaults (0.2 manim, 0.6 HF).
    CODE_GENERATOR_TEMPERATURE: str = os.getenv("CODE_GENERATOR_TEMPERATURE", "")
    CODE_GENERATOR_TOP_P: str = os.getenv("CODE_GENERATOR_TOP_P", "")
    CODE_GENERATOR_MAX_TOKENS: int = int(os.getenv("CODE_GENERATOR_MAX_TOKENS", "16384"))
    # Render engine: "hybrid" (default — per-scene auto-pick via content_type),
    # "manim" (force every scene through Manim), or "hyperframes" (force all HTML).
    RENDER_MODE: str = os.getenv("RENDER_MODE", "hybrid")

    # ── TTS ───────────────────────────────────────────────────────────────────
    VOICEOVER_PROVIDER: str = os.getenv("VOICEOVER_PROVIDER", "kokoro")  # kokoro
    # ALL-OFFLINE, ALL-NEURAL fallback chain. Comma-separated, tried in order after
    # the primary. Default: piper — an independent ONNX neural engine that survives a
    # kokoro runtime/phonemizer break (different package, different code path). Both
    # are local, no network. If every provider fails on a scene the orchestrator
    # degrades gracefully (that scene plays without narration) — no robotic espeak.
    # edge_tts (cloud) stays implemented but is NOT in the default offline chain.
    VOICEOVER_FALLBACK_PROVIDER: str = os.getenv("VOICEOVER_FALLBACK_PROVIDER", "piper")
    EDGE_TTS_VOICE: str = os.getenv("EDGE_TTS_VOICE", "en-US-JennyNeural")
    PIPER_MODEL_PATH: str = os.getenv("PIPER_MODEL_PATH", "/models/piper/en_US-lessac-medium.onnx")
    VOICEOVER_MAX_RETRIES: int = int(os.getenv("VOICEOVER_MAX_RETRIES", "3"))
    VOICEOVER_RETRY_BACKOFF_SECONDS: float = float(os.getenv("VOICEOVER_RETRY_BACKOFF_SECONDS", "2.0"))

    # Kokoro ONNX local TTS (CPU-capable, offline)
    KOKORO_MODEL_PATH: str = os.getenv("KOKORO_MODEL_PATH", "/models/kokoro/kokoro-v1.0.int8.onnx")
    KOKORO_VOICES_PATH: str = os.getenv("KOKORO_VOICES_PATH", "/models/kokoro/voices-v1.0.bin")
    KOKORO_VOICE: str = os.getenv("KOKORO_VOICE", "af_sarah")
    KOKORO_SPEED: float = float(os.getenv("KOKORO_SPEED", "1.0"))
    KOKORO_LANG: str = os.getenv("KOKORO_LANG", "en-us")

    # ── Timeouts ──────────────────────────────────────────────────────────────
    SERVICE_HTTP_TIMEOUT_SECONDS: float = float(os.getenv("SERVICE_HTTP_TIMEOUT_SECONDS", "900"))
    # Hard ceiling for a whole job; orchestrator aborts ainvoke past this.
    JOB_WALLCLOCK_TIMEOUT_SECONDS: float = float(os.getenv("JOB_WALLCLOCK_TIMEOUT_SECONDS", "3600"))

    # ── Long-form scaling (see shared/timeouts.py) ────────────────────────────
    JOB_TIMEOUT_BASE_SECONDS: float = float(os.getenv("JOB_TIMEOUT_BASE_SECONDS", "1800"))
    JOB_TIMEOUT_PER_TARGET_MINUTE_SECONDS: float = float(os.getenv("JOB_TIMEOUT_PER_TARGET_MINUTE_SECONDS", "420"))
    # 340 min: strictly under the GitHub Actions job cap (350 min workflow
    # timeout, 360 min hard kill) so the orchestrator aborts cleanly and
    # persists 'failed' while the runner can still flush it to Neon.
    JOB_TIMEOUT_MAX_SECONDS: float = float(os.getenv("JOB_TIMEOUT_MAX_SECONDS", "20400"))
    ASSEMBLER_TIMEOUT_MAX_SECONDS: float = float(os.getenv("ASSEMBLER_TIMEOUT_MAX_SECONDS", "14400"))

    # Writer-stage output format: "markdown" (default — natural prose register,
    # truncation-tolerant parsing) or "json" (legacy). Planner/reviewer verdicts
    # are always JSON regardless.
    SCRIPT_OUTPUT_FORMAT: str = os.getenv("SCRIPT_OUTPUT_FORMAT", "markdown")

    # ── Script council / duration budget ─────────────────────────────────────
    SCRIPT_WORDS_PER_SECOND: float = float(os.getenv("SCRIPT_WORDS_PER_SECOND", "2.2"))
    SCRIPT_DURATION_TOLERANCE: float = float(os.getenv("SCRIPT_DURATION_TOLERANCE", "0.10"))
    # Minimum share of the assembled runtime that must carry narration. Slots
    # are max(video, audio): a script can hit the duration target with inflated
    # estimates while the words fall far short — everything below this ratio is
    # dead air in the final video, so the audit fails and repair runs.
    # 0.80: ~15-20% of runtime without narration is healthy pacing (visual
    # holds, breathing room); below that reads as dead air. Measured live:
    # tuned prompts land ~0.83, the old ones shipped 0.46.
    SCRIPT_MIN_NARRATION_COVERAGE: float = float(os.getenv("SCRIPT_MIN_NARRATION_COVERAGE", "0.80"))
    # Comma-separated ordered fallbacks tried when SCRIPT_WRITER_MODEL fails
    # (unreachable function, provider 4xx/5xx after retries, filtered reply).
    SCRIPT_WRITER_FALLBACK_MODELS: str = os.getenv("SCRIPT_WRITER_FALLBACK_MODELS", "")
    COUNCIL_FULL_THRESHOLD_SECONDS: int = int(os.getenv("COUNCIL_FULL_THRESHOLD_SECONDS", "180"))
    COUNCIL_MAX_PARALLEL_WRITERS: int = int(os.getenv("COUNCIL_MAX_PARALLEL_WRITERS", "4"))
    SCRIPT_MAX_SCENES: int = int(os.getenv("SCRIPT_MAX_SCENES", "80"))

    # ── Scene retry budgets ───────────────────────────────────────────────────
    # MAX_SCENE_RETRIES: content failures (bad code / render error) per scene.
    # MAX_INFRA_RETRIES: node-level retries when a downstream SERVICE is
    # unreachable/5xx — tracked separately so a brief outage never burns the
    # content budget. Each infra retry already carries HTTP-level backoff.
    MAX_SCENE_RETRIES: int = int(os.getenv("MAX_SCENE_RETRIES", "5"))
    MAX_INFRA_RETRIES: int = int(os.getenv("MAX_INFRA_RETRIES", "3"))

    # ── Fan-out / render concurrency ─────────────────────────────────────────
    # Default to cpu//2 (min 2) so BOTH the validator's internal render semaphore
    # AND the orchestrator's render fan-out scale with the box. Previously the
    # orchestrator fan-out fell back to a hard 2 (graph.py "... or 2"), so only 2
    # scenes rendered in parallel even on a 20-core machine while the validator
    # already allowed cpu//2. Override via env.
    VALIDATOR_MAX_CONCURRENT_RENDERS: int = int(os.getenv("VALIDATOR_MAX_CONCURRENT_RENDERS", str(max(2, (os.cpu_count() or 4) // 2))))
    ORCH_CODEGEN_CONCURRENCY: int = int(os.getenv("ORCH_CODEGEN_CONCURRENCY", "3"))
    # Voiceover fan-out. All requests share ONE Kokoro model in the voiceover
    # service, so returns diminish past ~half the cores (model/CPU contention);
    # the bigger win is running Kokoro on the GPU (CUDA provider), not raising
    # this further. Override via env.
    ORCH_VOICEOVER_CONCURRENCY: int = int(os.getenv("ORCH_VOICEOVER_CONCURRENCY", "8"))

    # ── Compositor chunked rendering ─────────────────────────────────────────
    COMPOSITOR_CHUNK_THRESHOLD_SECONDS: float = float(os.getenv("COMPOSITOR_CHUNK_THRESHOLD_SECONDS", "480"))
    COMPOSITOR_CHUNK_MAX_SCENES: int = int(os.getenv("COMPOSITOR_CHUNK_MAX_SCENES", "8"))
    COMPOSITOR_CHUNK_MAX_SECONDS: float = float(os.getenv("COMPOSITOR_CHUNK_MAX_SECONDS", "300"))
    COMPOSITOR_CHUNK_TIMEOUT_MAX_SECONDS: float = float(os.getenv("COMPOSITOR_CHUNK_TIMEOUT_MAX_SECONDS", "3600"))
    # HyperFrames render workers per composition (parallel frame rendering in the
    # headless browser). Browser render is RAM/CPU-heavy, so keep modest on a laptop;
    # 2 is a safe bump from the old hard-coded 1. Override via env.
    COMPOSITOR_RENDER_WORKERS: int = int(os.getenv("COMPOSITOR_RENDER_WORKERS", "2"))
    # Captions: a soft WebVTT track is always emitted (toggleable in the player).
    # BURN_CAPTIONS=true ALSO burns the lower-third into the pixels (old behavior,
    # not toggleable). Default false = soft-only, so viewers can turn CC on/off.
    BURN_CAPTIONS: bool = os.getenv("BURN_CAPTIONS", "false").lower() == "true"

    # ── Final-cut polish: intro/outro concat + music bed (assemble-time ffmpeg) ──
    # Paths point at the read-only /assets mount. Empty = feature off (output is
    # byte-for-byte today's behavior). See spec/spec-design-intro-music-transcript.md.
    INTRO_VIDEO_PATH: str = os.getenv("INTRO_VIDEO_PATH", "")
    OUTRO_VIDEO_PATH: str = os.getenv("OUTRO_VIDEO_PATH", "")
    BG_MUSIC_PATH: str = os.getenv("BG_MUSIC_PATH", "")
    # Directory of BGM files. When set, a track is picked deterministically per job
    # (hash of film filename → index) so the same job always gets the same track.
    # BG_MUSIC_PATH takes precedence if both are set.
    BG_MUSIC_DIR: str = os.getenv("BG_MUSIC_DIR", "")
    BG_MUSIC_VOLUME: float = float(os.getenv("BG_MUSIC_VOLUME", "0.12"))
    BG_MUSIC_FADEOUT_SECONDS: float = float(os.getenv("BG_MUSIC_FADEOUT_SECONDS", "2.0"))

    # ── Service URLs (Docker internal) ────────────────────────────────────────
    SCRIPT_WRITER_URL: str = os.getenv("SCRIPT_WRITER_URL", "http://script-writer:8001")
    CODE_GENERATOR_URL: str = os.getenv("CODE_GENERATOR_URL", "http://code-generator:8002")
    VALIDATOR_URL: str = os.getenv("VALIDATOR_URL", "http://validator:8003")
    VOICEOVER_URL: str = os.getenv("VOICEOVER_URL", "http://voiceover:8004")
    # The live assembler is the COMPOSITOR (HyperFrames HTML pipeline);
    # docker-compose.yml sets ASSEMBLER_URL=http://compositor:8005. The ffmpeg
    # `assembler` service is a legacy Manim-only path kept for reference.
    ASSEMBLER_URL: str = os.getenv("ASSEMBLER_URL", "http://compositor:8005")
    IMAGE_FETCHER_URL: str = os.getenv("IMAGE_FETCHER_URL", "http://image-fetcher:8006")

    # Fail-open by default: when a lint subprocess or a seek re-encode cannot run,
    # the pipeline degrades (passes lint / keeps the original render) rather than
    # blocking the job. Set true to fail-closed — surface those tooling failures
    # as hard errors instead of silently proceeding.
    COMPOSITOR_FAIL_CLOSED: bool = os.getenv("COMPOSITOR_FAIL_CLOSED", "false").lower() == "true"

    # ── External API Keys ─────────────────────────────────────────────────────
    PEXELS_API_KEY: str = os.getenv("PEXELS_API_KEY", "")
    PIXABAY_API_KEY: str = os.getenv("PIXABAY_API_KEY", "")

    # Vision-capable model for the final image-relevance vet (sees the pixels).
    # Empty -> the vision stage is skipped and SigLIP's ranking is used as-is.
    # The running services set this via docker-compose (defaulting to
    # meta/llama-3.2-90b-vision-instruct); the hard default here is empty so the
    # "empty -> skip" contract holds for any import without an env override.
    IMAGE_EVAL_MODEL: str = os.getenv("IMAGE_EVAL_MODEL", "")

    # Phase 4: enable vision model keyframe inspection for Manim renders.
    # On by default; catches layout collisions, clutter, and empty frames in rendered output.
    VISION_INSPECT_ENABLED: bool = os.getenv("VISION_INSPECT_ENABLED", "true").lower() == "true"

    # Post-assembly film QA: ffmpeg blackdetect/freezedetect/silencedetect scan
    # of the assembled film, vision diagnosis of flagged scenes (needs
    # IMAGE_EVAL_MODEL), and a one-shot regeneration round via the code-gen
    # retry loop. On by default; best-effort — never fails an assembly.
    FILM_QA_ENABLED: bool = os.getenv("FILM_QA_ENABLED", "true").lower() == "true"


settings = Settings()


def require_keys(*names: str, any_of: tuple = ()) -> None:
    """Fail-fast startup assertion for per-service credentials.

    Call from a service's FastAPI startup hook with the keys THAT service
    needs. A missing key then kills the container at boot with a clear message
    instead of 401-ing deep inside the first LLM/API call mid-job.
      require_keys("PEXELS_API_KEY")                       # all required
      require_keys(any_of=("NVIDIA_API_KEY", "ANTHROPIC_API_KEY"))  # at least one
    """
    missing = [n for n in names if not getattr(settings, n, "")]
    if missing:
        raise RuntimeError(f"Missing required credentials: {', '.join(missing)}")
    if any_of and not any(getattr(settings, n, "") for n in any_of):
        raise RuntimeError(f"Need at least one of: {', '.join(any_of)}")
