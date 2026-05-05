"""
Image Fetcher Service - FastAPI application

Fetches contextually relevant images for each scene using Pexels (primary)
and Wikimedia Commons (fallback). Downloads and validates images by magic bytes,
then re-ranks and filters by SigLIP image-text similarity.
"""

import logging
from pathlib import Path
from typing import Dict, List

import httpx
from fastapi import FastAPI

from shared.config import settings
from shared.log import get_logger, set_log_context, make_request_logging_middleware
from shared.schemas.requests import ImageFetcherRequest
from shared.schemas.responses import ImageFetcherResponse

from .keyword_extractor import extract_keywords
from .pexels_client import search_pexels
# from .siglip_scorer import filter_by_relevance  # TODO: enable when SigLIP models are downloaded
from .wikimedia_client import search_wikimedia

app = FastAPI(title="Image Fetcher Service", version="1.0.0")
app.add_middleware(make_request_logging_middleware("image-fetcher"))
logger = get_logger(__name__)

# Magic bytes for image validation
# JPEG: FF D8 FF
# PNG: 89 50 4E 47
JPEG_MAGIC = bytes([0xFF, 0xD8, 0xFF])
PNG_MAGIC = bytes([0x89, 0x50, 0x4E, 0x47])

DOWNLOAD_HEADERS = {
    "User-Agent": "ManimAgentNetwork/1.0 (https://github.com/manim-agent-network; contact@example.com) python-httpx",
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    "Referer": "https://commons.wikimedia.org/",
}


def validate_image_magic_bytes(data: bytes) -> bool:
    """
    Validate that the given byte data starts with valid JPEG or PNG magic bytes.
    
    JPEG magic bytes: FF D8 FF
    PNG magic bytes: 89 50 4E 47
    
    Args:
        data: The byte data to validate (at least first 4 bytes).
    
    Returns:
        True if the data starts with valid JPEG or PNG magic bytes, False otherwise.
    
    Validates: Requirements 2.7
    """
    if len(data) < 4:
        return False
    
    # Check JPEG magic bytes (first 3 bytes)
    if data[:3] == JPEG_MAGIC:
        return True
    
    # Check PNG magic bytes (first 4 bytes)
    if data[:4] == PNG_MAGIC:
        return True
    
    return False


# Alias used by property-based tests
is_valid_image = validate_image_magic_bytes


async def download_and_validate_image(
    url: str,
    output_path: Path,
    scene_id: int,
    img_index: int
) -> bool:
    """
    Download an image from the given URL, validate its magic bytes, and save it.
    
    Args:
        url: The URL to download the image from.
        output_path: The path to save the validated image to.
        scene_id: The scene ID (for logging).
        img_index: The image index (for logging).
    
    Returns:
        True if the image was successfully downloaded and validated, False otherwise.
    
    Validates: Requirements 2.4, 2.7
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=DOWNLOAD_HEADERS, follow_redirects=True)
            
            if response.status_code >= 400:
                logger.warning(
                    f"Failed to download image for scene {scene_id}, "
                    f"img {img_index}: HTTP {response.status_code}"
                )
                return False
            
            # Read the response content
            content = response.content
            
            # Validate magic bytes
            if not validate_image_magic_bytes(content):
                logger.warning(
                    f"Invalid image magic bytes for scene {scene_id}, "
                    f"img {img_index} from {url}"
                )
                return False
            
            # Write the validated image to disk
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(content)
            
            logger.info(
                f"Successfully downloaded and validated image for scene {scene_id}, "
                f"img {img_index}: {output_path}"
            )
            return True
            
    except httpx.RequestError as e:
        logger.warning(
            f"Request error downloading image for scene {scene_id}, "
            f"img {img_index}: {e}"
        )
        return False
    except Exception as e:
        logger.warning(
            f"Unexpected error downloading image for scene {scene_id}, "
            f"img {img_index}: {e}"
        )
        return False


async def fetch_images_for_scene(
    scene_id: int,
    narration_text: str,
    visual_description: str,
    job_id: str
) -> List[str]:
    set_log_context(scene_id=scene_id)
    logger.info("Fetching images", extra={"scene_id": scene_id})

    # Step 1: Extract keywords
    keywords = extract_keywords(narration_text, visual_description)
    logger.info("Keywords extracted", extra={"scene_id": scene_id, "keywords": keywords})

    # Step 2: Query Pexels, fallback to Wikimedia
    if not settings.PEXELS_API_KEY:
        logger.warning("PEXELS_API_KEY not set, skipping Pexels search", extra={"scene_id": scene_id})
    candidate_urls = await search_pexels(keywords)
    logger.info("Pexels results", extra={"scene_id": scene_id, "count": len(candidate_urls)})

    if not candidate_urls:
        candidate_urls = await search_wikimedia(keywords)
        logger.info("Wikimedia results", extra={"scene_id": scene_id, "count": len(candidate_urls)})
        if not candidate_urls:
            logger.warning(
                "No image candidates found",
                extra={"scene_id": scene_id, "keywords": keywords}
            )

    # Step 3: Download + magic-byte validate
    image_paths: List[str] = []
    for idx, url in enumerate(candidate_urls):
        output_dir  = Path(settings.WORKSPACE_DIR) / "temp" / job_id / "images" / f"scene_{scene_id}"
        output_path = output_dir / f"img_{idx}.jpg"
        if await download_and_validate_image(url, output_path, scene_id, idx):
            image_paths.append(str(output_path.absolute()))

    logger.info("Downloaded images", extra={"scene_id": scene_id, "count": len(image_paths)})

    if not image_paths:
        return []

    # TODO: SigLIP relevance filter — uncomment when models are available
    # query = f"{visual_description}. {narration_text}"
    # ranked = filter_by_relevance(image_paths, query_text=query, top_k=3)
    # logger.info("After SigLIP filter", extra={"scene_id": scene_id,
    #                                            "before": len(image_paths),
    #                                            "after": len(ranked)})
    # return ranked

    return image_paths


@app.post("/fetch", response_model=ImageFetcherResponse)
async def fetch_images(request: ImageFetcherRequest) -> ImageFetcherResponse:
    """Fetch images for all scenes in parallel."""
    import asyncio
    logger.info("Image fetch request", extra={"job_id": request.job_id, "scenes": len(request.scenes)})

    async def _safe_fetch(scene) -> tuple:
        try:
            paths = await fetch_images_for_scene(
                scene_id=scene.scene_id,
                narration_text=scene.narration_text,
                visual_description=scene.visual_description,
                job_id=request.job_id,
            )
            return scene.scene_id, paths
        except Exception as e:
            logger.error("Image fetch failed for scene", extra={"scene_id": scene.scene_id, "error": str(e)})
            return scene.scene_id, []

    # Run all scenes in parallel
    results = await asyncio.gather(*[_safe_fetch(s) for s in request.scenes])
    image_paths = {sid: paths for sid, paths in results}

    scenes_with_images = sum(1 for p in image_paths.values() if p)
    logger.info("Image fetch complete", extra={"job_id": request.job_id,
                                                "total": len(request.scenes),
                                                "with_images": scenes_with_images})
    return ImageFetcherResponse(image_paths=image_paths)


@app.get("/health")
async def health_check():
    """
    Health check endpoint.
    
    Returns:
        A simple status message indicating the service is healthy.
    """
    return {"status": "healthy", "service": "image-fetcher"}
