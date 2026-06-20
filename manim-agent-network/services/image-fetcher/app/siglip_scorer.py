"""
SigLIP ONNX relevance scorer for image-text similarity.

Uses the ONNX-exported SigLIP base model (deepghs/siglip_onnx) to score
how relevant a downloaded image is to a scene's text description.
Runs entirely on CPU via onnxruntime — no PyTorch, no GPU needed.

Model: google/siglip-base-patch16-256 (~180MB image encoder + ~170MB text encoder)
Score: sigmoid(image_emb · text_emb) in [0, 1]. Threshold 0.15 works well in practice.
"""

from __future__ import annotations

import os
import re
import struct
from functools import lru_cache
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
from PIL import Image

from shared.log import get_logger

logger = get_logger(__name__)

# ── Model paths (downloaded during Docker build) ──────────────────────────────
_MODEL_DIR = Path(os.getenv("SIGLIP_MODEL_DIR", "/models/siglip"))
_IMAGE_ENCODER = _MODEL_DIR / "image_encoder.onnx"
_TEXT_ENCODER  = _MODEL_DIR / "text_encoder.onnx"
_VOCAB_FILE    = _MODEL_DIR / "sentencepiece.model"

# ── Scoring threshold ─────────────────────────────────────────────────────────
RELEVANCE_THRESHOLD: float = float(os.getenv("SIGLIP_THRESHOLD", "0.15"))

# ── Image size expected by siglip-base-patch16-256 ───────────────────────────
_IMG_SIZE = 256
_MEAN = np.array([0.5, 0.5, 0.5], dtype=np.float32)
_STD  = np.array([0.5, 0.5, 0.5], dtype=np.float32)

# ── Max text tokens ───────────────────────────────────────────────────────────
_MAX_SEQ_LEN = 64


# ── Lazy-loaded ONNX sessions ─────────────────────────────────────────────────
# CUDA first, CPU fallback. onnxruntime silently uses the first provider it can
# build; on a host without an sm_120-capable onnxruntime-gpu (Blackwell) it falls
# back to CPU. We log which provider actually loaded so that's never a surprise.
_PROVIDERS = ["CUDAExecutionProvider", "CPUExecutionProvider"]


@lru_cache(maxsize=1)
def _image_session():
    import onnxruntime as ort
    opts = ort.SessionOptions()
    opts.inter_op_num_threads = 2
    opts.intra_op_num_threads = 2
    logger.info("Loading SigLIP image encoder", extra={"path": str(_IMAGE_ENCODER)})
    sess = ort.InferenceSession(str(_IMAGE_ENCODER), sess_options=opts, providers=_PROVIDERS)
    logger.info("SigLIP image encoder provider", extra={"provider": sess.get_providers()[0]})
    return sess


@lru_cache(maxsize=1)
def _text_session():
    import onnxruntime as ort
    opts = ort.SessionOptions()
    opts.inter_op_num_threads = 2
    opts.intra_op_num_threads = 2
    logger.info("Loading SigLIP text encoder", extra={"path": str(_TEXT_ENCODER)})
    sess = ort.InferenceSession(str(_TEXT_ENCODER), sess_options=opts, providers=_PROVIDERS)
    logger.info("SigLIP text encoder provider", extra={"provider": sess.get_providers()[0]})
    return sess


@lru_cache(maxsize=1)
def _sp_model():
    """Load SentencePiece tokenizer."""
    import sentencepiece as spm
    sp = spm.SentencePieceProcessor()
    sp.Load(str(_VOCAB_FILE))
    logger.info("SigLIP SentencePiece tokenizer loaded")
    return sp


def _models_available() -> bool:
    return _IMAGE_ENCODER.exists() and _TEXT_ENCODER.exists() and _VOCAB_FILE.exists()


