"""
Keyword extractor module for the image-fetcher service.

Extracts 1-5 keywords from scene narration_text and visual_description
using an LLM call. Falls back to simple tokenization on failure.

Validates: Requirements 2.1
"""

import json
import logging
import re
from typing import List

from shared.config import settings
from shared.llm_client import get_llm_client

logger = logging.getLogger(__name__)

# System prompt instructing the model to return a JSON array of search terms.
# Constraints mirror MoneyPrinterTurbo's term-generation prompt: short focused
# terms (1-3 words) that always carry the scene's main subject search far better
# on Pexels/Pixabay than long descriptive phrases.
KEYWORD_EXTRACTION_SYSTEM_PROMPT = """You are a stock-image search-term generator. From the narration and visual description, produce 3-5 search terms for finding contextual photos.

Rules:
1. Each term is 1-3 words. No long phrases.
2. Every term must include the scene's MAIN SUBJECT (the concrete thing the scene is about), so a generic word never returns off-topic images.
3. English only.
4. Return ONLY a JSON array of strings — no markdown, no explanation.

Example (scene about photosynthesis):
["photosynthesis", "green leaf", "chloroplast cell", "sunlight plant"]"""

KEYWORD_EXTRACTION_USER_PROMPT_TEMPLATE = """Generate 3-5 stock-image search terms (1-3 words each, always include the main subject) for this scene.

Narration text: {narration_text}

Visual description: {visual_description}

Return only a JSON array of search terms."""

STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from",
    "if", "in", "into", "is", "it", "its", "no", "not", "of", "on", "or",
    "such", "that", "the", "their", "then", "there", "these", "they", "this",
    "to", "was", "were", "will", "with",
    # Common sentence starters and connectors that slip through
    "when", "where", "who", "what", "why", "how", "every", "all", "some",
    "each", "few", "many", "most", "other", "another", "both", "either",
    "neither", "much", "more", "less", "very", "just", "only",
    "now", "here", "so", "than", "too", "can", "could", "should", "would",
    "may", "might", "must", "shall", "do", "does", "did", "has", "have",
    "had", "been", "being", "am", "we", "you", "he", "she", "us", "them",
}


def extract_keywords(narration_text: str, visual_description: str) -> List[str]:
    """
    Extract 1-5 keywords from narration_text and visual_description using an LLM.
    
    Makes a single NVIDIA chat completion call per scene. The system prompt
    instructs the model to return a JSON array of 1-5 keywords.
    
    On JSON parse failure, falls back to a filtered token list from narration_text.
    
    Args:
        narration_text: The narration text for the scene.
        visual_description: The visual description for the scene.
    
    Returns:
        A list of 1-5 keyword strings.
    
    Validated by: Property-based tests for keyword count in [1, 5]
    Validates: Requirements 2.1
    """
    client = get_llm_client()
    
    user_prompt = KEYWORD_EXTRACTION_USER_PROMPT_TEMPLATE.format(
        narration_text=narration_text,
        visual_description=visual_description
    )
    
    try:
        response = client.chat.completions.create(
            model=settings.COMPOSITOR_LLM_MODEL,
            messages=[
                {"role": "system", "content": KEYWORD_EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.3,
            max_tokens=100
        )
        
        content = response.choices[0].message.content
        if content is None:
            logger.warning("LLM returned None content, falling back to tokenization")
            return _fallback_tokenize(narration_text)
        
        # Parse the JSON response
        keywords = _parse_keywords_json(content)
        keywords = _clean_keywords(keywords)
        
        if keywords:
            # Ensure we return 1-5 keywords
            return keywords[:5] if len(keywords) > 5 else keywords
        
        logger.warning("Parsed empty keyword list, falling back to tokenization")
        return _fallback_tokenize(narration_text)
        
    except json.JSONDecodeError as e:
        logger.warning(
            f"LLM keyword extraction returned unparseable JSON ({e}); using regex "
            "fallback — image search quality may degrade"
        )
        return _fallback_tokenize(narration_text)
    except Exception as e:
        logger.warning(
            f"LLM keyword extraction failed ({e}); using regex fallback — "
            "image search quality may degrade. Check NVIDIA_API_KEY / NIM reachability."
        )
        return _fallback_tokenize(narration_text)


def _parse_keywords_json(content: str) -> List[str]:
    """
    Parse the LLM response content as a JSON array of keywords.
    
    Handles cases where the response might contain markdown code blocks
    or other formatting around the JSON.
    
    Args:
        content: The raw content string from the LLM response.
    
    Returns:
        A list of keyword strings, or empty list if parsing fails.
    """
    content = content.strip()
    
    # Try to extract JSON from markdown code blocks if present
    if "```" in content:
        # Find content between code block markers
        lines = content.split("\n")
        json_lines = []
        in_code_block = False
        for line in lines:
            if line.strip().startswith("```"):
                in_code_block = not in_code_block
                continue
            if in_code_block:
                json_lines.append(line)
        content = "\n".join(json_lines).strip()
    
    # Try to find JSON array in the content
    start_idx = content.find("[")
    end_idx = content.rfind("]")
    
    if start_idx == -1 or end_idx == -1 or end_idx <= start_idx:
        raise json.JSONDecodeError("No JSON array found", content, 0)
    
    json_str = content[start_idx:end_idx + 1]
    keywords = json.loads(json_str)
    
    # Validate it's a list of strings
    if not isinstance(keywords, list):
        raise json.JSONDecodeError("Response is not a JSON array", json_str, 0)
    
    # Filter to only string elements and strip whitespace
    return [str(k).strip() for k in keywords if k]


def _clean_keywords(keywords: List[str]) -> List[str]:
    """Normalize and filter keywords for better search quality."""
    cleaned: List[str] = []
    seen: set[str] = set()
    for kw in keywords:
        token = str(kw).strip().lower()
        if not token or token in STOP_WORDS or len(token) < 2:
            continue
        if token in seen:
            continue
        seen.add(token)
        cleaned.append(token)
    return cleaned


def _fallback_tokenize(narration_text: str) -> List[str]:
    """
    Fallback tokenizer that filters narration_text into 1-5 useful keywords.
    
    Args:
        narration_text: The narration text to tokenize.
    
    Returns:
        A list of up to 3 tokens from the narration text.
    """
    tokens = re.split(r"\W+", narration_text.lower())
    tokens = [t for t in tokens if t and t not in STOP_WORDS and len(t) >= 2]
    tokens = _clean_keywords(tokens)
    return tokens[:5] if tokens else ["image"]  # Ensure at least one keyword
