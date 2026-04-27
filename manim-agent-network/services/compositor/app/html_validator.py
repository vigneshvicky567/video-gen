"""HTML validation for HyperFrames composition documents.

This module provides functionality to:
1. Parse HTML composition documents
2. Extract and validate media file references
3. Validate required HyperFrames attributes
4. Count media element types
"""

from html.parser import HTMLParser
from pathlib import Path
from typing import List, Set, Tuple

from .duration_prober import AssemblyError


# Required attributes for HyperFrames timed elements
REQUIRED_ATTRS = ["data-start", "data-duration", "data-track-index"]
REQUIRED_CLASS = "clip"


class CompositionValidator(HTMLParser):
    """HTML parser that collects src attributes from video, audio, and img tags.
    
    Attributes:
        src_paths: List of all src attribute values found in media elements
        counts: Dictionary tracking count of each media element type
        missing_clip_class: Set of elements missing class="clip"
        missing_required_attrs: Dict mapping element to set of missing attributes
        video_not_muted: List of video elements without muted attribute
    """
    
    def __init__(self):
        super().__init__()
        self.src_paths: List[str] = []
        self.counts = {"video": 0, "audio": 0, "img": 0}
        self.missing_clip_class: Set[str] = set()
        self.missing_required_attrs: dict = {}  # element -> set of missing attrs
        self.video_not_muted: List[str] = []
        self._current_element: str = ""
        self._current_attrs: dict = {}
    
    def handle_starttag(self, tag: str, attrs: list):
        """Handle opening tags, collecting src attributes from media elements.
        
        Args:
            tag: The HTML tag name
            attrs: List of (attribute, value) tuples
        """
        if tag in self.counts:
            self.counts[tag] += 1
        
        attrs_dict = dict(attrs)
        
        # Track current element for error reporting
        self._current_element = tag
        self._current_attrs = attrs_dict
        
        # Collect src paths
        if tag in ("video", "audio", "img") and "src" in attrs_dict:
            self.src_paths.append(attrs_dict["src"])
        
        # Validate class="clip" for timed elements
        element_class = attrs_dict.get("class", "")
        if tag in ("video", "audio", "img", "div", "span", "h1", "h2", "h3", "p", "iframe"):
            if REQUIRED_CLASS not in element_class.split():
                self.missing_clip_class.add(f"<{tag}> at position {self.getpos()}")
        
        # Validate required data attributes for elements with class="clip"
        if REQUIRED_CLASS in element_class.split():
            missing_attrs = set()
            for req_attr in REQUIRED_ATTRS:
                if req_attr not in attrs_dict:
                    missing_attrs.add(req_attr)
            if missing_attrs:
                self.missing_required_attrs[f"<{tag}>"] = missing_attrs
        
        # Check video elements are muted
        if tag == "video" and "muted" not in attrs_dict:
            self.video_not_muted.append(f"<video> at position {self.getpos()}")


def validate_composition(html_path: str) -> None:
    """Parse HTML composition and verify all requirements.
    
    Validates:
    1. HTML is well-formed
    2. All src paths exist on disk
    3. All timed elements have class="clip"
    4. All elements with class="clip" have data-start, data-duration, data-track-index
    5. Video elements are muted
    
    Args:
        html_path: Path to the HTML composition file
        
    Raises:
        HTMLParseError: If the HTML is malformed (propagated from HTMLParser)
        AssemblyError: If any validation fails
    """
    content = Path(html_path).read_text()
    validator = CompositionValidator()
    validator.feed(content)  # raises HTMLParseError if malformed
    
    errors: List[str] = []
    
    # Check for missing media files
    missing = [p for p in validator.src_paths if not Path(p).exists()]
    if missing:
        errors.append(f"Missing media files: {missing}")
    
    # Check for missing class="clip"
    if validator.missing_clip_class:
        errors.append(f"Elements missing class='clip': {validator.missing_clip_class}")
    
    # Check for missing required attributes
    if validator.missing_required_attrs:
        attr_errors = [
            f"{elem} missing: {attrs}" 
            for elem, attrs in validator.missing_required_attrs.items()
        ]
        errors.append(f"Elements missing required attributes: {attr_errors}")
    
    # Check for video elements not muted
    if validator.video_not_muted:
        errors.append(f"Video elements not muted: {validator.video_not_muted}")
    
    if errors:
        raise AssemblyError("; ".join(errors))
