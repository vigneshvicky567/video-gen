"""Shared NVIDIA NIM chat client with async-safe rate limiting.

Rate limit: configurable via NVIDIA_RPM (default 35 requests/minute).
Uses asyncio.Semaphore to cap concurrent in-flight requests rather than
serializing them with sleep — this avoids blocking the event loop and
lets requests run as fast as the API allows up to the concurrency cap.

The semaphore limits concurrent requests per process. With the default
CODE_GENERATOR_WORKERS=1 (single uvicorn worker per container) and
NVIDIA_RPM=35, we allow up to NIM_MAX_CONCURRENT=6 simultaneous requests
which keeps us well under the 40 RPM limit while maximising parallelism.
"""

# ── Anthropic Claude implementation (commented out — Claude API expired, reverted to NVIDIA) ─
# from __future__ import annotations
# import anthropic
#
# class _ClaudeCompletions:
#     def _do_request(self, payload: dict) -> SimpleNamespace:
#         client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
#         model = payload.get("model", "claude-opus-4-7")
#         messages_raw = payload.get("messages", [])
#         max_tokens = payload.get("max_tokens", 16000)
#         system_parts = [m["content"] for m in messages_raw if m["role"] == "system"]
#         conv_messages = [m for m in messages_raw if m["role"] != "system"]
#         response_format = payload.get("response_format", {})
#         if isinstance(response_format, dict) and response_format.get("type") == "json_object":
#             system_parts.append("IMPORTANT: Respond with valid JSON only.")
#         system = "\n\n".join(system_parts) if system_parts else None
#         kwargs = {"model": model, "max_tokens": max_tokens, "messages": conv_messages}
#         if system:
#             kwargs["system"] = system
#         response = client.messages.create(**kwargs)
#         text = next((b.text for b in response.content if b.type == "text"), "")
#         return SimpleNamespace(
#             id=response.id, model=response.model,
#             choices=[SimpleNamespace(message=SimpleNamespace(content=text),
#                                       finish_reason=response.stop_reason, index=0)],
#             usage={"prompt_tokens": response.usage.input_tokens,
#                    "completion_tokens": response.usage.output_tokens},
#             raw=response,
#         )
# class ClaudeClient: ...
# def get_llm_client() -> ClaudeClient: ...
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import asyncio
import os
import threading
import time
from types import SimpleNamespace
from typing import Any

import httpx

from shared.config import settings
from shared.log import get_logger

_logger = get_logger(__name__)

# ── Async concurrency limiter ─────────────────────────────────────────────────
# Limits how many NIM requests are in-flight at once per process.
# This is non-blocking (uses asyncio.Semaphore) so it never stalls the event loop.
# Default: 6 concurrent → at ~10s per call that's ~36 RPM, safely under 40.
_MAX_CONCURRENT: int = int(os.getenv("NIM_MAX_CONCURRENT", "6"))
_sem: asyncio.Semaphore | None = None  # created lazily on first use (needs running loop)

# Sync fallback for non-async callers (e.g. voiceover Kokoro thread)
# NVIDIA_RPM is the PER-KEY budget. Requests round-robin across the key pool, so
# the effective per-process rate is NVIDIA_RPM * n_keys — add keys and throughput
# scales automatically with no retune. See _min_interval().
_RPM: int = int(os.getenv("NVIDIA_RPM", "35"))
_rate_lock = threading.Lock()
_last_request_time: float = 0.0

# ── API key pool ──────────────────────────────────────────────────────────────
# NVIDIA_API_KEYS=key1,key2,key3 spreads requests round-robin across accounts,
# multiplying the per-key RPM budget. On a 429 the request retries on the NEXT
# key immediately-ish instead of sleeping out the full backoff on one key.
# Falls back to the single NVIDIA_API_KEY when the pool var is absent.
_key_lock = threading.Lock()
_key_index = 0


def _api_keys() -> list[str]:
    pool = [k.strip() for k in os.getenv("NVIDIA_API_KEYS", "").split(",") if k.strip()]
    return pool or [settings.NVIDIA_API_KEY]


def _next_key() -> str:
    global _key_index
    keys = _api_keys()
    with _key_lock:
        key = keys[_key_index % len(keys)]
        _key_index += 1
    return key


