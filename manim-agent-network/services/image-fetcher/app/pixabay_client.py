"""
Pixabay API client for the image-fetcher service.

Second stock-photo source (after Pexels, before the Wikimedia last resort).
Same per-keyword search pattern as pexels_client: each term searched on its
own, results pooled and deduped. Returns a url -> alt-text map (Pixabay's
`tags` field) for the downstream vision-LLM stage.
"""

import logging
from typing import Dict, List

import httpx

from shared.config import settings

from .http_retry import get_with_backoff

logger = logging.getLogger(__name__)

PIXABAY_API_BASE_URL = "https://pixabay.com/api/"

PER_TERM = 5


async def search_pixabay(keywords: List[str]) -> Dict[str, str]:
    """
    Search Pixabay per-keyword and pool the results.

    If PIXABAY_API_KEY is absent/empty, returns {} without a network call.
    Per-keyword errors are logged and skipped (other keywords still run).

    Args:
        keywords: search terms (each searched separately).

    Returns:
        Ordered dict of {image_url: tags}. tags may be "" when absent.
    """
    if not settings.PIXABAY_API_KEY:
        logger.debug("PIXABAY_API_KEY not set, skipping Pixabay search")
        return {}

    terms = [k.strip() for k in keywords if k and k.strip()]
    if not terms:
        logger.debug("No keywords, returning empty result")
        return {}

    results: Dict[str, str] = {}

    async with httpx.AsyncClient(timeout=30.0) as client:
        for term in terms:
            params = {
                "key": settings.PIXABAY_API_KEY,
                "q": term,
                "image_type": "photo",
                "per_page": PER_TERM,
                "safesearch": "true",
                "orientation": "horizontal",
            }
            try:
                response = await get_with_backoff(client, PIXABAY_API_BASE_URL, params=params)
                if response.status_code >= 400:
                    logger.warning(
                        f"Pixabay API status {response.status_code} for term '{term}': "
                        f"{response.text[:200]}"
                    )
                    continue

                hits = response.json().get("hits", [])
                for hit in hits:
                    url = hit.get("largeImageURL")
                    if url and url not in results:
                        results[url] = hit.get("tags") or ""
            except httpx.RequestError as e:
                logger.warning(f"Request error during Pixabay search for '{term}': {e}")
                continue
            except Exception as e:
                logger.warning(f"Unexpected error during Pixabay search for '{term}': {e}")
                continue

    logger.debug(f"Pixabay pooled {len(results)} images across {len(terms)} terms")
    return results
