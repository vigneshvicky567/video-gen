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

    # ── TTS ───────────────────────────────────────────────────────────────────
    VOICEOVER_PROVIDER: str = os.getenv("VOICEOVER_PROVIDER", "kokoro")  # kokoro | espeak
    VOICEOVER_FALLBACK_PROVIDER: str = os.getenv("VOICEOVER_FALLBACK_PROVIDER", "espeak")
    ALLOW_ESPEAK_FALLBACK: bool = os.getenv("ALLOW_ESPEAK_FALLBACK", "true").lower() == "true"

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

    # ── External API Keys ─────────────────────────────────────────────────────
    PEXELS_API_KEY: str = os.getenv("PEXELS_API_KEY", "")


settings = Settings()