def _min_interval() -> float:
    """Seconds between request STARTS for this process.

    NVIDIA_RPM is per-key; round-robin spreads requests across the pool, so the
    process can fire NVIDIA_RPM * n_keys per minute while each key still stays
    within NVIDIA_RPM (per process). Add keys to NVIDIA_API_KEYS -> faster, no
    retune. Across N services sharing the same keys, keep NVIDIA_RPM <= 40 / N.
    """
    return 60.0 / (_RPM * max(1, len(_api_keys())))


def _get_semaphore() -> asyncio.Semaphore:
    """Return (or create) the per-event-loop semaphore."""
    global _sem
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None  # not in async context
    # Re-create if the loop changed (e.g. test teardown)
    if _sem is None:
        _sem = asyncio.Semaphore(_MAX_CONCURRENT)
    return _sem


def _acquire_rate_slot_sync() -> None:
    """Blocking rate limiter for sync callers only."""
    global _last_request_time
    with _rate_lock:
        now = time.monotonic()
        wait = _min_interval() - (now - _last_request_time)
        if wait > 0:
            _logger.debug("Rate limiter waiting (sync)", extra={"wait_s": round(wait, 3)})
            time.sleep(wait)
        _last_request_time = time.monotonic()


# Keep old name as alias so any existing callers don't break
_acquire_rate_slot = _acquire_rate_slot_sync


# ── Async rate limiter ─────────────────────────────────────────────────────────
# The semaphore caps *concurrency*, not *rate*. Fast calls (keyword extraction,
# vision vet, short prompts) return in 1-2s, so 6 concurrent slots churn far past
# NVIDIA_RPM and trigger 429s. This min-interval gate paces request STARTS to
# 60/NVIDIA_RPM seconds apart — the async twin of _acquire_rate_slot_sync — so the
# process holds to its RPM budget regardless of how fast individual calls finish.
# ponytail: per-process pacing only; for one shared key across N services, set
# NVIDIA_RPM = account_rpm / N (env), or add keys to NVIDIA_API_KEYS.
_async_rate_lock: asyncio.Lock | None = None
_async_last_request_time: float = 0.0


async def _acquire_rate_slot_async() -> None:
    """Non-blocking min-interval pacer for async callers."""
    global _async_rate_lock, _async_last_request_time
    if _async_rate_lock is None:
        _async_rate_lock = asyncio.Lock()
    async with _async_rate_lock:
        now = time.monotonic()
        wait = _min_interval() - (now - _async_last_request_time)
        if wait > 0:
            _logger.debug("Rate limiter waiting (async)", extra={"wait_s": round(wait, 3)})
            await asyncio.sleep(wait)
        _async_last_request_time = time.monotonic()


# ── NIM completions ───────────────────────────────────────────────────────────

def _normalize_payload_for_backend(payload: dict) -> dict:
    """Adapt the payload to the backend named by NVIDIA_BASE_URL.

    NIM (kimi/qwen) takes `max_tokens` + free `temperature`/`top_p`.
    OpenAI reasoning models (gpt-5.x) renamed `max_tokens` -> `max_completion_tokens`
    and only accept the default temperature (1.0), so we drop sampling overrides
    when pointed at OpenAI. Keyed off the base URL so a NIM<->OpenAI swap in .env
    needs no code change. ponytail: host-substring check, widen if a 3rd backend appears.
    """
    if "openai.com" not in settings.NVIDIA_BASE_URL:
        return payload
    p = dict(payload)
    if "max_tokens" in p:
        p["max_completion_tokens"] = p.pop("max_tokens")
    # Reasoning models reject non-default temperature/top_p — strip them.
    p.pop("temperature", None)
    p.pop("top_p", None)
    return p


