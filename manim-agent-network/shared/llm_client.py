"""
Shared LLM client factory.

All LLM calls in this project are routed through NVIDIA's OpenAI-compatible
NIM endpoint using DeepSeek models.

Usage:
    from shared.llm_client import get_llm_client
    client = get_llm_client()
    response = client.chat.completions.create(model=settings.SCRIPT_WRITER_MODEL, ...)
"""

from openai import OpenAI
from shared.config import settings


def get_llm_client() -> OpenAI:
    """Return an OpenAI client pointed at NVIDIA NIM."""
    return OpenAI(
        base_url=settings.NVIDIA_BASE_URL,
        api_key=settings.NVIDIA_API_KEY,
    )


def get_openai_tts_client() -> OpenAI:
    """Return a standard OpenAI client for TTS (tts-1-hd).

    NVIDIA NIM has no TTS endpoint, so voiceover still uses OpenAI directly.
    """
    return OpenAI(
        api_key=settings.OPENAI_API_KEY,
        timeout=settings.OPENAI_TIMEOUT_SECONDS,
    )
