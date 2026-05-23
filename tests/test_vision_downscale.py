"""Unit tests for vision._downscale."""

import io

from PIL import Image


def _make_jpeg_bytes(w: int, h: int, size_hint_mb: float = 0) -> bytes:
    """Create a JPEG image. If size_hint_mb > 0, pad to exceed that many bytes."""
    img = Image.new("RGB", (w, h), color=(128, 64, 32))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=95)
    data = buf.getvalue()
    if size_hint_mb > 0:
        target = int(size_hint_mb * 1_000_000)
        while len(data) < target:
            data = data + b"\x00" * 10_000
    return data


def test_downscale_large_image_resizes():
    from cvp.services.vision import _downscale

    big_bytes = _make_jpeg_bytes(3000, 2000, size_hint_mb=1.1)
    result_bytes, mime = _downscale(big_bytes)

    assert mime == "image/jpeg"
    with Image.open(io.BytesIO(result_bytes)) as img:
        w, h = img.size
        assert max(w, h) <= 1568


def test_downscale_small_image_preserves_dimensions():
    from cvp.services.vision import _downscale

    small_bytes = _make_jpeg_bytes(800, 600)
    result_bytes, mime = _downscale(small_bytes)

    assert mime == "image/jpeg"
    with Image.open(io.BytesIO(result_bytes)) as img:
        assert img.size == (800, 600)


def test_downscale_portrait_respects_long_edge():
    from cvp.services.vision import _downscale

    tall_bytes = _make_jpeg_bytes(400, 3000, size_hint_mb=1.1)
    result_bytes, _ = _downscale(tall_bytes)

    with Image.open(io.BytesIO(result_bytes)) as img:
        w, h = img.size
        assert h <= 1568  # portrait: height is long edge
        assert w < h
