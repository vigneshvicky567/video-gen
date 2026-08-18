"""Shared LLM chat client: NVIDIA NIM + Anthropic Claude + Mistral, routed by model id.

Concurrency model
-----------------
* An asyncio.Semaphore caps concurrent in-flight requests per event loop
  (NIM_MAX_CONCURRENT, default 6). Semaphores are loop-bound, so they are
  keyed by the running loop and re-created when the loop changes (uvicorn
  reload, pytest-asyncio, anyio workers).
* A min-interval pacer spaces request STARTS to 60/(NVIDIA_RPM * n_keys)
  seconds. The pacer reserves a start slot under a cheap threading.Lock and
  sleeps OUTSIDE the lock, so concurrent callers wait in parallel, not in a
  queue. Sync and async callers share one pacing clock.

Error contract
--------------
* LLMEmptyContent — the model returned no usable text (empty content, refusal,
  content filter). Retryable by the caller with a changed prompt.
* LLMTransient — retries for 429/5xx/timeouts were exhausted client-side.
  The original httpx exception is chained as __cause__.
* extract_json(text) — tolerant helper for "JSON mode" replies that arrive
  wrapped in code fences or prose (neither NIM nor Anthropic hard-enforce
  JSON output).
"""

from __future__ import annotations

import asyncio
import os
import random
import re
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from types import SimpleNamespace
from typing import Any

import httpx

from shared.config import settings
from shared.log import get_logger

_logger = get_logger(__name__)


# ── Typed errors ──────────────────────────────────────────────────────────────

class LLMError(Exception):
    """Base class for llm_client errors."""


class LLMEmptyContent(LLMError):
    """Model returned no usable content (empty / refusal / content filter).

    Callers should treat this as a per-attempt failure and retry with the
    same or an adjusted prompt — the request itself succeeded.
    """

    def __init__(self, message: str, finish_reason: str | None = None, model: str | None = None):
        super().__init__(message)
        self.finish_reason = finish_reason
        self.model = model


class LLMTransient(LLMError):
    """Transient transport failure (429/5xx/timeout) after retries exhausted."""


# ── Tolerant JSON extraction ─────────────────────────────────────────────────

_FENCE_RE = re.compile(r"^```[a-zA-Z0-9_-]*\s*|\s*```$", re.MULTILINE)


def extract_json(text: str) -> str:
    """Best-effort slice of the outermost JSON value from an LLM reply.

    Strips markdown code fences, then returns the substring from the first
    '{' or '[' to the last '}' or ']'. Returns the stripped text unchanged if
    no JSON delimiters are found — json.loads will then raise with the real
    content in the error, which is more debuggable than a synthetic message.
    """
    t = _FENCE_RE.sub("", (text or "").strip()).strip()
    starts = [i for i in (t.find("{"), t.find("[")) if i != -1]
    if not starts:
        return t
    start = min(starts)
    end = max(t.rfind("}"), t.rfind("]"))
    return t[start:end + 1] if end > start else t[start:]


# ── Concurrency limiter (per event loop) ─────────────────────────────────────
# Semaphores bind to the loop that created them; cache per loop and prune
# closed loops so test teardown / worker restarts get fresh primitives.
_MAX_CONCURRENT: int = int(os.getenv("NIM_MAX_CONCURRENT", "6"))
_ANTHROPIC_MAX_CONCURRENT: int = int(os.getenv("ANTHROPIC_MAX_CONCURRENT", "5"))

_loop_sems: dict[int, dict[str, Any]] = {}


