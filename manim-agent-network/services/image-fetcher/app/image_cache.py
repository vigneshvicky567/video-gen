"""Persistent image cache with SigLIP-embedding similarity lookup.

Every image the pipeline keeps is stored ONCE (file + embedding + alt text) in
/workspace/image_cache. Before hitting Pexels/Pixabay/Wikimedia for a new
scene, the fetcher embeds the scene query and searches this store — a hit
skips the whole network fetch + download + re-scoring path.

Implementation is deliberately boring: sqlite for metadata, float32 embedding
BLOBs, brute-force cosine/sigmoid scoring in numpy. At cache sizes this
pipeline reaches (thousands of rows, 768-dim vectors) a full scan is
milliseconds — a real vector DB adds an infra dependency for nothing.
ponytail: swap the scan for FAISS/sqlite-vec if the cache passes ~100k rows.

Degrades to a no-op (miss on lookup, skip on add) when the SigLIP models are
absent — exactly like the scorer it reuses.
"""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np

from shared.config import settings
from shared.log import get_logger

from .siglip_scorer import _image_embedding, _models_available, _text_embedding

logger = get_logger(__name__)

_CACHE_DIR = Path(settings.WORKSPACE_DIR) / "image_cache"
_DB_PATH = _CACHE_DIR / "cache.db"

# Stricter than the live SigLIP keep-threshold (0.15): reusing a cached image
# skips a fresh fetch entirely, so the bar for "good enough to not even look"
# must be higher than "good enough to keep from a fresh pool".
import os
MIN_HIT_SCORE: float = float(os.getenv("IMAGE_CACHE_MIN_SCORE", "0.25"))


def _conn() -> sqlite3.Connection:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(_DB_PATH, timeout=10)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=5000")
    c.execute("""
        CREATE TABLE IF NOT EXISTS images (
            sha TEXT PRIMARY KEY,
            path TEXT NOT NULL,
            alt TEXT NOT NULL DEFAULT '',
            emb BLOB NOT NULL,
            created_at REAL NOT NULL
        )
    """)
    return c


def lookup(query_text: str, k: int = 5,
           min_score: float = MIN_HIT_SCORE) -> Tuple[List[str], Dict[str, str]]:
    """Return up to k cached image paths scoring >= min_score for the query.

    Returns ([], {}) on any failure or when models/cache are absent — callers
    fall through to the network fetch.
    """
    if not _models_available():
        return [], {}
    try:
        with _conn() as c:
            rows = c.execute("SELECT sha, path, alt, emb FROM images").fetchall()
        if not rows:
            return [], {}
        text_emb = _text_embedding(query_text)
        scored = []
        for sha, path, alt, emb_blob in rows:
            if not Path(path).exists():
                continue  # pruned externally; row is stale but harmless
            emb = np.frombuffer(emb_blob, dtype=np.float32)
            if emb.shape != text_emb.shape:
                continue
            score = float(1.0 / (1.0 + np.exp(-float(np.dot(emb, text_emb)))))
            if score >= min_score:
                scored.append((score, path, alt))
        scored.sort(key=lambda t: t[0], reverse=True)
        top = scored[:k]
        if top:
            logger.info("Image cache lookup hit",
                        extra={"hits": len(top), "best": round(top[0][0], 4),
                               "cache_rows": len(rows)})
        return [p for _, p, _ in top], {p: a for _, p, a in top}
    except Exception as e:  # noqa: BLE001 — cache must never break fetching
        logger.warning("Image cache lookup failed (treating as miss)",
                       extra={"error": str(e)[:200]})
        return [], {}


def add(paths: List[str], alts: Dict[str, str]) -> int:
    """Persist kept images (copy into the cache dir + embed + upsert). Returns
    the number of images newly added. Never raises."""
    if not _models_available():
        return 0
    added = 0
    try:
        with _conn() as c:
            for p in paths:
                src = Path(p)
                if not src.exists():
                    continue
                raw = src.read_bytes()
                sha = hashlib.sha1(raw).hexdigest()
                if c.execute("SELECT 1 FROM images WHERE sha = ?", (sha,)).fetchone():
                    continue
                # Copy OUT of the per-job temp dir (which gets deleted after
                # assembly) into the persistent cache dir.
                dest = _CACHE_DIR / f"img_{sha}{src.suffix or '.jpg'}"
                if not dest.exists():
                    shutil.copyfile(src, dest)
                emb = _image_embedding(str(dest)).astype(np.float32)
                c.execute(
                    "INSERT OR IGNORE INTO images (sha, path, alt, emb, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (sha, str(dest), alts.get(p, ""), emb.tobytes(), time.time()),
                )
                added += 1
        if added:
            logger.info("Image cache add", extra={"added": added})
        return added
    except Exception as e:  # noqa: BLE001
        logger.warning("Image cache add failed (non-fatal)", extra={"error": str(e)[:200]})
        return added
