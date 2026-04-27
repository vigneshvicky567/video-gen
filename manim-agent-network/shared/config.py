from pydantic_settings import BaseSettings
import os


class Settings(BaseSettings):
    # ── NVIDIA NIM (DeepSeek) ─────────────────────────────────────────────────
    # All LLM calls (script writing, code generation, composition, keywords)
    # are routed through NVIDIA's OpenAI-compatible NIM endpoint.
    NVIDIA_API_KEY: str = os.getenv("NVIDIA_API_KEY", "")
    NVIDIA_BASE_URL: str = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")

    # ── OpenAI ────────────────────────────────────────────────────────────────
    # Still used for TTS (tts-1-hd) — NVIDIA NIM has no TTS endpoint.
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")

    WORKSPACE_DIR: str = "/workspace"

    # ── LLM models (all via NVIDIA NIM) ──────────────────────────────────────
    SCRIPT_WRITER_MODEL: str = os.getenv("SCRIPT_WRITER_MODEL", "moonshotai/kimi-k2-instruct")
    CODE_GENERATOR_MODEL: str = os.getenv("CODE_GENERATOR_MODEL", "moonshotai/kimi-k2-instruct")
    COMPOSITOR_LLM_MODEL: str = os.getenv("COMPOSITOR_LLM_MODEL", "moonshotai/kimi-k2-instruct")

    # ── TTS ───────────────────────────────────────────────────────────────────
    VOICEOVER_MODEL: str = os.getenv("VOICEOVER_MODEL", "tts-1-hd")
    VOICEOVER_PROVIDER: str = os.getenv("VOICEOVER_PROVIDER", "openai")  # openai | dia2 | coqui

    # Dia2 local TTS (nari-labs/Dia2-1B fits in ~4GB VRAM)
    DIA2_MODEL: str = os.getenv("DIA2_MODEL", "nari-labs/Dia2-1B")
    DIA2_DEVICE: str = os.getenv("DIA2_DEVICE", "cuda")
    DIA2_DTYPE: str = os.getenv("DIA2_DTYPE", "bfloat16")
    DIA2_CFG_SCALE: float = float(os.getenv("DIA2_CFG_SCALE", "2.0"))
    DIA2_TEMPERATURE: float = float(os.getenv("DIA2_TEMPERATURE", "0.8"))

    # Coqui TTS
    COQUI_MODEL: str = os.getenv("COQUI_MODEL", "xtts_v2")
    COQUI_REFERENCE_VOICE: str = os.getenv("COQUI_REFERENCE_VOICE", "")

    # ── Timeouts ──────────────────────────────────────────────────────────────
    OPENAI_TIMEOUT_SECONDS: int = int(os.getenv("OPENAI_TIMEOUT_SECONDS", "120"))
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
