"""
Pexels API client for the image-fetcher service.

Queries the Pexels API for royalty-free images using extracted keywords.
Returns up to 3 image URLs per query.

Validates: Requirements 2.2, 6.6, 6.7
"""

import logging
from typing import List

import httpx

from shared.config import settings

logger = logging.getLogger(__name__)

PEXELS_API_BASE_URL = "https://api.pexels.com/v1/search"


async def search_pexels(keywords: List[str]) -> List[str]:
    """
    Search Pexels for images matching the given keywords.
    
    Makes a GET request to the Pexels API with:
      - query: keywords joined by space
      - per_page: 3
      - orientation: landscape
    
    Returns up to 3 src.large image URLs.
    
    If PEXELS_API_KEY is absent or empty, returns an empty list immediately
    without making a network call.
    
    On HTTP 4xx/5xx errors, logs a warning and returns an empty list.
    
    Args:
        keywords: List of keyword strings to search for.
    
    Returns:
        A list of up to 3 image URLs (src.large from Pexels response).
    
    Validates: Requirements 2.2, 6.6, 6.7
    """
    # Check for API key before making any request
    # Requirement 6.7: Skip Pexels query if PEXELS_API_KEY is not set
    if not settings.PEXELS_API_KEY:
        logger.debug("PEXELS_API_KEY not set, skipping Pexels search")
        return []
    
    # Build query from keywords
    query = " ".join(keywords)
    if not query:
        logger.debug("Empty query, returning empty list")
        return []
    
    # Prepare request parameters
    params = {
        "query": query,
        "per_page": 3,
        "orientation": "landscape"
    }
    
    # Requirement 6.6: Authorization header with API key
    headers = {
        "Authorization": settings.PEXELS_API_KEY
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                PEXELS_API_BASE_URL,
                params=params,
                headers=headers
            )
            
            # Requirement 2.2: On HTTP 4xx/5xx, log warning and return empty list
            if response.status_code >= 400:
                logger.warning(
                    f"Pexels API returned status {response.status_code} "
                    f"for query '{query}': {response.text[:200]}"
                )
                return []
            
            # Parse response and extract src.large URLs
            data = response.json()
            photos = data.get("photos", [])
            
            image_urls = []
            for photo in photos[:3]:
                src = photo.get("src", {})
                large_url = src.get("large")
                if large_url:
                    image_urls.append(large_url)
            
            logger.debug(f"Found {len(image_urls)} images for query '{query}'")
            return image_urls
            
    except httpx.HTTPStatusError as e:
        logger.warning(f"HTTP error during Pexels search: {e}")
        return []
    except httpx.RequestError as e:
        logger.warning(f"Request error during Pexels search: {e}")
        return []
    except Exception as e:
        logger.warning(f"Unexpected error during Pexels search: {e}")
        return []
