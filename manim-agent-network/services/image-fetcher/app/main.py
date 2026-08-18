"""
Image Fetcher Service - FastAPI application

Fetches contextually relevant images for each scene using Pexels (primary)
and Wikimedia Commons (fallback). Downloads and validates images by magic bytes,
then re-ranks and filters by SigLIP image-text similarity.
"""

import asyncio
import ipaddress
import logging
import socket
from pathlib import Path
from typing import Dict, List
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI

from shared.config import settings
from shared.log import get_logger, set_log_context, make_request_logging_middleware
from shared.schemas.requests import ImageFetcherRequest
from shared.schemas.responses import ImageFetcherResponse

from . import image_cache
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


# SSRF guard. `url` and every redirect target originate from external API JSON
# (Pexels/Pixabay/Wikimedia responses) and are fully attacker-influenceable, so
# a bare follow-redirects GET could reach internal services (http://orchestrator:8000)
# or the cloud metadata endpoint (169.254.169.254). Every fetch — and every
# redirect hop — must pass _is_safe_public_url BEFORE the request is issued.
#
# Allowlist = the image-serving hosts the source clients actually return:
#   Pexels     photo.src.large2x/large -> images.pexels.com
#   Pixabay    largeImageURL           -> pixabay.com / cdn.pixabay.com
#   Wikimedia  imageinfo.thumburl      -> upload.wikimedia.org (thumbs) + commons.wikimedia.org
# Subdomains of these are allowed (e.g. i.pixabay.com under pixabay.com).
_ALLOWED_IMAGE_HOSTS = (
    "images.pexels.com",
    "pixabay.com",
    "cdn.pixabay.com",
    "upload.wikimedia.org",
    "commons.wikimedia.org",
)

# Cloud metadata IP — rejected explicitly (it is link-local, but call it out).
_METADATA_IP = "169.254.169.254"

# Bound manual redirect following.
_MAX_REDIRECTS = 3


def _host_allowed(host: str) -> bool:
    """True if host equals an allowlisted host or is a subdomain of one."""
    host = host.lower().rstrip(".")
    for allowed in _ALLOWED_IMAGE_HOSTS:
        if host == allowed or host.endswith("." + allowed):
            return True
    return False


def _is_safe_public_url(url: str) -> bool:
    """Return True only for an https URL whose host is on the CDN allowlist AND
    resolves exclusively to public IP addresses.

    Rejects: non-https schemes, non-allowlisted hosts, the cloud metadata IP,
    and any host that resolves to a private/loopback/link-local/reserved/
    multicast address (DNS-rebinding / internal-service SSRF)."""
    try:
        parts = urlsplit(url)
    except Exception:
        return False

    if parts.scheme != "https":
        return False

    host = parts.hostname
    if not host or not _host_allowed(host):
        return False

    try:
        infos = socket.getaddrinfo(host, parts.port or 443, proto=socket.IPPROTO_TCP)
    except OSError:
        return False
    if not infos:
        return False

    for info in infos:
        addr = info[4][0]
        if addr == _METADATA_IP:
            return False
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            return False
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast):
            return False
    return True


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
    _MAX_IMAGE_BYTES = 15 * 1024 * 1024  # attacker/CDN-controlled body — cap the read
    # SSRF: validate the initial URL up front. Redirects are followed manually
    # below so each hop's target can be re-validated before we connect to it.
    if not _is_safe_public_url(url):
        logger.warning(
            f"Blocked unsafe/non-allowlisted image URL for scene {scene_id}, "
            f"img {img_index}: {url}"
        )
        return False
    try:
        # follow_redirects=False: a 3xx to an internal host must not be followed
        # blindly. We chase redirects ourselves (bounded), re-checking each target.
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
            current_url = url
            for _redirect in range(_MAX_REDIRECTS + 1):
                async with client.stream("GET", current_url, headers=DOWNLOAD_HEADERS) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        next_url = str(response.next_request.url) if response.next_request else location
                        if not next_url or not _is_safe_public_url(next_url):
                            logger.warning(
                                f"Blocked unsafe redirect target for scene {scene_id}, "
                                f"img {img_index}: {next_url}"
                            )
                            return False
                        current_url = next_url
                        continue

                    if response.status_code >= 400:
                        logger.warning(
                            f"Failed to download image for scene {scene_id}, "
                            f"img {img_index}: HTTP {response.status_code}"
                        )
                        return False

                    declared = response.headers.get("content-length")
                    if declared and declared.isdigit() and int(declared) > _MAX_IMAGE_BYTES:
                        logger.warning(f"Image too large ({declared}B) for scene {scene_id}, "
                                       f"img {img_index}; skipping")
                        return False

                    chunks = []
                    received = 0
                    async for chunk in response.aiter_bytes():
                        received += len(chunk)
                        if received > _MAX_IMAGE_BYTES:
                            logger.warning(f"Image exceeded {_MAX_IMAGE_BYTES}B cap for scene "
                                           f"{scene_id}, img {img_index}; aborting download")
                            return False
                        chunks.append(chunk)
                    content = b"".join(chunks)
                    break
            else:
                logger.warning(f"Too many redirects (>{_MAX_REDIRECTS}) for scene {scene_id}, "
                               f"img {img_index}; aborting download")
                return False

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

    # Step 0: cache first — previously kept images live in a persistent
    # embedding store; a similarity hit skips keywords + 3 API searches +
    # downloads entirely. The vision vet still judges the pixels, so a stale
    # or merely-similar cached image can't sneak into the scene.
    query = f"{visual_description}. {narration_text}"
    cached_paths, cached_alts = await asyncio.to_thread(image_cache.lookup, query, 5)
    if cached_paths:
        final = await asyncio.to_thread(
            vision_select, cached_paths, cached_alts, narration_text, visual_description, 3
        )
        if final:
            logger.info("Image cache HIT — skipping network fetch",
                        extra={"scene_id": scene_id, "kept": len(final)})
            return final
        logger.info("Image cache candidates rejected by vision vet; fetching fresh",
                    extra={"scene_id": scene_id})

    # Step 1: Extract keywords (semantic LLM call; regex fallback warns loudly).
    # to_thread: extract_keywords is a SYNC blocking LLM call — inline it and the
    # whole service's event loop (incl. /health) stalls for its duration.
    keywords = await asyncio.to_thread(extract_keywords, narration_text, visual_description)
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
    # Cap the pool BEFORE downloading — the pooled candidate count is unbounded
    # (3 sources × N terms) and every extra download is wasted bandwidth once
    # SigLIP keeps only the top 5.
    _MAX_CANDIDATES = 12
    if len(candidates) > _MAX_CANDIDATES:
        logger.info("Capping candidate pool before download",
                    extra={"scene_id": scene_id, "pooled": len(candidates),
                           "cap": _MAX_CANDIDATES})
        candidates = dict(list(candidates.items())[:_MAX_CANDIDATES])
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

    # Step 6: persist the keepers (file + embedding) so the next scene/job with
    # a similar query reuses them without any network fetch.
    if final:
        await asyncio.to_thread(image_cache.add, final, path_alts)
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
