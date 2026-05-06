# tests/test_vision_adapters.py
from cvp.services.vision_adapters import (
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
        # Gemini box [100, 200, 300, 400] in 0..1000 space, image 2000x1000
        # => left=200, upper=200, right=600, lower=400 (pre-padding)
        # 15% padding of 400x200: pad_x=round(400*0.15)=60, pad_y=round(200*0.15)=30
        # left=200-60=140, upper=200-30=170, right=600+60=660, lower=400+30=430
        out = gemini_normalized_1000([100, 200, 300, 400], 2000, 1000)
        assert out == (140, 170, 660, 430)

    def test_clamps_to_image_bounds(self):
        out = gemini_normalized_1000([0, 0, 1000, 1000], 500, 500)
        assert out == (0, 0, 500, 500)

    def test_rejects_out_of_range(self):
        assert gemini_normalized_1000([0, 0, 1500, 500], 500, 500) is None

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
