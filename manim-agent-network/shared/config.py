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
    NVIDIA_READ_TIMEOUT_SECONDS: int = int(os.getenv("NVIDIA_READ_TIMEOUT_SECONDS", "180"))
    NVIDIA_RPM: int = int(os.getenv("NVIDIA_RPM", "35"))  # requests per minute (stay under 40)

    # ── Anthropic Claude API (commented out — Claude API expired, reverted to NVIDIA) ─
    # ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    # ANTHROPIC_RPM: int = int(os.getenv("ANTHROPIC_RPM", "50"))

    WORKSPACE_DIR: str = "/workspace"

    # ── LLM models (all via NVIDIA NIM) ──────────────────────────────────────
    SCRIPT_WRITER_MODEL: str = os.getenv("SCRIPT_WRITER_MODEL", "moonshotai/kimi-k2-instruct")
    CODE_GENERATOR_MODEL: str = os.getenv("CODE_GENERATOR_MODEL", "qwen/qwen3-coder-480b-a35b-instruct")
    COMPOSITOR_LLM_MODEL: str = os.getenv("COMPOSITOR_LLM_MODEL", "moonshotai/kimi-k2-instruct")
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
    JOB_TIMEOUT_MAX_SECONDS: float = float(os.getenv("JOB_TIMEOUT_MAX_SECONDS", "21600"))
    ASSEMBLER_TIMEOUT_MAX_SECONDS: float = float(os.getenv("ASSEMBLER_TIMEOUT_MAX_SECONDS", "14400"))

    # ── Script council / duration budget ─────────────────────────────────────
    SCRIPT_WORDS_PER_SECOND: float = float(os.getenv("SCRIPT_WORDS_PER_SECOND", "2.2"))
    SCRIPT_DURATION_TOLERANCE: float = float(os.getenv("SCRIPT_DURATION_TOLERANCE", "0.10"))
    COUNCIL_FULL_THRESHOLD_SECONDS: int = int(os.getenv("COUNCIL_FULL_THRESHOLD_SECONDS", "600"))
    COUNCIL_MAX_PARALLEL_WRITERS: int = int(os.getenv("COUNCIL_MAX_PARALLEL_WRITERS", "4"))
    SCRIPT_MAX_SCENES: int = int(os.getenv("SCRIPT_MAX_SCENES", "80"))

    # ── Fan-out / render concurrency ─────────────────────────────────────────
    # 0 = auto (cpu//2) on the validator side.
    VALIDATOR_MAX_CONCURRENT_RENDERS: int = int(os.getenv("VALIDATOR_MAX_CONCURRENT_RENDERS", "0"))
    ORCH_CODEGEN_CONCURRENCY: int = int(os.getenv("ORCH_CODEGEN_CONCURRENCY", "3"))
    ORCH_VOICEOVER_CONCURRENCY: int = int(os.getenv("ORCH_VOICEOVER_CONCURRENCY", "4"))

    # ── Compositor chunked rendering ─────────────────────────────────────────
    COMPOSITOR_CHUNK_THRESHOLD_SECONDS: float = float(os.getenv("COMPOSITOR_CHUNK_THRESHOLD_SECONDS", "480"))
    COMPOSITOR_CHUNK_MAX_SCENES: int = int(os.getenv("COMPOSITOR_CHUNK_MAX_SCENES", "8"))
    COMPOSITOR_CHUNK_MAX_SECONDS: float = float(os.getenv("COMPOSITOR_CHUNK_MAX_SECONDS", "300"))
    COMPOSITOR_CHUNK_TIMEOUT_MAX_SECONDS: float = float(os.getenv("COMPOSITOR_CHUNK_TIMEOUT_MAX_SECONDS", "3600"))

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
    # Off by default; set VISION_INSPECT_ENABLED=true in .env to activate.
    VISION_INSPECT_ENABLED: bool = os.getenv("VISION_INSPECT_ENABLED", "false").lower() == "true"


settings = Settings()