def _get_semaphore(name: str = "nim") -> asyncio.Semaphore | None:
    """Return the named per-event-loop semaphore, or None outside a loop."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None  # not in async context
    entry = _loop_sems.get(id(loop))
    # Recreate when there is no entry, when the cached loop was closed, or when
    # id(loop) was reused for a *different* live loop (CPython recycles ids of
    # GC'd loops, so a same-id hit can point at the wrong loop after teardown).
    if entry is None or entry["loop"].is_closed() or entry["loop"] is not loop:
        # Prune entries whose loops are gone before adding a fresh one.
        for key in [k for k, v in _loop_sems.items() if v["loop"].is_closed()]:
            del _loop_sems[key]
        entry = {
            "loop": loop,
            "nim": asyncio.Semaphore(_MAX_CONCURRENT),
            "anthropic": asyncio.Semaphore(_ANTHROPIC_MAX_CONCURRENT),
        }
        _loop_sems[id(loop)] = entry
    return entry[name]


# ── Rate pacer (shared clock, sleep outside the lock) ────────────────────────
# NVIDIA_RPM is the PER-KEY budget. Requests round-robin across the key pool,
# so the effective per-process rate is NVIDIA_RPM * n_keys — add keys and
# throughput scales automatically with no retune. See _min_interval().
_RPM: int = int(os.getenv("NVIDIA_RPM", "35"))
_pace_lock = threading.Lock()   # guards only the slot arithmetic (never held while sleeping)
_next_slot_time: float = 0.0

# ── API key pool ──────────────────────────────────────────────────────────────
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

    Round-robin spreads requests across the key pool, so the process can fire
    NVIDIA_RPM * n_keys per minute while each key stays within NVIDIA_RPM.
    Across N services sharing the same keys, keep NVIDIA_RPM <= 40 / N.
    """
    return 60.0 / (_RPM * max(1, len(_api_keys())))


def _reserve_rate_slot() -> float:
    """Reserve the next request-start slot; return seconds until it opens.

    The lock is held only for the arithmetic. Each caller gets its own slot
    (previous slot + interval) and sleeps toward it independently, so N
    waiters sleep concurrently instead of queuing behind one another.
    """
    global _next_slot_time
    with _pace_lock:
        now = time.monotonic()
        slot = max(now, _next_slot_time)
        _next_slot_time = slot + _min_interval()
        return slot - now


def _acquire_rate_slot_sync() -> None:
    wait = _reserve_rate_slot()
    if wait > 0:
        _logger.debug("Rate limiter waiting (sync)", extra={"wait_s": round(wait, 3)})
        time.sleep(wait)


async def _acquire_rate_slot_async() -> None:
    wait = _reserve_rate_slot()
    if wait > 0:
        _logger.debug("Rate limiter waiting (async)", extra={"wait_s": round(wait, 3)})
        await asyncio.sleep(wait)


# Keep old name as alias so any existing callers don't break
_acquire_rate_slot = _acquire_rate_slot_sync


# ── Retry policy ─────────────────────────────────────────────────────────────
# One named budget for every transient class (5xx, timeouts, connect errors).
# 429 gets extra headroom when a key pool exists (the next attempt lands on a
# different key), but never less than the transient budget.
_TRANSIENT_MAX_ATTEMPTS: int = int(os.getenv("LLM_TRANSIENT_MAX_ATTEMPTS", "4"))


def _parse_retry_after(value: str | None) -> float | None:
    """Parse a Retry-After header: seconds or HTTP-date, defensively."""
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        dt = parsedate_to_datetime(value)
        return max(0.0, (dt - datetime.now(timezone.utc)).total_seconds())
    except Exception:
        return None


def _jitter(wait: float) -> float:
    return wait * random.uniform(1.0, 1.25)


# stop/finish reasons that mean the reply is unusable, across both backends:
#   OpenAI/NIM:  "length" (truncated), "content_filter"
#   Anthropic:   "max_tokens" (truncated), "refusal"
_TRUNCATED_REASONS = frozenset({"length", "max_tokens"})
_BLOCKED_REASONS = frozenset({"refusal", "content_filter"})


