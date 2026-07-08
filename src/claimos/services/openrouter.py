"""OpenRouter HTTP client for vision calls and model catalog discovery.

Replaces the historical anthropic.Anthropic client.  Uses the OpenAI-compatible
chat completions endpoint with a base64 data: URL for the image part.
"""

from __future__ import annotations

import base64
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_BASE_URL = "https://openrouter.ai/api/v1"
_CHAT_URL = f"{_BASE_URL}/chat/completions"
_MODELS_URL = f"{_BASE_URL}/models"


class OpenRouterError(Exception):
    """Raised on any non-2xx response from OpenRouter."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"{status}: {message}")
        self.status = status
        self.message = message


def _headers() -> dict[str, str]:
    # Read directly from env so tests can monkeypatch before calling.
    # Fall back to settings for non-key fields (referer, title) which are
    # less likely to be mutated in tests.
    from claimos.config import settings

    api_key = os.environ.get("OPENROUTER_API_KEY") or settings.openrouter_api_key
    h: dict[str, str] = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    referer = os.environ.get("OPENROUTER_REFERER") or settings.openrouter_referer
    title = os.environ.get("OPENROUTER_APP_TITLE") or settings.openrouter_app_title
    if referer:
        h["HTTP-Referer"] = referer
    if title:
        h["X-Title"] = title
    return h


def call_vision(
    model_slug: str,
    image_bytes: bytes,
    mime_type: str,
    prompt: str,
    *,
    timeout_seconds: float = 120.0,
) -> str:
    """POST to OpenRouter chat completions; return the raw text content of the
    first choice. Raises OpenRouterError on 4xx/5xx, httpx.TimeoutException on
    timeout."""
    b64 = base64.standard_b64encode(image_bytes).decode()
    payload = {
        "model": model_slug,
        "max_tokens": 4096,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{b64}"},
                    },
                ],
            }
        ],
    }
    with httpx.Client(timeout=timeout_seconds) as client:
        resp = client.post(_CHAT_URL, headers=_headers(), json=payload)
    if resp.status_code >= 400:
        try:
            err = resp.json().get("error", {}).get("message") or resp.text
        except Exception:  # noqa: BLE001
            err = resp.text
        raise OpenRouterError(resp.status_code, err)
    data = resp.json()
    choices = data.get("choices") or []
    if not choices:
        return ""
    return choices[0].get("message", {}).get("content", "") or ""


def fetch_models() -> list[dict[str, Any]]:
    """Return the OpenRouter model catalog filtered to vision-capable entries."""
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(_MODELS_URL, headers=_headers())
    if resp.status_code >= 400:
        raise OpenRouterError(resp.status_code, resp.text[:500])
    data = resp.json().get("data") or []
    out: list[dict[str, Any]] = []
    for m in data:
        modalities = (m.get("architecture") or {}).get("input_modalities") or []
        if "image" in modalities:
            out.append(m)
    return out


def parse_pricing_to_cents(value: Any) -> int | None:
    """OpenRouter returns pricing as decimal-string USD-per-image (e.g. '0.025').
    Convert to integer cents.  Returns None for missing, negative, or unparseable inputs.
    Sub-cent prices (e.g. '$0.003/img') round to 0 cents and are stored as 0 — shown
    as '~$0.00' rather than '~$?' so the specialist knows the pricing was captured."""
    if value is None or value == "":
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f < 0:
        return None
    return round(f * 100)
