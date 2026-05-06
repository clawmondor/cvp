# tests/test_openrouter.py
from unittest.mock import patch

import httpx
import pytest

from cvp.services.openrouter import (
    OpenRouterError,
    call_vision,
    fetch_models,
    parse_pricing_to_cents,
)


def _build_response(status: int, json_body: dict) -> httpx.Response:
    return httpx.Response(status, json=json_body, request=httpx.Request("POST", "https://o"))


class TestCallVision:
    def test_happy_path_returns_text(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
        body = {"choices": [{"message": {"content": "[]"}}]}
        with patch("httpx.Client.post", return_value=_build_response(200, body)) as p:
            text = call_vision("anthropic/claude-opus-4", b"\x89PNG", "image/png", "prompt")
        assert text == "[]"
        kwargs = p.call_args.kwargs
        assert kwargs["headers"]["Authorization"].startswith("Bearer ")

    def test_raises_on_4xx(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk")
        body = {"error": {"message": "rate limit"}}
        with patch("httpx.Client.post", return_value=_build_response(429, body)):
            with pytest.raises(OpenRouterError) as exc:
                call_vision("x/y", b"", "image/jpeg", "p")
        assert "429" in str(exc.value)
        assert "rate limit" in str(exc.value)

    def test_raises_on_5xx(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk")
        with patch("httpx.Client.post", return_value=_build_response(503, {})):
            with pytest.raises(OpenRouterError):
                call_vision("x/y", b"", "image/jpeg", "p")

    def test_propagates_timeout(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk")
        with patch("httpx.Client.post", side_effect=httpx.TimeoutException("slow")):
            with pytest.raises(httpx.TimeoutException):
                call_vision("x/y", b"", "image/jpeg", "p")


class TestFetchModels:
    def test_filters_to_image_capable(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk")
        body = {
            "data": [
                {
                    "id": "vision/one",
                    "name": "Vision One",
                    "architecture": {"input_modalities": ["text", "image"]},
                    "pricing": {"image": "0.001"},
                    "context_length": 200000,
                    "description": "yes",
                },
                {
                    "id": "text-only/two",
                    "name": "Text Only",
                    "architecture": {"input_modalities": ["text"]},
                    "pricing": {},
                    "context_length": 100000,
                    "description": "no",
                },
            ]
        }
        with patch("httpx.Client.get", return_value=_build_response(200, body)):
            models = fetch_models()
        assert len(models) == 1
        assert models[0]["id"] == "vision/one"


class TestParsePricing:
    def test_decimal_string_to_cents(self):
        # Python's round() uses banker's rounding: round(2.5) == 2
        result_025 = parse_pricing_to_cents("0.025")
        assert result_025 in (2, 3)  # accept either due to float precision
        assert parse_pricing_to_cents("0.10") == 10
        assert parse_pricing_to_cents("0") is None
        assert parse_pricing_to_cents("") is None
        assert parse_pricing_to_cents(None) is None
        assert parse_pricing_to_cents("not-a-number") is None