def _check_content(content: str | None, finish_reason: str | None, model: str) -> None:
    """Raise LLMEmptyContent on unusable replies instead of returning them.

    Refusals, content-filter stops, empty content, and truncation all raise
    LLMEmptyContent (a per-attempt, retryable failure per the module error
    contract). Truncation is raised because a cut-off reply yields invalid JSON
    downstream and a silently-truncated plain-text reply is a latent bug;
    callers retry (e.g. with a larger max_tokens or a tighter prompt). The two
    backends spell these differently — see _TRUNCATED_REASONS / _BLOCKED_REASONS.
    """
    if finish_reason in _BLOCKED_REASONS:
        raise LLMEmptyContent(
            f"model {model} returned finish_reason={finish_reason}",
            finish_reason=finish_reason, model=model,
        )
    if not content or not str(content).strip():
        raise LLMEmptyContent(
            f"model {model} returned empty content (finish_reason={finish_reason})",
            finish_reason=finish_reason, model=model,
        )
    if finish_reason in _TRUNCATED_REASONS:
        _logger.warning("LLM reply truncated at max_tokens",
                        extra={"model": model, "finish_reason": finish_reason})
        raise LLMEmptyContent(
            f"model {model} reply truncated at max_tokens (finish_reason={finish_reason})",
            finish_reason=finish_reason, model=model,
        )


