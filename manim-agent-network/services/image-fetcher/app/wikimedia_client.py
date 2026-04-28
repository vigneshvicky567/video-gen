"""
Wikimedia Commons API client for the image-fetcher service.

Queries the Wikimedia Commons API as a fallback image source when Pexels
returns no results. Iterates through keywords until at least one image URL
is found, up to 3 total results.

Validates: Requirements 2.3
"""

import logging
from typing import List

import httpx

logger = logging.getLogger(__name__)

WIKIMEDIA_API_BASE_URL = "https://en.wikipedia.org/w/api.php"


async def search_wikimedia(keywords: List[str]) -> List[str]:
    """
    Search Wikimedia Commons for images matching the given keywords.
    
    Makes GET requests to the Wikipedia API with:
      - action: query
      - generator: search
      - gsrsearch: {keyword}
      - prop: pageimages
      - piprop: original
      - format: json
    
    Iterates through keywords until at least one image URL is found,
    collecting up to 3 total results.
    
    Returns an empty list on HTTP errors (4xx/5xx).
    
    Args:
        keywords: List of keyword strings to search for.
    
    Returns:
        A list of up to 3 image URLs from Wikimedia Commons.
    
    Validates: Requirements 2.3
    """
    if not keywords:
        logger.debug("Empty keywords list, returning empty list")
        return []
    
    image_urls: List[str] = []
    
    try:
        async with httpx.AsyncClient(
            timeout=30.0,
            headers={
                "User-Agent": "ManimAgentNetwork/1.0 (https://github.com/manim-agent-network; contact@example.com) python-httpx"
            }
        ) as client:
            # Iterate through keywords until we have at least one image or exhaust keywords
            for keyword in keywords:
                if len(image_urls) >= 3:
                    break
                
                # Build query parameters
                params = {
                    "action": "query",
                    "generator": "search",
                    "gsrsearch": keyword,
                    "prop": "pageimages",
                    "piprop": "original",
                    "format": "json"
                }
                
                try:
                    response = await client.get(
                        WIKIMEDIA_API_BASE_URL,
                        params=params
                    )
                    
                    # Requirement 2.3: Return empty list on HTTP error
                    if response.status_code >= 400:
                        logger.warning(
                            f"Wikimedia API returned status {response.status_code} "
                            f"for keyword '{keyword}': {response.text[:200]}"
                        )
                        return []
                    
                    # Parse response and extract image URLs
                    data = response.json()
                    pages = data.get("query", {}).get("pages", {})
                    
                    for page_id, page_data in pages.items():
                        if len(image_urls) >= 3:
                            break
                        
                        # Extract original image URL if present
                        original = page_data.get("original")
                        if original and "source" in original:
                            image_url = original["source"]
                            image_urls.append(image_url)
                            logger.debug(f"Found image for keyword '{keyword}': {image_url}")
                    
                    # If we found at least one image, we can stop iterating keywords
                    if image_urls:
                        logger.debug(
                            f"Found {len(image_urls)} images after keyword '{keyword}', "
                            f"stopping iteration"
                        )
                        break
                
                except httpx.HTTPStatusError as e:
                    logger.warning(f"HTTP error during Wikimedia search for '{keyword}': {e}")
                    return []
                except httpx.RequestError as e:
                    logger.warning(f"Request error during Wikimedia search for '{keyword}': {e}")
                    return []
            
            logger.debug(f"Wikimedia search completed with {len(image_urls)} images")
            return image_urls
            
    except Exception as e:
        logger.warning(f"Unexpected error during Wikimedia search: {e}")
        return []
