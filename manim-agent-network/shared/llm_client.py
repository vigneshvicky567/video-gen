"""Shared NVIDIA NIM chat client factory."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx

from shared.config import settings


class _NimCompletions:
    def create(self, **kwargs: Any) -> SimpleNamespace:
        payload = {key: value for key, value in kwargs.items() if value is not None}
        url = f"{settings.NVIDIA_BASE_URL.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {settings.NVIDIA_API_KEY}",
            "Content-Type": "application/json",
        }

        with httpx.Client(timeout=settings.NVIDIA_TIMEOUT_SECONDS) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

        choices = []
        for choice in data.get("choices", []):
            message = choice.get("message") or {}
            choices.append(
                SimpleNamespace(
                    message=SimpleNamespace(content=message.get("content")),
                    finish_reason=choice.get("finish_reason"),
                    index=choice.get("index"),
                )
            )

        return SimpleNamespace(
            id=data.get("id"),
            model=data.get("model"),
            choices=choices,
            usage=data.get("usage"),
            raw=data,
        )


class _NimChat:
    def __init__(self) -> None:
        self.completions = _NimCompletions()


class NimClient:
    """Small compatibility wrapper for existing chat completion call sites."""

    def __init__(self) -> None:
        self.chat = _NimChat()


def get_llm_client() -> NimClient:
    return NimClient()
