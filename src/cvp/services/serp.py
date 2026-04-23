"""SerpAPI caller service."""

import json
import logging
import re

import httpx

from cvp.config import settings
from cvp.models import ItemCrop

logger = logging.getLogger(__name__)

SERP_BASE = "https://serpapi.com/search"

ENGINE_MAP: dict[str, dict] = {
    "google_lens": {"engine": "google_lens"},
}

_SENSITIVE_KEYS = {"api_key"}


def _mask_key(value: str, show_chars: int = 4) -> str:
    if not value:
        return "(not set)"
    if len(value) <= show_chars:
        return "****"
    return f"****...{value[-show_chars:]}"


def _mask_params(params: dict) -> dict:
    return {
        k: (_mask_key(v) if k in _SENSITIVE_KEYS and isinstance(v, str) else v)
        for k, v in params.items()
    }


def _mask_url(url: str) -> str:
    return re.sub(r"([?&]api_key=)[^&]+", lambda m: m.group(1) + "****", url)


def build_crop_url(item_crop: ItemCrop) -> str | None:
    """Return a public URL for the crop if PUBLIC_BASE_URL is configured."""
    if settings.public_base_url and item_crop.crop_path:
        base = settings.public_base_url.rstrip("/")
        return f"{base}/crops/{item_crop.crop_path}"
    return None


def call_serp(
    service: str,
    item_crop: ItemCrop,
    image_url: str | None = None,
) -> tuple[str, dict, dict, int]:
    """
    Call SerpAPI for the given service.

    Returns (request_url, params_dict, response_dict, status_code).
    image_url takes precedence over build_crop_url() if provided.
    """
    if service not in ENGINE_MAP:
        raise ValueError(f"Unknown service: {service}")

    params: dict = {
        "api_key": settings.serp_api_key,
        **ENGINE_MAP[service],
    }

    url = image_url or build_crop_url(item_crop)
    if not url:
        return (
            SERP_BASE,
            params,
            {"error": "No image URL available. Paste a public URL or set PUBLIC_BASE_URL in .env."},
            0,
        )
    params["url"] = url

    logger.debug(
        "SerpAPI request | service=%s crop=%s params=%s",
        service,
        item_crop.id,
        _mask_params(params),
    )

    try:
        with httpx.Client(timeout=30) as client:
            response = client.get(SERP_BASE, params=params)
        status_code = response.status_code
        request_url = str(response.request.url)
        ct = response.headers.get("content-type", "")
        response_data = response.json() if "json" in ct else {"raw": response.text}
    except httpx.TimeoutException:
        logger.warning("SerpAPI timeout | service=%s crop=%s", service, item_crop.id)
        return SERP_BASE, params, {"error": "Request timed out after 30 seconds"}, 0
    except Exception as exc:  # noqa: BLE001
        logger.exception("SerpAPI call failed | service=%s crop=%s", service, item_crop.id)
        return SERP_BASE, params, {"error": str(exc)}, 0

    logger.debug(
        "SerpAPI response | service=%s crop=%s status=%d url=%s",
        service,
        item_crop.id,
        status_code,
        _mask_url(request_url),
    )
    logger.debug(
        "SerpAPI response body | service=%s crop=%s |\n%s",
        service,
        item_crop.id,
        json.dumps(response_data, indent=2, ensure_ascii=False)[:4000],
    )

    return request_url, params, response_data, status_code
