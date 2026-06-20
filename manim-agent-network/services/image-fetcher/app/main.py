"""
Image Fetcher Service - FastAPI application

Fetches contextually relevant images for each scene using Pexels (primary)
and Wikimedia Commons (fallback). Downloads and validates images by magic bytes,
then re-ranks and filters by SigLIP image-text similarity.
"""

import asyncio
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
from .pixabay_client import search_pixabay
from .relevance_llm import vision_select
from .siglip_scorer import filter_by_relevance
from .wikimedia_client import search_wikimedia

app = FastAPI(title="Image Fetcher Service", version="1.0.0")
app.add_middleware(make_request_logging_middleware("image-fetcher"))
logger = get_logger(__name__)

# Magic bytes for image validation
# JPEG: FF D8 FF
# PNG: 89 50 4E 47
JPEG_MAGIC = bytes([0xFF, 0xD8, 0xFF])
PNG_MAGIC = bytes([0x89, 0x50, 0x4E, 0x47])

# Accept only JPEG/PNG. Pexels' `auto=compress` serves WebP/AVIF when those are
# in Accept, but validate_image_magic_bytes only knows JPEG/PNG -> ~70% of valid
# candidates were silently dropped. Asking for jpeg/png makes the source return
# a format the validator (and the .jpg extension) actually match.
# ponytail: if a source ignores Accept and serves WebP anyway, add WebP magic
# bytes to validate_image_magic_bytes instead of widening this header.
# Wikimedia's upload host enforces a robot policy: it 403s any User-Agent that
# contains the "example.com" placeholder or a bare library token like
# "python-httpx". A real client name + contact passes. (Proven: example.com -> 403,
# real contact -> 200.) Other sources don't care, so one compliant UA serves all.
DOWNLOAD_HEADERS = {
    "User-Agent": "ManimAgentNetwork/1.0 (https://github.com/manim-agent-network; admin@kineticstudios.dev)",
    "Accept": "image/jpeg,image/png,image/*;q=0.8",
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

    # Step 1: Extract keywords (semantic LLM call; regex fallback warns loudly)
    keywords = extract_keywords(narration_text, visual_description)
    logger.info("Keywords extracted", extra={"scene_id": scene_id, "keywords": keywords})

    # Step 2: Pool all sources per-term (Pexels + Pixabay stock, Wikimedia Commons
    #         for educational diagrams/science/maps). All three are peers — SigLIP
    #         + the vision LLM rank the combined pool, so the best image wins per
    #         scene regardless of source. candidates: {url: alt_text}
    pexels, pixabay, commons = await asyncio.gather(
        search_pexels(keywords),
        search_pixabay(keywords),
        search_wikimedia(keywords),
    )
    candidates: Dict[str, str] = {}
    candidates.update(pexels)
    candidates.update(pixabay)
    candidates.update(commons)
    logger.info(
        "Pooled candidates",
        extra={"scene_id": scene_id, "pexels": len(pexels),
               "pixabay": len(pixabay), "commons": len(commons),
               "total": len(candidates)},
    )

    if not candidates:
        logger.warning("No image candidates found",
                       extra={"scene_id": scene_id, "keywords": keywords})
        return []

    # Step 3: Download + magic-byte validate. Carry alt text onto the saved path.
    image_paths: List[str] = []
    path_alts: Dict[str, str] = {}
    output_dir = Path(settings.WORKSPACE_DIR) / "temp" / job_id / "images" / f"scene_{scene_id}"
    for idx, (url, alt) in enumerate(candidates.items()):
        output_path = output_dir / f"img_{idx}.jpg"
        if await download_and_validate_image(url, output_path, scene_id, idx):
            abs_path = str(output_path.absolute())
            image_paths.append(abs_path)
            path_alts[abs_path] = alt

    logger.info("Downloaded images", extra={"scene_id": scene_id, "count": len(image_paths)})
    if not image_paths:
        return []

    # Step 4 (Stage 1): SigLIP visual ranking — keep top 5 to feed the vision LLM.
    # Degrades to pass-through (top_k) if the SigLIP model files are absent.
    query = f"{visual_description}. {narration_text}"
    ranked = await asyncio.to_thread(filter_by_relevance, image_paths, query, top_k=5)
    logger.info("After SigLIP filter",
                extra={"scene_id": scene_id, "before": len(image_paths), "after": len(ranked)})

    # Step 5 (Stage 2): vision-LLM final vet — sees pixels, keeps best <=3.
    # Degrades to ranked[:3] on any failure / non-vision model.
    final = await asyncio.to_thread(
        vision_select, ranked, path_alts, narration_text, visual_description, 3
    )
    logger.info("After vision vet",
                extra={"scene_id": scene_id, "before": len(ranked), "after": len(final)})
    return final


@app.post("/fetch", response_model=ImageFetcherResponse)
async def fetch_images(request: ImageFetcherRequest) -> ImageFetcherResponse:
    """Fetch images for all scenes in parallel."""
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
