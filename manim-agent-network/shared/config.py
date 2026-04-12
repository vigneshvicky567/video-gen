from pydantic_settings import BaseSettings
import os

class Settings(BaseSettings):
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    WORKSPACE_DIR: str = "/workspace"
    
    # AI Models - Use Flash for free tier compatibility
    # Note: gemini-3.1-pro requires paid tier
    SCRIPT_WRITER_MODEL: str = os.getenv("SCRIPT_WRITER_MODEL", "gemini-2.5-flash")
    CODE_GENERATOR_MODEL: str = os.getenv("CODE_GENERATOR_MODEL", "gemini-2.5-flash")
    VOICEOVER_MODEL: str = os.getenv("VOICEOVER_MODEL", "gemini-2.5-flash")
    
    # Timeouts
    GEMINI_REQUEST_TIMEOUT_MS: int = int(os.getenv("GEMINI_REQUEST_TIMEOUT_MS", "600000"))
    SERVICE_HTTP_TIMEOUT_SECONDS: float = float(os.getenv("SERVICE_HTTP_TIMEOUT_SECONDS", "900"))
    
    # Voiceover Configuration
    VOICEOVER_PROVIDER: str = os.getenv("VOICEOVER_PROVIDER", "gemini")  # "gemini" or "coqui"
    
    # Coqui TTS Settings (local TTS with voice cloning)
    COQUI_MODEL: str = os.getenv("COQUI_MODEL", "xtts_v2")
    COQUI_REFERENCE_VOICE: str = os.getenv("COQUI_REFERENCE_VOICE", "")
    
    # Service URLs (Docker internal)
    SCRIPT_WRITER_URL: str = os.getenv("SCRIPT_WRITER_URL", "http://script-writer:8001")
    CODE_GENERATOR_URL: str = os.getenv("CODE_GENERATOR_URL", "http://code-generator:8002")
    VALIDATOR_URL: str = os.getenv("VALIDATOR_URL", "http://validator:8003")
    VOICEOVER_URL: str = os.getenv("VOICEOVER_URL", "http://voiceover:8004")
    ASSEMBLER_URL: str = os.getenv("ASSEMBLER_URL", "http://assembler:8005")

settings = Settings()
