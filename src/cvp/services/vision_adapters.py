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
        return None
    return left, upper, right, lower


def pixel_passthrough(raw: Any, w: int, h: int) -> _PadResult:
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        left, upper, right, lower = (int(v) for v in raw)
    except (TypeError, ValueError):
        return None
    return _pad_clamp(left, upper, right, lower, w, h)


def gemini_normalized_1000(raw: Any, w: int, h: int) -> _PadResult:
    """Gemini native bbox format: [y_min, x_min, y_max, x_max], normalized 0–1000."""
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        n_ymin, n_xmin, n_ymax, n_xmax = (int(v) for v in raw)
    except (TypeError, ValueError):
        return None
    if not all(0 <= v <= 1000 for v in (n_ymin, n_xmin, n_ymax, n_xmax)):
        return None
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
