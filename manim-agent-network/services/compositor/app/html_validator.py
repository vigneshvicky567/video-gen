"""HTML validation for HyperFrames composition documents."""

from html.parser import HTMLParser
from pathlib import Path
import re
from typing import Dict, List, Optional

from .duration_prober import AssemblyError


REQUIRED_ATTRS = ["data-start", "data-duration", "data-track-index"]
TIMED_TAGS = ("video", "audio", "img", "iframe")
COUNTED_TAGS = ("video", "audio", "img")


class CompositionValidator(HTMLParser):
    """Validates HyperFrames HTML composition."""

    def __init__(self):
        super().__init__()
        self.src_paths: List[str] = []
        self.has_any_timed_element = False
        self.errors: List[str] = []
        self.counts: Dict[str, int] = {tag: 0 for tag in COUNTED_TAGS}
        self.root_attrs: Optional[dict] = None

    def handle_starttag(self, tag: str, attrs: list):
        attrs_dict = dict(attrs)

        if tag in self.counts:
            self.counts[tag] += 1

        is_root_composition = "data-composition-id" in attrs_dict and self.root_attrs is None
        if is_root_composition:
            self.root_attrs = attrs_dict

        # Collect src paths from media elements
        if tag in TIMED_TAGS and "src" in attrs_dict:
            self.src_paths.append(attrs_dict["src"])

        # If element has data-start, it's a timed element — validate it
        if "data-start" in attrs_dict or "data-duration" in attrs_dict:
            self.has_any_timed_element = True
            if is_root_composition:
                return
            missing = [a for a in REQUIRED_ATTRS if a not in attrs_dict]
            if missing:
                self.errors.append(
                    f"<{tag}> at {self.getpos()} missing: {missing}"
                )
            if tag in ("video", "audio") and "id" not in attrs_dict:
                self.errors.append(f"<{tag}> at {self.getpos()} missing: ['id']")
            if tag == "video":
                if "muted" not in attrs_dict:
                    self.errors.append(f"<video> at {self.getpos()} missing muted")
                if "playsinline" not in attrs_dict:
                    self.errors.append(f"<video> at {self.getpos()} missing playsinline")


def validate_composition(html_path: str) -> None:
    """Parse HTML composition and verify all requirements.

    Validates:
    1. HTML is parseable
    2. At least one timed element exists
    3. All timed elements have data-start, data-duration, data-track-index
    4. All referenced media files exist on disk

    Raises:
        AssemblyError: If any validation fails
    """
    html_path_obj = Path(html_path)
    content = html_path_obj.read_text()
    validator = CompositionValidator()
    validator.feed(content)

    errors: List[str] = []

    # Must have at least one timed element
    if not validator.has_any_timed_element:
        errors.append("No timed elements (data-start) found in composition HTML")

    if validator.root_attrs is None:
        errors.append("Root composition is missing data-composition-id")
    else:
        root = validator.root_attrs
        for attr in ("data-start", "data-duration", "data-width", "data-height"):
            if attr not in root:
                errors.append(f"Root composition missing {attr}")
        if root.get("data-width") != "1920" or root.get("data-height") != "1080":
            errors.append("Root composition dimensions must be 1920x1080")

    # Check for missing required attributes on timed elements
    if validator.errors:
        errors.extend(validator.errors)

    if "window.__timelines" not in content:
        errors.append("Missing window.__timelines registration")
    if "window.__timelines.push" in content:
        errors.append("Invalid timeline registration: use window.__timelines['main'] = tl")
    if not re.search(r"window\.__timelines\s*\[\s*['\"]main['\"]\s*\]\s*=", content):
        errors.append("Missing window.__timelines['main'] assignment")

    # Check for missing media files (only local paths, skip http/https)
    # Resolve paths relative to the composition HTML directory
    composition_dir = html_path_obj.parent
    missing = []
    for p in validator.src_paths:
        if not p.startswith("http"):
            # Resolve relative paths from composition directory
            full_path = composition_dir / p
            if not full_path.exists():
                missing.append(p)
    
    if missing:
        errors.append(f"Missing media files: {missing}")

    if errors:
        raise AssemblyError("; ".join(errors))
