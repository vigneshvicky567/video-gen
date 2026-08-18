"""Core llm_client behaviors that were systemically broken (audit FR-7/FR-8):
loop-keyed semaphores, non-serializing rate slots, tolerant JSON extraction,
defensive Retry-After parsing, typed empty-content errors, Claude content-block
translation, and per-model routing."""

import asyncio
import os
import sys
import time

import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from shared import llm_client as lc  # noqa: E402


# ── rate pacer ────────────────────────────────────────────────────────────────

def test_rate_slot_reservation_is_instant_and_spaced():
    lc._next_slot_time = 0.0
    interval = lc._min_interval()
    t0 = time.perf_counter()
    w1 = lc._reserve_rate_slot()
    w2 = lc._reserve_rate_slot()
    w3 = lc._reserve_rate_slot()
    elapsed = time.perf_counter() - t0
    # Reservation NEVER blocks (the old code slept while holding the lock,
    # serializing every concurrent caller).
    assert elapsed < 0.05
    assert w1 <= 0.001
    # Consecutive callers get slots spaced by the min interval and can all
    # sleep toward them CONCURRENTLY.
    assert w2 == pytest.approx(interval, rel=0.2)
    assert w3 == pytest.approx(2 * interval, rel=0.2)


def test_sync_and_async_share_one_pacing_clock():
    lc._next_slot_time = 0.0
    lc._reserve_rate_slot()          # "sync" caller takes slot 0
    async def _async_reserve():
        return lc._reserve_rate_slot()
    w = asyncio.run(_async_reserve())
    assert w > 0  # async caller sees the sync caller's reservation


# ── loop-keyed semaphores ─────────────────────────────────────────────────────

def test_semaphore_recreated_per_event_loop():
    async def _grab():
        return lc._get_semaphore("nim")
    sem_a = asyncio.run(_grab())
    sem_b = asyncio.run(_grab())      # brand-new loop -> must be a new semaphore
    assert sem_a is not None and sem_b is not None
    assert sem_a is not sem_b


def test_semaphore_none_outside_loop():
    assert lc._get_semaphore("nim") is None


# ── extract_json ─────────────────────────────────────────────────────────────

def test_extract_json_strips_fences_and_prose():
    assert lc.extract_json('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert lc.extract_json('Sure! Here you go:\n{"a": [1, 2]}\nHope that helps.') == '{"a": [1, 2]}'
    assert lc.extract_json('[1, 2, 3]') == '[1, 2, 3]'
    assert lc.extract_json('no json at all') == 'no json at all'


# ── Retry-After parsing ───────────────────────────────────────────────────────

def test_parse_retry_after_numeric_date_and_garbage():
    assert lc._parse_retry_after("5") == 5.0
    assert lc._parse_retry_after(None) is None
    assert lc._parse_retry_after("not-a-value") is None
    # HTTP-date in the past clamps to 0, never raises (the old float() cast crashed)
    assert lc._parse_retry_after("Mon, 01 Jan 2024 00:00:00 GMT") == 0.0


# ── typed empty-content errors ────────────────────────────────────────────────

def test_check_content_raises_on_empty_and_refusal():
    with pytest.raises(lc.LLMEmptyContent):
        lc._check_content(None, "stop", "m")
    with pytest.raises(lc.LLMEmptyContent):
        lc._check_content("   ", "stop", "m")
    with pytest.raises(lc.LLMEmptyContent):
        lc._check_content("text", "refusal", "m")
    with pytest.raises(lc.LLMEmptyContent):
        lc._check_content("text", "content_filter", "m")
    lc._check_content("fine", "stop", "m")       # no raise
    # truncation now raises (retryable) — invalid/partial JSON must not flow downstream
    with pytest.raises(lc.LLMEmptyContent):
        lc._check_content("truncated", "length", "m")      # OpenAI/NIM truncation
    with pytest.raises(lc.LLMEmptyContent):
        lc._check_content("truncated", "max_tokens", "m")  # Anthropic truncation


# ── Claude content translation ────────────────────────────────────────────────

def test_openai_image_url_translates_to_anthropic_block():
    blocks = lc._to_anthropic_content([
        {"type": "text", "text": "look"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}},
        {"type": "image_url", "image_url": {"url": "https://x.test/i.jpg"}},
    ])
    assert blocks[0] == {"type": "text", "text": "look"}
    assert blocks[1] == {"type": "image", "source": {
        "type": "base64", "media_type": "image/png", "data": "QUJD"}}
    assert blocks[2] == {"type": "image", "source": {
        "type": "url", "url": "https://x.test/i.jpg"}}
    assert lc._to_anthropic_content("plain") == "plain"


# ── routing ───────────────────────────────────────────────────────────────────

def test_routing_by_model_id():
    r = lc._RoutingCompletions()
    assert r._pick("claude-opus-4-8") is r._claude
    assert r._pick("mistral-large-latest") is r._mistral
    assert r._pick("codestral-latest") is r._mistral
    # NIM-hosted mistralai/* org models stay on NIM
    assert r._pick("mistralai/mistral-small-4-119b-2603") is r._nim
    assert r._pick("moonshotai/kimi-k2-instruct") is r._nim
    assert r._pick(None) is r._nim
