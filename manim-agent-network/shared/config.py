from pydantic_settings import BaseSettings
import os


class Settings(BaseSettings):
    # ── NVIDIA NIM ───────────────────────────────────────────────────────────
    # All LLM calls (script writing, code generation, composition, keywords)
    # are routed through NVIDIA's chat endpoint.
    NVIDIA_API_KEY: str = os.getenv("NVIDIA_API_KEY", "")
    NVIDIA_BASE_URL: str = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
    NVIDIA_TIMEOUT_SECONDS: int = int(os.getenv("NVIDIA_TIMEOUT_SECONDS", "120"))

    WORKSPACE_DIR: str = "/workspace"

    # ── LLM models (all via NVIDIA NIM) ──────────────────────────────────────
    SCRIPT_WRITER_MODEL: str = os.getenv("SCRIPT_WRITER_MODEL", "moonshotai/kimi-k2-instruct")
    CODE_GENERATOR_MODEL: str = os.getenv("CODE_GENERATOR_MODEL", "moonshotai/kimi-k2-instruct")
    COMPOSITOR_LLM_MODEL: str = os.getenv("COMPOSITOR_LLM_MODEL", "moonshotai/kimi-k2-instruct")

    # ── TTS ───────────────────────────────────────────────────────────────────
    VOICEOVER_PROVIDER: str = os.getenv("VOICEOVER_PROVIDER", "dia2")  # dia2 | kokoro
    VOICEOVER_FALLBACK_PROVIDER: str = os.getenv("VOICEOVER_FALLBACK_PROVIDER", "kokoro")
    ALLOW_ESPEAK_FALLBACK: bool = os.getenv("ALLOW_ESPEAK_FALLBACK", "false").lower() == "true"

    # Dia2 local TTS (nari-labs/Dia2-1B fits in ~4GB VRAM)
    DIA2_MODEL: str = os.getenv("DIA2_MODEL", "nari-labs/Dia2-1B")
    DIA2_DEVICE: str = os.getenv("DIA2_DEVICE", "cuda")
    DIA2_DTYPE: str = os.getenv("DIA2_DTYPE", "bfloat16")
    DIA2_CFG_SCALE: float = float(os.getenv("DIA2_CFG_SCALE", "2.0"))
    DIA2_TEMPERATURE: float = float(os.getenv("DIA2_TEMPERATURE", "0.8"))

    # Kokoro ONNX local fallback
    KOKORO_MODEL_PATH: str = os.getenv("KOKORO_MODEL_PATH", "/models/kokoro/kokoro-v1.0.int8.onnx")
    KOKORO_VOICES_PATH: str = os.getenv("KOKORO_VOICES_PATH", "/models/kokoro/voices-v1.0.bin")
    KOKORO_VOICE: str = os.getenv("KOKORO_VOICE", "af_sarah")
    KOKORO_SPEED: float = float(os.getenv("KOKORO_SPEED", "1.0"))
    KOKORO_LANG: str = os.getenv("KOKORO_LANG", "en-us")

    # ── Timeouts ──────────────────────────────────────────────────────────────
    SERVICE_HTTP_TIMEOUT_SECONDS: float = float(os.getenv("SERVICE_HTTP_TIMEOUT_SECONDS", "900"))

    # ── Service URLs (Docker internal) ────────────────────────────────────────
    SCRIPT_WRITER_URL: str = os.getenv("SCRIPT_WRITER_URL", "http://script-writer:8001")
    CODE_GENERATOR_URL: str = os.getenv("CODE_GENERATOR_URL", "http://code-generator:8002")
    VALIDATOR_URL: str = os.getenv("VALIDATOR_URL", "http://validator:8003")
    VOICEOVER_URL: str = os.getenv("VOICEOVER_URL", "http://voiceover:8004")
    ASSEMBLER_URL: str = os.getenv("ASSEMBLER_URL", "http://assembler:8005")
    IMAGE_FETCHER_URL: str = os.getenv("IMAGE_FETCHER_URL", "http://image-fetcher:8006")

    # ── External API Keys ─────────────────────────────────────────────────────
    PEXELS_API_KEY: str = os.getenv("PEXELS_API_KEY", "")


settings = Settings()
