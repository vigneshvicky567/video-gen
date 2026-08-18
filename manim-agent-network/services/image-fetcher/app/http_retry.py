"""Shared rate-limit-aware GET for the stock image source clients.

Pexels/Pixabay/Wikimedia all rate-limit; a bare GET treated 429 like any
error and silently dropped the term. One helper, Retry-After honored, bounded.
"""

from __future__ import annotations

import asyncio

import httpx


async def get_with_backoff(client: httpx.AsyncClient, url: str, *,
                           params=None, headers=None, retries: int = 2) -> httpx.Response:
    """GET with bounded backoff on 429/503 (honoring Retry-After when numeric).

    Returns the final response whatever its status — callers keep their own
    status handling. Never sleeps more than 30s per attempt.
    """
    response: httpx.Response | None = None
    for attempt in range(retries + 1):
        response = await client.get(url, params=params, headers=headers)
        if response.status_code in (429, 503) and attempt < retries:
            ra = response.headers.get("retry-after")
            try:
                wait = min(30.0, max(1.0, float(ra))) if ra else 2.0 * (attempt + 1)
            except (TypeError, ValueError):
                wait = 2.0 * (attempt + 1)
            await asyncio.sleep(wait)
            continue
        return response
    return response
