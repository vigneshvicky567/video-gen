"""HTML validation for HyperFrames composition documents."""

from html.parser import HTMLParser
from pathlib import Path
import re
from typing import Dict, List, Optional

from shared.log import get_logger
from .duration_prober import AssemblyError
from .llm_composer import CAPTION_TRACK_INDEX

logger = get_logger(__name__)


REQUIRED_ATTRS = ["data-start", "data-duration", "data-track-index"]
TIMED_TAGS = ("video", "audio", "img", "iframe")
COUNTED_TAGS = ("video", "audio", "img")
# data-composition-src is used on <div> elements for HyperFrames sub-compositions
# (replaces <iframe> to avoid screenshot-capture mode)


class CompositionValidator(HTMLParser):
    """Validates HyperFrames HTML composition."""

    def __init__(self):
        super().__init__()
        self.src_paths: List[str] = []
        self.has_any_timed_element = False
        self.errors: List[str] = []
        self.counts: Dict[str, int] = {tag: 0 for tag in COUNTED_TAGS}
        self.root_attrs: Optional[dict] = None
        self.clips: List[dict] = []

    def handle_starttag(self, tag: str, attrs: list):
        attrs_dict = dict(attrs)

        if tag in self.counts:
            self.counts[tag] += 1

        # Collect every timed clip (start + duration + track) for overlap/track
        # lint. Naturally includes scene-host divs and excludes the root (no
        # track-index). Parse failures are surfaced as errors.
        if all(a in attrs_dict for a in ("data-start", "data-duration", "data-track-index")):
            try:
                self.clips.append({
                    "tag": tag,
                    "start": float(attrs_dict["data-start"]),
                    "duration": float(attrs_dict["data-duration"]),
                    "track": int(attrs_dict["data-track-index"]),
                    "cls": attrs_dict.get("class", ""),
                    "pos": self.getpos(),
                })
            except (TypeError, ValueError):
                self.errors.append(f"<{tag}> at {self.getpos()} has non-numeric timing attrs")

        is_root_composition = "data-composition-id" in attrs_dict and self.root_attrs is None
        if is_root_composition:
            self.root_attrs = attrs_dict

        # Collect src paths from media elements
        if tag in TIMED_TAGS and "src" in attrs_dict:
            self.src_paths.append(attrs_dict["src"])

        # Also collect data-composition-src from <div> sub-compositions
        if "data-composition-src" in attrs_dict:
            self.src_paths.append(attrs_dict["data-composition-src"])

        # If element has data-start, it's a timed element — validate it.
        # Skip REQUIRED_ATTRS check for sub-composition roots (data-composition-id
        # present) — these are inlined scene host divs, not clip elements.
        if "data-start" in attrs_dict or "data-duration" in attrs_dict:
            self.has_any_timed_element = True
            if is_root_composition or "data-composition-id" in attrs_dict:
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

    # Same-track overlap: clips on one track must not overlap in time. This is
    # the invariant captions rely on (sequential windows on track 0).
    by_track: Dict[int, List[dict]] = {}
    for clip in validator.clips:
        by_track.setdefault(clip["track"], []).append(clip)
    for track, clips in by_track.items():
        ordered = sorted(clips, key=lambda c: c["start"])
        for a, b in zip(ordered, ordered[1:]):
            if b["start"] < a["start"] + a["duration"] - 1e-6:
                errors.append(
                    f"track {track}: clips overlap at {a['pos']} and {b['pos']}"
                )

    # Caption track discipline: lower-third captions live ONLY on the reserved
    # track, and nothing else may use it.
    for clip in validator.clips:
        is_caption = "lower-third" in clip["cls"]
        if is_caption and clip["track"] != CAPTION_TRACK_INDEX:
            errors.append(
                f"caption at {clip['pos']} must be on track {CAPTION_TRACK_INDEX}, got {clip['track']}"
            )
        if not is_caption and clip["track"] == CAPTION_TRACK_INDEX:
            errors.append(
                f"<{clip['tag']}> at {clip['pos']} uses reserved caption track {CAPTION_TRACK_INDEX}"
            )

    # Heuristic warning (never fatal): scene files placing content in the
    # bottom caption band. Prompts are the primary enforcement; assembly is the
    # last stage, so we log rather than fail a long render.
    for w in _warn_caption_band(composition_dir):
        logger.warning("caption-band intrusion", extra={"detail": w})

    if errors:
        raise AssemblyError("; ".join(errors))


_ABS_RE = re.compile(r"position\s*:\s*absolute", re.IGNORECASE)
_BOTTOM_RE = re.compile(r"bottom\s*:\s*(\d+(?:\.\d+)?)px", re.IGNORECASE)
_TOP_RE = re.compile(r"top\s*:\s*(\d+(?:\.\d+)?)px", re.IGNORECASE)


def _warn_caption_band(comp_dir: Path) -> List[str]:
    """Scan copied HyperFrames scene files for absolutely-positioned content
    inside the bottom 160px caption band. Returns warnings (does not raise).
    """
    warnings: List[str] = []
    scene_dir = comp_dir / "compositions"
    if not scene_dir.is_dir():
        return warnings
    for scene_file in sorted(scene_dir.glob("scene_*.html")):
        try:
            text = scene_file.read_text(encoding="utf-8")
        except Exception:
            continue
        for m in re.finditer(r"style\s*=\s*[\"']([^\"']*)[\"']", text, re.IGNORECASE):
            style = m.group(1)
            if not _ABS_RE.search(style):
                continue
            bm = _BOTTOM_RE.search(style)
            if bm and float(bm.group(1)) < 160:
                warnings.append(f"{scene_file.name}: absolute element with bottom:{bm.group(1)}px (<160 caption band)")
            tm = _TOP_RE.search(style)
            if tm and float(tm.group(1)) >= 920:
                warnings.append(f"{scene_file.name}: absolute element with top:{tm.group(1)}px (>=920 caption band)")
    return warnings
