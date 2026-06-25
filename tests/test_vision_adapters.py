# tests/test_vision_adapters.py
from cvp.services.vision_adapters import (
    bbox_prompt,
    gemini_normalized_1000,
    none_adapter,
    pixel_passthrough,
    resolve,
)


class TestPixelPassthrough:
    def test_basic(self):
        assert pixel_passthrough([100, 200, 300, 400], 1000, 800) is not None

    def test_returns_padded_clamped_box(self):
        # 15% padding of 200x200 box => 30 each side
        out = pixel_passthrough([100, 100, 300, 300], 1000, 1000)
        assert out == (70, 70, 330, 330)

    def test_clamps_to_image_bounds(self):
        out = pixel_passthrough([0, 0, 1000, 1000], 1000, 1000)
        assert out == (0, 0, 1000, 1000)

    def test_rejects_non_list(self):
        assert pixel_passthrough("not a list", 1000, 1000) is None

    def test_rejects_wrong_length(self):
        assert pixel_passthrough([1, 2, 3], 1000, 1000) is None

    def test_rejects_inverted(self):
        assert pixel_passthrough([300, 300, 100, 100], 1000, 1000) is None


class TestGeminiNormalized:
    def test_scales_0_1000_to_pixels(self):
        # Gemini native format: [y_min, x_min, y_max, x_max] in 0..1000 space
        # Input [100, 200, 300, 400] on image 2000x1000:
        #   y_min=100, x_min=200, y_max=300, x_max=400
        #   => left=400, upper=100, right=800, lower=300 (pre-padding)
        # 15% padding of 400w x 200h: pad_x=60, pad_y=30
        #   => left=340, upper=70, right=860, lower=330
        out = gemini_normalized_1000([100, 200, 300, 400], 2000, 1000)
        assert out == (340, 70, 860, 330)

    def test_clamps_to_image_bounds(self):
        out = gemini_normalized_1000([0, 0, 1000, 1000], 500, 500)
        assert out == (0, 0, 500, 500)

    def test_rejects_out_of_range(self):
        assert gemini_normalized_1000([0, 0, 1500, 500], 500, 1500) == (0, 0, 500, 1500)

    def test_rejects_non_list(self):
        assert gemini_normalized_1000("nope", 500, 500) is None


class TestNoneAdapter:
    def test_always_returns_none(self):
        assert none_adapter([1, 2, 3, 4], 100, 100) is None
        assert none_adapter(None, 100, 100) is None


class TestResolve:
    def test_known_name(self):
        assert resolve("pixel_passthrough") is pixel_passthrough

    def test_unknown_falls_back_to_none(self):
        assert resolve("does_not_exist") is none_adapter


class TestBboxPrompt:
    """The prompt fragment must elicit coordinates in the format the matching
    decode function expects — otherwise the model and adapter disagree and
    boxes come out wrong (the Gemini full-height-box bug)."""

    def test_pixel_uses_left_upper_right_lower(self):
        bp = bbox_prompt("pixel_passthrough", 1024, 768)
        assert "[left, upper, right, lower]" in bp.field
        assert "pixel coordinates" in bp.field
        assert "1024" in bp.intro
        assert "768" in bp.intro

    def test_gemini_uses_normalized_ymin_xmin(self):
        bp = bbox_prompt("gemini_normalized_1000", 1024, 768)
        assert "[ymin, xmin, ymax, xmax]" in bp.field
        assert "1000" in bp.field
        # Must NOT ask Gemini for pixel left/upper/right/lower — that contract
        # mismatch is exactly what corrupts the vertical coordinates.
        assert "[left, upper, right, lower]" not in bp.field

    def test_unknown_adapter_falls_back_to_pixel(self):
        bp = bbox_prompt("does_not_exist", 800, 600)
        assert "[left, upper, right, lower]" in bp.field
