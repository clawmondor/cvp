# tests/test_vision_models_service.py
from claimos.services.vision_models import (
    is_recommended,
    suggest_adapter,
)


class TestSuggestAdapter:
    def test_anthropic_returns_pixel_passthrough(self):
        assert suggest_adapter("anthropic/claude-opus-4") == "pixel_passthrough"

    def test_gemini_returns_normalized(self):
        assert suggest_adapter("google/gemini-2.5-pro") == "gemini_normalized_1000"

    def test_unknown_returns_none(self):
        assert suggest_adapter("openai/gpt-4o") == "none"


class TestIsRecommended:
    def test_known_slug(self):
        assert is_recommended("anthropic/claude-opus-4") is True

    def test_unknown_slug(self):
        assert is_recommended("random/model") is False