# ── OpenAI-compatible HTTP backends (NIM, Mistral) ───────────────────────────

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
    """NVIDIA NIM chat completions (OpenAI-shaped HTTP)."""

    _name = "NIM"

    def _base_url(self) -> str:
        return settings.NVIDIA_BASE_URL

    def _auth_key(self) -> str:
        return _next_key()

    def _n_keys(self) -> int:
        return len(_api_keys())

    def _adapt_payload(self, payload: dict) -> dict:
        return _normalize_payload_for_backend(payload)

    def _do_request(self, payload: dict) -> SimpleNamespace:
        """Execute one HTTP request (sync, blocking). Called from thread pool."""
        url = f"{self._base_url().rstrip('/')}/chat/completions"
        payload = self._adapt_payload(payload)
        model = payload.get("model", "?")
        msgs = payload.get("messages", [])
        prompt_chars = sum(len(m.get("content") or "") for m in msgs
                           if isinstance(m.get("content"), str))
        timeout = httpx.Timeout(
            settings.NVIDIA_TIMEOUT_SECONDS,
            connect=settings.NVIDIA_CONNECT_TIMEOUT_SECONDS,
            read=settings.NVIDIA_READ_TIMEOUT_SECONDS,
        )

        _logger.debug("%s request" % self._name,
                      extra={"model": model, "prompt_chars": prompt_chars,
                             "messages": len(msgs)})

        t0 = time.perf_counter()
        last_exc: Exception | None = None

        n_keys = self._n_keys()
        # 429s rotate to the next key, so more keys buy more attempts; every
        # other transient class uses the flat budget.
        max_attempts_429 = max(_TRANSIENT_MAX_ATTEMPTS, 3 + 2 * n_keys)
        max_attempts = max(max_attempts_429, _TRANSIENT_MAX_ATTEMPTS)

        for attempt in range(1, max_attempts + 1):
            try:
                headers = {
                    "Authorization": f"Bearer {self._auth_key()}",
                    "Content-Type": "application/json",
                }
                with httpx.Client(timeout=timeout) as client:
                    response = client.post(url, headers=headers, json=payload)
                    response.raise_for_status()
                    data = response.json()
                break  # success

            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code

                if status_code == 429 and attempt < max_attempts_429:
                    wait = _parse_retry_after(exc.response.headers.get("retry-after"))
                    if wait is None:
                        # Next attempt uses a different key when a pool exists.
                        wait = 2.0 if n_keys > 1 else min(attempt * 15, 120)
                    wait = _jitter(min(wait, 120))
                    _logger.warning("%s rate limited (429), backing off" % self._name,
                                    extra={"model": model, "attempt": attempt,
                                           "wait_s": round(wait, 2), "key_pool": n_keys})
                    time.sleep(wait)
                    last_exc = exc
                    continue

                if status_code in (500, 502, 503, 504) and attempt < _TRANSIENT_MAX_ATTEMPTS:
                    wait = _jitter(attempt * 5)
                    _logger.warning("%s server error, retrying" % self._name,
                                    extra={"model": model, "status": status_code,
                                           "attempt": attempt, "wait_s": round(wait, 2)})
                    time.sleep(wait)
                    last_exc = exc
                    continue

                if status_code == 429 or status_code >= 500:
                    raise LLMTransient(
                        f"{self._name} {status_code} after {attempt} attempts (model={model})"
                    ) from exc

                _logger.error("%s HTTP error" % self._name,
                              extra={"model": model, "status": status_code,
                                     "body": exc.response.text[:400]})
                raise

            except httpx.TimeoutException as exc:
                if attempt < _TRANSIENT_MAX_ATTEMPTS:
                    wait = _jitter(attempt * 5)
                    _logger.warning("%s timeout, retrying" % self._name,
                                    extra={"model": model, "attempt": attempt,
                                           "wait_s": round(wait, 2)})
                    time.sleep(wait)
                    last_exc = exc
                    continue
                raise LLMTransient(
                    f"{self._name} timeout after {attempt} attempts (model={model})"
                ) from exc

            except httpx.RequestError as exc:
                if attempt < _TRANSIENT_MAX_ATTEMPTS:
                    wait = _jitter(attempt * 3)
                    _logger.warning("%s request error, retrying" % self._name,
                                    extra={"model": model, "attempt": attempt,
                                           "wait_s": round(wait, 2), "error": str(exc)})
                    time.sleep(wait)
                    last_exc = exc
                    continue
                raise LLMTransient(
                    f"{self._name} request error after {attempt} attempts (model={model}): {exc}"
                ) from exc
        else:
            raise LLMTransient(
                f"{self._name} retries exhausted (model={model})"
            ) from last_exc

        elapsed = time.perf_counter() - t0
        usage = data.get("usage") or {}
        finish0 = (data.get("choices") or [{}])[0].get("finish_reason")
        _logger.info("%s response" % self._name, extra={
            "model": model,
            "elapsed_s": round(elapsed, 3),
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "finish_reason": finish0,
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

        first = choices[0] if choices else SimpleNamespace(
            message=SimpleNamespace(content=None), finish_reason=finish0)
        _check_content(first.message.content, first.finish_reason, model)

        return SimpleNamespace(
            id=data.get("id"),
            model=data.get("model"),
            choices=choices,
            usage=data.get("usage"),
            # Surfaced top-level so callers can detect truncation without
            # reaching into choices[0]. stop_reason mirrors it for uniformity
            # with the Anthropic path.
            finish_reason=first.finish_reason,
            stop_reason=first.finish_reason,
            raw=data,
        )

    def create(self, **kwargs: Any) -> SimpleNamespace:
        """Sync entry point — used by services that call from sync context."""
        payload = {k: v for k, v in kwargs.items() if v is not None}
        _acquire_rate_slot_sync()
        return self._do_request(payload)

    async def acreate(self, **kwargs: Any) -> SimpleNamespace:
        """Async entry point — acquires semaphore then offloads HTTP to thread pool."""
        payload = {k: v for k, v in kwargs.items() if v is not None}
        sem = _get_semaphore("nim")
        if sem is not None:
            async with sem:
                await _acquire_rate_slot_async()   # pace starts to NVIDIA_RPM
                return await asyncio.to_thread(self._do_request, payload)
        await _acquire_rate_slot_async()
        return await asyncio.to_thread(self._do_request, payload)


class _MistralCompletions(_NimCompletions):
    """Mistral chat completions (OpenAI-compatible API, separate quota).

    Used as the code-gen fallback when NIM is down/429ing. Inherits the full
    retry/backoff/typed-error machinery; skips NIM pacing (separate provider,
    fallback-volume traffic) and key rotation (single key).
    """

    _name = "Mistral"

    def _base_url(self) -> str:
        return settings.MISTRAL_BASE_URL

    def _auth_key(self) -> str:
        return settings.MISTRAL_API_KEY

    def _n_keys(self) -> int:
        return 1

    def _adapt_payload(self, payload: dict) -> dict:
        return payload

    def create(self, **kwargs: Any) -> SimpleNamespace:
        payload = {k: v for k, v in kwargs.items() if v is not None}
        return self._do_request(payload)

    async def acreate(self, **kwargs: Any) -> SimpleNamespace:
        payload = {k: v for k, v in kwargs.items() if v is not None}
        sem = _get_semaphore("nim")  # share the concurrency cap; no rate pacing
        if sem is not None:
            async with sem:
                return await asyncio.to_thread(self._do_request, payload)
        return await asyncio.to_thread(self._do_request, payload)


# ── Anthropic Claude backend ────────────────────────────────────────────────
# Routed to when the requested model id starts with "claude". Mirrors the NIM
# completions interface (OpenAI-shaped SimpleNamespace) so callers don't change.
# Model-family rules baked in:
#   * temperature/top_p are STRIPPED — Opus 4.7/4.8 reject non-default values (400).
#   * extended thinking is intentionally OFF — pipeline calls are structured
#     generation with tight latency budgets; enable per-call if a task needs it.
#   * always streams — large max_tokens (code-gen uses up to 100k) would hit the
#     SDK HTTP timeout on a non-streaming call.
_anthropic_client = None          # lazy SDK client (one per process)


def _get_anthropic():
    global _anthropic_client
    if _anthropic_client is None:
        import anthropic  # lazy: only imported when a claude-* model is used
        _anthropic_client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
    return _anthropic_client


def _to_anthropic_content(content: Any) -> Any:
    """Translate OpenAI message content into Anthropic content blocks.

    Strings pass through. Lists of OpenAI blocks are converted:
      {"type":"text","text":...}                     -> unchanged
      {"type":"image_url","image_url":{"url":...}}   -> {"type":"image","source":...}
    data: URLs become base64 sources; http(s) URLs become url sources.
    """
    if content is None or isinstance(content, str):
        return content
    blocks: list[dict] = []
    for b in content:
        if not isinstance(b, dict):
            continue
        btype = b.get("type")
        if btype == "text":
            blocks.append({"type": "text", "text": b.get("text", "")})
        elif btype == "image_url":
            url = (b.get("image_url") or {}).get("url", "")
            if url.startswith("data:"):
                header, _, b64 = url.partition(",")
                media = header.removeprefix("data:").split(";")[0] or "image/png"
                blocks.append({"type": "image",
                               "source": {"type": "base64", "media_type": media,
                                          "data": b64}})
            else:
                blocks.append({"type": "image",
                               "source": {"type": "url", "url": url}})
        else:
            blocks.append(b)  # pass through anything already Anthropic-shaped
    return blocks


def _content_to_text(content: Any) -> str:
    """Flatten OpenAI content (str or block list) to text for the system param."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content
                         if isinstance(b, dict) and b.get("type") == "text")
    return str(content or "")


class _ClaudeCompletions:
    def _do_request(self, payload: dict) -> SimpleNamespace:
        client = _get_anthropic()
        model = payload.get("model", "claude-opus-4-8")
        messages_raw = payload.get("messages", [])
        max_tokens = payload.get("max_tokens", 16000)

        # OpenAI -> Anthropic: hoist system turns into the `system` param; keep
        # user/assistant turns. (Anthropic has no inline system role.)
        system_parts = [_content_to_text(m["content"]) for m in messages_raw
                        if m.get("role") == "system" and m.get("content")]
        conv = [{"role": m["role"], "content": _to_anthropic_content(m["content"])}
                for m in messages_raw if m.get("role") in ("user", "assistant")]

        rf = payload.get("response_format") or {}
        if isinstance(rf, dict) and rf.get("type") == "json_object":
            # No native JSON mode on Anthropic — instruct instead. Callers
            # should still run replies through extract_json() before parsing.
            system_parts.append("Respond with valid JSON only — no prose, no code fences.")

        kwargs: dict[str, Any] = {"model": model, "max_tokens": max_tokens, "messages": conv}
        if system_parts:
            kwargs["system"] = "\n\n".join(system_parts)

        t0 = time.perf_counter()
        with client.messages.stream(**kwargs) as stream:  # stream: big max_tokens safe
            resp = stream.get_final_message()
        elapsed = time.perf_counter() - t0

        text = next((b.text for b in resp.content if b.type == "text"), "")
        _logger.info("Claude response", extra={
            "model": resp.model,
            "elapsed_s": round(elapsed, 3),
            "prompt_tokens": resp.usage.input_tokens,
            "completion_tokens": resp.usage.output_tokens,
            "finish_reason": resp.stop_reason,
        })
        _check_content(text, resp.stop_reason, model)

        return SimpleNamespace(
            id=resp.id,
            model=resp.model,
            choices=[SimpleNamespace(
                message=SimpleNamespace(content=text),
                finish_reason=resp.stop_reason,
                index=0,
            )],
            usage={"prompt_tokens": resp.usage.input_tokens,
                   "completion_tokens": resp.usage.output_tokens},
            # Surfaced top-level so callers can detect truncation/refusal
            # without reaching into choices[0]. finish_reason mirrors it for
            # uniformity with the OpenAI-shaped NIM/Mistral path.
            finish_reason=resp.stop_reason,
            stop_reason=resp.stop_reason,
            raw=resp,
        )

    def create(self, **kwargs: Any) -> SimpleNamespace:
        payload = {k: v for k, v in kwargs.items() if v is not None}
        return self._do_request(payload)

    async def acreate(self, **kwargs: Any) -> SimpleNamespace:
        payload = {k: v for k, v in kwargs.items() if v is not None}
        sem = _get_semaphore("anthropic")
        if sem is not None:
            async with sem:
                return await asyncio.to_thread(self._do_request, payload)
        return await asyncio.to_thread(self._do_request, payload)


# ── Model-based router ───────────────────────────────────────────────────────
# Dispatches each call by the `model` id: claude-* -> Anthropic,
# mistral/codestral/magistral-* (or the configured MISTRAL_MODEL) -> Mistral,
# else NIM. Lets a per-task slot (SCRIPT_WRITER_MODEL, CODE_GENERATOR_MODEL,
# ...) point at any provider independently with no caller change.
class _RoutingCompletions:
    def __init__(self) -> None:
        self._nim = _NimCompletions()
        self._claude = _ClaudeCompletions()
        self._mistral = _MistralCompletions()

    def _pick(self, model: str | None):
        m = model or ""
        if m.startswith("claude"):
            return self._claude
        # NIM also serves mistralai/* models — those route to NIM. Only bare
        # Mistral-API ids (no "mistralai/" org prefix) go to the Mistral API.
        if m == settings.MISTRAL_MODEL or (
                m.startswith(("mistral-", "codestral", "magistral"))):
            return self._mistral
        return self._nim

    def create(self, **kwargs: Any) -> SimpleNamespace:
        return self._pick(kwargs.get("model")).create(**kwargs)

    async def acreate(self, **kwargs: Any) -> SimpleNamespace:
        return await self._pick(kwargs.get("model")).acreate(**kwargs)


class _RoutingChat:
    def __init__(self) -> None:
        self.completions = _RoutingCompletions()


class NimClient:
    """OpenAI-SDK-shaped client. Routes per-call to NIM/Anthropic/Mistral by model id."""

    def __init__(self) -> None:
        self.chat = _RoutingChat()


def get_llm_client() -> NimClient:
    return NimClient()
