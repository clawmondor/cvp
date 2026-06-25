"""Per-model bbox adapters.

Vision models report bounding boxes in different formats.  Each adapter takes
the raw bbox from the model response and returns ``(left, upper, right, lower)``
in image pixels with 15% generous padding applied, or ``None`` if the input is
malformed or the model isn't expected to produce usable bboxes at all.

The 15% padding and clamping behavior mirrors the historical _parse_bbox in
services/vision.py — we move it here unchanged so existing crops stay
visually consistent.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

logger = logging.getLogger(__name__)


class BboxParseError(Exception):
    """Raised when raw bbox input is malformed beyond recovery."""


_PadResult = tuple[int, int, int, int] | None


def _pad_clamp(left: int, upper: int, right: int, lower: int, w: int, h: int) -> _PadResult:
    if left >= right or upper >= lower:
        return None
    pad_x = round((right - left) * 0.15)
    pad_y = round((lower - upper) * 0.15)
    left = max(0, left - pad_x)
    upper = max(0, upper - pad_y)
    right = min(w, right + pad_x)
    lower = min(h, lower + pad_y)
    if left >= right or upper >= lower:
        logger.error("_pad_clamp error left < right or uppper < lower")
        return None
    return left, upper, right, lower


def pixel_passthrough(raw: Any, w: int, h: int) -> _PadResult:
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        left, upper, right, lower = (int(v) for v in raw)
    except (TypeError, ValueError):
        logger.error("TypeError or ValueError", exc_info=True)
        return None
    return _pad_clamp(left, upper, right, lower, w, h)


def gemini_normalized_1000(raw: Any, w: int, h: int) -> _PadResult:
    """Gemini native bbox format: [y_min, x_min, y_max, x_max], normalized 0–1000."""
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        logger.error("couldn't determine bbox", exc_info=True)
        return None
    try:
        n_ymin, n_xmin, n_ymax, n_xmax = (int(v) for v in raw)
    except (TypeError, ValueError):
        logger.error("TypeError or ValueError", exc_info=True)
        return None
    if not all(0 <= v <= 1000 for v in (n_ymin, n_xmin, n_ymax, n_xmax)):
        logger.warning("gemini normalized bbox received")
        return _pad_clamp(n_xmin, n_ymin, n_xmax, n_ymax, w, h)
    left = round(n_xmin / 1000 * w)
    upper = round(n_ymin / 1000 * h)
    right = round(n_xmax / 1000 * w)
    lower = round(n_ymax / 1000 * h)
    return _pad_clamp(left, upper, right, lower, w, h)


def none_adapter(raw: Any, w: int, h: int) -> _PadResult:
    return None


REGISTRY: dict[str, Callable[[Any, int, int], _PadResult]] = {
    "pixel_passthrough": pixel_passthrough,
    "gemini_normalized_1000": gemini_normalized_1000,
    "none": none_adapter,
}


def resolve(name: str) -> Callable[[Any, int, int], _PadResult]:
    fn = REGISTRY.get(name)
    if fn is None:
        logger.warning("unknown vision adapter %r — falling back to 'none'", name)
        return none_adapter
    return fn


# --- Prompt fragments -------------------------------------------------------
# Each decode function above expects coordinates in a specific format.  The
# prompt that elicits those coordinates is defined here, next to the decoder,
# so the encode (prompt) and decode (adapter) contracts cannot drift apart.
# They previously lived in vision_prompts.py as a single pixel-only prompt
# shared by every model; Gemini ignores the pixel instruction and emits its
# native normalized [ymin, xmin, ymax, xmax] format, so the mismatch produced
# wildly tall bounding boxes.

# Format-agnostic guidance shared by every coordinate format.
_GENEROUS_GUIDANCE = (
    "  Be GENEROUS — it is far better to include extra background than to clip any part of the item.\n"
    "  Extend each edge an extra 10–15% past where you think the item ends.\n"
    "  Include the full item extent: soles of footwear, legs of furniture, handles, straps, and any protruding parts.\n"
    "  For footwear, always extend the lower edge to include the complete sole resting on the surface.\n"
    "  Bounding boxes MAY overlap with the bounding boxes of other items — this is expected and encouraged.\n"
    "  Do NOT shrink a box to avoid overlapping a neighbor; always prioritize capturing the full item."
)


@dataclass(frozen=True)
class BboxPrompt:
    """The two prompt fragments that elicit coordinates in an adapter's format.

    ``intro`` goes near the top of the scan prompt (image context); ``field`` is
    the ``"bounding_box"`` bullet in the per-item key list.
    """

    intro: str
    field: str


def _pixel_bbox_prompt(width: int, height: int) -> BboxPrompt:
    ex_left = round(width * 2 / 3)
    ex_right = width - 20
    ex_lower = round(height * 0.85)
    intro = (
        f"The image is exactly {width}×{height} pixels (width × height). "
        "All bounding box coordinates must be within these bounds."
    )
    field = (
        '- "bounding_box": [left, upper, right, lower] — pixel coordinates of the item\'s '
        "bounding box relative to the original image dimensions (top-left origin, x increases "
        "right, y increases down).\n"
        f"  Estimate carefully; every item MUST have one. Ensure 0 ≤ left < right ≤ {width} "
        f"and 0 ≤ upper < lower ≤ {height}.\n"
        f"{_GENEROUS_GUIDANCE}\n"
        f"  Example for an item in the right third of this image: [{ex_left}, 100, {ex_right}, {ex_lower}]"
    )
    return BboxPrompt(intro=intro, field=field)


def _gemini_normalized_bbox_prompt(width: int, height: int) -> BboxPrompt:
    intro = f"This photo is {width}×{height} pixels (width × height)."
    field = (
        '- "bounding_box": [ymin, xmin, ymax, xmax] — the item\'s 2D bounding box in your '
        "native box_2d format: four integers normalized to a 0–1000 scale (top-left origin, "
        "y increases down, x increases right). Do NOT output raw pixel values.\n"
        "  Estimate carefully; every item MUST have one. Ensure 0 ≤ ymin < ymax ≤ 1000 "
        "and 0 ≤ xmin < xmax ≤ 1000.\n"
        f"{_GENEROUS_GUIDANCE}\n"
        "  Example for an item in the right third of this image: [100, 666, 850, 980]"
    )
    return BboxPrompt(intro=intro, field=field)


_BBOX_PROMPTS: dict[str, Callable[[int, int], BboxPrompt]] = {
    "pixel_passthrough": _pixel_bbox_prompt,
    "gemini_normalized_1000": _gemini_normalized_bbox_prompt,
    # "none" never produces usable boxes, but the prompt still needs a shape;
    # the pixel form is the harmless default.
    "none": _pixel_bbox_prompt,
}


def bbox_prompt(name: str, width: int, height: int) -> BboxPrompt:
    """Return the prompt fragments matching adapter ``name``'s coordinate format."""
    fn = _BBOX_PROMPTS.get(name)
    if fn is None:
        logger.warning("no bbox prompt for adapter %r — using pixel format", name)
        fn = _pixel_bbox_prompt
    return fn(width, height)
