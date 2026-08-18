"""
Pexels API client for the image-fetcher service.

Searches each keyword SEPARATELY (MoneyPrinterTurbo's technique) and pools the
results, rather than joining all keywords into one weak query. Returns a
url -> alt-text map so the downstream vision-LLM stage has caption context.

Validates: Requirements 2.2, 6.6, 6.7
"""

import logging
from typing import Dict, List

import httpx

from shared.config import settings

from .http_retry import get_with_backoff

logger = logging.getLogger(__name__)

PEXELS_API_BASE_URL = "https://api.pexels.com/v1/search"

# Per-term result count. Each keyword is searched on its own (so 4 keywords ->
# up to 4*PER_TERM candidates pooled), then SigLIP + the vision-LLM rank them.
PER_TERM = 5


async def search_pexels(keywords: List[str]) -> Dict[str, str]:
    """
    Search Pexels per-keyword and pool the results.

    For each keyword, GET the Pexels API with per_page=PER_TERM, orientation
    landscape. Results are pooled and deduped by URL across all keywords.

    If PEXELS_API_KEY is absent/empty, returns {} without a network call.
    HTTP/network errors on one keyword are logged and skipped (other keywords
    still run) — matches MPT's "skip term, keep going" behaviour.

    Args:
        keywords: search terms (each searched separately).

    Returns:
        Ordered dict of {image_url: alt_text}. alt may be "" when Pexels omits it.

    Validates: Requirements 2.2, 6.6, 6.7
    """
    if not settings.PEXELS_API_KEY:
        logger.debug("PEXELS_API_KEY not set, skipping Pexels search")
        return {}

    terms = [k.strip() for k in keywords if k and k.strip()]
    if not terms:
        logger.debug("No keywords, returning empty result")
        return {}

    headers = {"Authorization": settings.PEXELS_API_KEY}
    results: Dict[str, str] = {}

    async with httpx.AsyncClient(timeout=30.0) as client:
        for term in terms:
            params = {"query": term, "per_page": PER_TERM, "orientation": "landscape"}
            try:
                response = await get_with_backoff(client, PEXELS_API_BASE_URL,
                                                  params=params, headers=headers)
                if response.status_code >= 400:
                    logger.warning(
                        f"Pexels API status {response.status_code} for term '{term}': "
                        f"{response.text[:200]}"
                    )
                    continue

                photos = response.json().get("photos", [])
                for photo in photos:
                    src = photo.get("src") or {}
                    # large2x = max 1880×1300 (close to 1920×1080 canvas, minimal upscale).
                    # original = full res but potentially huge; skip to avoid 4MB inline limit.
                    large_url = src.get("large2x") or src.get("large")
                    if large_url and large_url not in results:
                        results[large_url] = photo.get("alt") or ""
            except httpx.RequestError as e:
                logger.warning(f"Request error during Pexels search for '{term}': {e}")
                continue
            except Exception as e:
                logger.warning(f"Unexpected error during Pexels search for '{term}': {e}")
                continue

    logger.debug(f"Pexels pooled {len(results)} images across {len(terms)} terms")
    return results
