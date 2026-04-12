from pydantic_settings import BaseSettings
import os

class Settings(BaseSettings):
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    WORKSPACE_DIR: str = "/workspace"

    SCRIPT_WRITER_URL: str = os.getenv("SCRIPT_WRITER_URL", "http://script-writer:8001")
    CODE_GENERATOR_URL: str = os.getenv("CODE_GENERATOR_URL", "http://code-generator:8002")
    VALIDATOR_URL: str = os.getenv("VALIDATOR_URL", "http://validator:8003")
    VOICEOVER_URL: str = os.getenv("VOICEOVER_URL", "http://voiceover:8004")
    ASSEMBLER_URL: str = os.getenv("ASSEMBLER_URL", "http://assembler:8005")

    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./jobs.db")

settings = Settings()
