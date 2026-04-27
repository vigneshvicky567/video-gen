"""
Image Fetcher Service - FastAPI application

Fetches contextually relevant images for each scene using Pexels (primary)
and Wikimedia Commons (fallback). Downloads and validates images by magic bytes.

Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7
"""

import logging
from pathlib import Path
from typing import Dict, List

import httpx
from fastapi import FastAPI, HTTPException

from shared.config import settings
from shared.schemas.requests import ImageFetcherRequest
from shared.schemas.responses import ImageFetcherResponse

from .keyword_extractor import extract_keywords
from .pexels_client import search_pexels
from .wikimedia_client import search_wikimedia

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Image Fetcher Service", version="1.0.0")

# Magic bytes for image validation
# JPEG: FF D8 FF
# PNG: 89 50 4E 47
JPEG_MAGIC = bytes([0xFF, 0xD8, 0xFF])
PNG_MAGIC = bytes([0x89, 0x50, 0x4E, 0x47])


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
            response = await client.get(url)
            
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
    """
    Fetch images for a single scene.
    
    Process:
    1. Extract keywords from narration_text and visual_description
    2. Query Pexels API
    3. If Pexels returns empty, query Wikimedia Commons
    4. Download each candidate URL
    5. Validate magic bytes (JPEG: FF D8 FF, PNG: 89 50 4E 47)
    6. Write valid images to {WORKSPACE_DIR}/temp/{job_id}/images/scene_{scene_id}/img_{n}.jpg
    7. Return list of absolute paths to validated images
    
    Args:
        scene_id: The scene ID.
        narration_text: The narration text for the scene.
        visual_description: The visual description for the scene.
        job_id: The job ID.
    
    Returns:
        A list of absolute paths to validated images (may be empty).
    
    Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7
    """
    logger.info(f"Fetching images for scene {scene_id}")
    
    # Step 1: Extract keywords
    keywords = extract_keywords(narration_text, visual_description)
    logger.info(f"Extracted keywords for scene {scene_id}: {keywords}")
    
    # Step 2: Query Pexels
    candidate_urls = await search_pexels(keywords)
    logger.info(f"Pexels returned {len(candidate_urls)} candidates for scene {scene_id}")
    
    # Step 3: If Pexels returns empty, query Wikimedia
    if not candidate_urls:
        logger.info(f"Pexels returned empty, querying Wikimedia for scene {scene_id}")
        candidate_urls = await search_wikimedia(keywords)
        logger.info(
            f"Wikimedia returned {len(candidate_urls)} candidates for scene {scene_id}"
        )
    
    # Step 4-6: Download, validate, and save images
    image_paths: List[str] = []
    
    for idx, url in enumerate(candidate_urls):
        # Construct output path
        output_dir = Path(settings.WORKSPACE_DIR) / "temp" / job_id / "images" / f"scene_{scene_id}"
        output_path = output_dir / f"img_{idx}.jpg"
        
        # Download and validate
        success = await download_and_validate_image(url, output_path, scene_id, idx)
        
        if success:
            # Record absolute path
            image_paths.append(str(output_path.absolute()))
    
    # Step 7: Return list of validated image paths (may be empty)
    logger.info(f"Scene {scene_id} has {len(image_paths)} validated images")
    return image_paths


@app.post("/fetch", response_model=ImageFetcherResponse)
async def fetch_images(request: ImageFetcherRequest) -> ImageFetcherResponse:
    """
    Fetch contextually relevant images for all scenes in the request.
    
    For each scene:
    - Extract keywords from narration_text and visual_description
    - Query Pexels API (primary source)
    - If Pexels returns empty, query Wikimedia Commons (fallback)
    - Download each candidate image URL
    - Validate magic bytes (JPEG: FF D8 FF, PNG: 89 50 4E 47)
    - Write valid images to {WORKSPACE_DIR}/temp/{job_id}/images/scene_{scene_id}/img_{n}.jpg
    - Record empty list for scene if both sources return nothing
    
    Never raises exceptions on missing images - always returns a response.
    
    Args:
        request: ImageFetcherRequest containing job_id and list of ScenePlan objects.
    
    Returns:
        ImageFetcherResponse with mapping of scene_id to list of absolute image paths.
    
    Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7
    """
    logger.info(f"Received fetch request for job {request.job_id} with {len(request.scenes)} scenes")
    
    image_paths: Dict[int, List[str]] = {}
    
    # Process each scene
    for scene in request.scenes:
        try:
            scene_images = await fetch_images_for_scene(
                scene_id=scene.scene_id,
                narration_text=scene.narration_text,
                visual_description=scene.visual_description,
                job_id=request.job_id
            )
            
            # Record the image paths (may be empty list)
            image_paths[scene.scene_id] = scene_images
            
        except Exception as e:
            # Never raise on missing images - record empty list and continue
            logger.error(
                f"Error fetching images for scene {scene.scene_id}: {e}. "
                f"Recording empty list and continuing."
            )
            image_paths[scene.scene_id] = []
    
    logger.info(
        f"Completed fetch request for job {request.job_id}. "
        f"Total scenes: {len(request.scenes)}, "
        f"Scenes with images: {sum(1 for paths in image_paths.values() if paths)}"
    )
    
    return ImageFetcherResponse(image_paths=image_paths)


@app.get("/health")
async def health_check():
    """
    Health check endpoint.
    
    Returns:
        A simple status message indicating the service is healthy.
    """
    return {"status": "healthy", "service": "image-fetcher"}