class _NimCompletions:
    def _do_request(self, payload: dict) -> SimpleNamespace:
        """Execute one HTTP request to NIM (sync, blocking). Called from thread pool."""
        url = f"{settings.NVIDIA_BASE_URL.rstrip('/')}/chat/completions"
        payload = _normalize_payload_for_backend(payload)
        model = payload.get("model", "?")
        msgs = payload.get("messages", [])
        prompt_chars = sum(len(m.get("content") or "") for m in msgs)
        timeout = httpx.Timeout(
            settings.NVIDIA_TIMEOUT_SECONDS,
            connect=settings.NVIDIA_CONNECT_TIMEOUT_SECONDS,
            read=settings.NVIDIA_READ_TIMEOUT_SECONDS,
        )

        _logger.debug("NIM request", extra={"model": model, "prompt_chars": prompt_chars,
                                             "messages": len(msgs)})

        t0 = time.perf_counter()
        last_exc = None

        n_keys = len(_api_keys())
        max_attempts = 3 + 2 * n_keys  # more keys -> more 429 headroom

        for attempt in range(1, max_attempts + 1):
            try:
                headers = {
                    "Authorization": f"Bearer {_next_key()}",
                    "Content-Type": "application/json",
                }
                with httpx.Client(timeout=timeout) as client:
                    response = client.post(url, headers=headers, json=payload)
                    response.raise_for_status()
                    data = response.json()
                break  # success

            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code

                if status_code == 429 and attempt < max_attempts:
                    retry_after = exc.response.headers.get("retry-after")
                    if retry_after:
                        wait = float(retry_after)
                    elif n_keys > 1:
                        # Next attempt uses a different key — short pause only.
                        wait = 2.0
                    else:
                        wait = min(attempt * 15, 120)
                    _logger.warning("NIM rate limited (429), backing off",
                                    extra={"model": model, "attempt": attempt,
                                           "wait_s": wait, "retry_after": retry_after,
                                           "key_pool": n_keys})
                    time.sleep(wait)
                    last_exc = exc
                    continue

                if status_code in (502, 503, 504) and attempt < 3:
                    wait = attempt * 5
                    _logger.warning("NIM server error, retrying",
                                    extra={"model": model, "status": status_code,
                                           "attempt": attempt, "wait_s": wait})
                    time.sleep(wait)
                    last_exc = exc
                    continue

                _logger.error("NIM HTTP error", extra={"model": model,
                                                        "status": status_code,
                                                        "body": exc.response.text[:400]})
                raise

            except httpx.ReadTimeout as exc:
                if attempt < 3:
                    wait = attempt * 5
                    _logger.warning("NIM read timeout, retrying",
                                    extra={"model": model, "attempt": attempt, "wait_s": wait})
                    time.sleep(wait)
                    last_exc = exc
                    continue
                raise

            except httpx.RequestError as exc:
                if attempt < 3:
                    wait = attempt * 3
                    _logger.warning("NIM request error, retrying",
                                    extra={"model": model, "attempt": attempt,
                                           "wait_s": wait, "error": str(exc)})
                    time.sleep(wait)
                    last_exc = exc
                    continue
                _logger.error("NIM request error", extra={"model": model, "error": str(exc)})
                raise
        else:
            raise last_exc

        elapsed = time.perf_counter() - t0
        usage = data.get("usage") or {}
        _logger.info("NIM response", extra={
            "model": model,
            "elapsed_s": round(elapsed, 3),
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "finish_reason": (data.get("choices") or [{}])[0].get("finish_reason"),
        })

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

    def create(self, **kwargs: Any) -> SimpleNamespace:
        """Sync entry point — used by services that call from sync context."""
        payload = {k: v for k, v in kwargs.items() if v is not None}
        _acquire_rate_slot_sync()
        return self._do_request(payload)

    async def acreate(self, **kwargs: Any) -> SimpleNamespace:
        """Async entry point — acquires semaphore then offloads HTTP to thread pool.

        This never blocks the event loop: the semaphore limits concurrency and
        asyncio.to_thread runs the blocking HTTP call in a worker thread.
        """
        payload = {k: v for k, v in kwargs.items() if v is not None}
        sem = _get_semaphore()
        if sem is not None:
            async with sem:
                await _acquire_rate_slot_async()   # pace starts to NVIDIA_RPM
                return await asyncio.to_thread(self._do_request, payload)
        else:
            # Fallback: run in thread without semaphore
            await _acquire_rate_slot_async()
            return await asyncio.to_thread(self._do_request, payload)


class _NimChat:
    def __init__(self) -> None:
        self.completions = _NimCompletions()


class NimClient:
    """Thin wrapper keeping the same interface as the OpenAI SDK client."""

    def __init__(self) -> None:
        self.chat = _NimChat()


def get_llm_client() -> NimClient:
    return NimClient()