# ── Preprocessing ─────────────────────────────────────────────────────────────
def _preprocess_image(path: str) -> np.ndarray:
    """Load, resize, normalize → float32 [1, 3, H, W]."""
    img = Image.open(path).convert("RGB")
    img = img.resize((_IMG_SIZE, _IMG_SIZE), Image.BICUBIC)
    arr = np.array(img, dtype=np.float32) / 255.0          # [H, W, 3]
    arr = (arr - _MEAN) / _STD                              # normalize
    arr = arr.transpose(2, 0, 1)[np.newaxis]                # [1, 3, H, W]
    return arr


def _tokenize(text: str) -> Tuple[np.ndarray, np.ndarray]:
    """SentencePiece tokenize → input_ids + attention_mask [1, seq_len]."""
    sp = _sp_model()
    ids = sp.EncodeAsIds(text)
    # SigLIP uses BOS=1, EOS=2 (same as T5)
    ids = [1] + ids[:_MAX_SEQ_LEN - 2] + [2]
    pad_len = _MAX_SEQ_LEN - len(ids)
    mask = [1] * len(ids) + [0] * pad_len
    ids  = ids + [0] * pad_len
    return (
        np.array([ids],  dtype=np.int64),
        np.array([mask], dtype=np.int64),
    )


# ── Embedding helpers ─────────────────────────────────────────────────────────
def _image_embedding(image_path: str) -> np.ndarray:
    pixel_values = _preprocess_image(image_path)
    sess = _image_session()
    input_name = sess.get_inputs()[0].name
    outputs = sess.run(None, {input_name: pixel_values})
    emb = outputs[0][0]                    # [D]
    return emb / (np.linalg.norm(emb) + 1e-8)


def _text_embedding(text: str) -> np.ndarray:
    input_ids, attention_mask = _tokenize(text)
    sess = _text_session()
    in_names = [i.name for i in sess.get_inputs()]
    feed = {}
    for name in in_names:
        if "attention" in name.lower():
            feed[name] = attention_mask
        else:
            feed[name] = input_ids
    outputs = sess.run(None, feed)
    emb = outputs[0][0]                    # [D]
    return emb / (np.linalg.norm(emb) + 1e-8)


# ── Public API ────────────────────────────────────────────────────────────────
def score_image(image_path: str, query_text: str) -> float:
    """
    Return a relevance score in [0, 1] between the image and query_text.

    Uses sigmoid(dot(image_emb, text_emb)) — same as SigLIP's training objective.
    A score >= RELEVANCE_THRESHOLD (default 0.15) is considered relevant.

    Returns 0.0 if models are not available (graceful degradation).
    """
    if not _models_available():
        logger.debug("SigLIP models not found, skipping relevance scoring")
        return 1.0  # pass-through: don't filter if models missing

    try:
        img_emb  = _image_embedding(image_path)
        text_emb = _text_embedding(query_text)
        dot      = float(np.dot(img_emb, text_emb))
        score    = float(1.0 / (1.0 + np.exp(-dot)))   # sigmoid
        return score
    except Exception as exc:
        logger.warning("SigLIP scoring failed", extra={"path": image_path, "error": str(exc)})
        return 1.0  # pass-through on error


def filter_by_relevance(
    image_paths: List[str],
    query_text: str,
    threshold: float = RELEVANCE_THRESHOLD,
    top_k: int = 3,
) -> List[str]:
    """
    Score all images against query_text, keep those above threshold,
    return top_k sorted by score descending.

    Falls back to returning all images unchanged if models unavailable.
    """
    if not _models_available():
        return image_paths[:top_k]

    scored: List[Tuple[float, str]] = []
    for path in image_paths:
        s = score_image(path, query_text)
        logger.info("SigLIP score", extra={"score": round(s, 4), "path": path,
                                            "relevant": s >= threshold})
        scored.append((s, path))

    scored.sort(key=lambda x: x[0], reverse=True)
    kept = [p for s, p in scored if s >= threshold][:top_k]

    logger.info("SigLIP filter result", extra={
        "total": len(image_paths),
        "kept": len(kept),
        "threshold": threshold,
        "top_score": round(scored[0][0], 4) if scored else 0,
    })
    return kept if kept else [p for _, p in scored[:1]]  # always keep best even if below threshold
