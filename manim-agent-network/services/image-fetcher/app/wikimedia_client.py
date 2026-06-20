"""
Wikimedia Commons API client for the image-fetcher service.

Searches the Commons File namespace (namespace 6) per-keyword and pools the
results, same shape as the Pexels/Pixabay clients. Commons is the strongest
source for *educational* imagery — diagrams, anatomy, science, charts, maps,
historical photos — all CC / public-domain.

Key trick: we request a scaled thumbnail (iiurlwidth) rather than the original.
That keeps downloads small AND renders SVG diagrams (Commons' richest edu asset)
as PNG, which the magic-byte validator accepts. Originals can be 20MB TIFFs or
raw SVG the renderer can't use.

Validates: Requirements 2.3
"""

import logging
from typing import Dict, List

import httpx

logger = logging.getLogger(__name__)

COMMONS_API_BASE_URL = "https://commons.wikimedia.org/w/api.php"

# Per-term result count. Each keyword searched separately, pooled + deduped by
# URL — mirrors pexels_client / pixabay_client so SigLIP + vision-vet rank the
# combined pool.
PER_TERM = 4

# Width of the rendered thumbnail. 1280 is plenty for 1080p scenes and forces
# SVG -> PNG rasterization on Commons' side.
THUMB_WIDTH = 1280


def _alt_from_imageinfo(info: dict, title: str) -> str:
    """Best human-readable caption: extmetadata description/object name, else title."""
    meta = info.get("extmetadata") or {}
    for key in ("ImageDescription", "ObjectName"):
        val = (meta.get(key) or {}).get("value")
        if val:
            # extmetadata values can carry HTML; keep it simple for the vision LLM.
            return val
    # Strip the "File:" prefix and extension noise from the page title.
    return title.removeprefix("File:")


async def search_wikimedia(keywords: List[str]) -> Dict[str, str]:
    """
    Search Wikimedia Commons (File namespace) per-keyword and pool the results.

    For each keyword, GET the Commons API with generator=search, gsrnamespace=6,
    prop=imageinfo, iiurlwidth=THUMB_WIDTH. Pools + dedupes thumbnail URLs across
    keywords. Skips results with no rasterizable thumbnail.

    Returns an empty dict on HTTP errors (4xx/5xx) for a keyword (other keywords
    still run).

    Args:
        keywords: List of keyword strings to search for.

    Returns:
        Ordered dict of {thumbnail_url: alt_text}.

    Validates: Requirements 2.3
    """
    terms = [k.strip() for k in keywords if k and k.strip()]
    if not terms:
        logger.debug("No keywords, returning empty result")
        return {}

    results: Dict[str, str] = {}
    # Wikimedia robot policy: a placeholder "example.com" or bare library token
    # in the UA gets 403'd. Use a real client name + contact.
    headers = {
        "User-Agent": "ManimAgentNetwork/1.0 (https://github.com/manim-agent-network; admin@kineticstudios.dev)"
    }

    async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
        for term in terms:
            params = {
                "action": "query",
                "generator": "search",
                "gsrsearch": term,
                "gsrnamespace": 6,          # File: namespace -> actual media files
                "gsrlimit": PER_TERM,
                "prop": "imageinfo",
                "iiprop": "url|mime|extmetadata",
                "iiurlwidth": THUMB_WIDTH,  # rendered thumb (SVG -> PNG, small)
                "format": "json",
            }
            try:
                response = await client.get(COMMONS_API_BASE_URL, params=params)
                if response.status_code >= 400:
                    logger.warning(
                        f"Commons API status {response.status_code} for term '{term}': "
                        f"{response.text[:200]}"
                    )
                    continue

                pages = response.json().get("query", {}).get("pages", {})
                for page in pages.values():
                    infos = page.get("imageinfo") or []
                    if not infos:
                        continue
                    info = infos[0]
                    # thumburl is the rasterized, scaled image (PNG/JPEG).
                    url = info.get("thumburl")
                    if url and url not in results:
                        results[url] = _alt_from_imageinfo(info, page.get("title", ""))
            except httpx.RequestError as e:
                logger.warning(f"Request error during Commons search for '{term}': {e}")
                continue
            except Exception as e:
                logger.warning(f"Unexpected error during Commons search for '{term}': {e}")
                continue

    logger.debug(f"Commons pooled {len(results)} images across {len(terms)} terms")
    return results
