"""Firecrawl web search with schema-guided price extraction.

One POST to /v2/search both searches and scrapes each result page, so a
specialist's click maps to exactly one HTTP call. The async /v2/extract
endpoint is deliberately unused — it polls, which a synchronous HTMX
request cannot do.
"""

import logging
import re
from typing import Any

import httpx

from cvp.config import settings
from cvp.models import Item

logger = logging.getLogger(__name__)

FIRECRAWL_SEARCH_URL = "https://api.firecrawl.dev/v2/search"

# Measured live: limit=2 cost creditsUsed=12, i.e. ~6 credits/scraped page.
# limit=5 therefore costs ~30 credits per search.
_RESULT_LIMIT = 5
_TIMEOUT_SECONDS = 30


def build_query(item: Item) -> str:
    """Join brand, model, and description into a plain search query.

    No marketing words ("buy", "price") — they skew results toward
    affiliate spam rather than retailer product pages.
    """
    parts = [item.brand, item.model, item.description]
    cleaned = [re.sub(r"\s+", " ", p).strip() for p in parts if p and p.strip()]
    return " ".join(cleaned)


PRICE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "product_title": {"type": "string"},
        "price": {"type": "number"},
        "currency": {"type": "string"},
        "retailer": {"type": "string"},
        "in_stock": {"type": "boolean"},
        "is_product_page": {"type": "boolean"},
    },
}


def _build_body(query: str) -> dict[str, Any]:
    """The request body. Carries no credentials — auth rides in the header."""
    return {
        "query": query,
        "limit": _RESULT_LIMIT,
        "sources": [{"type": "web"}],
        "country": "US",
        "scrapeOptions": {
            "onlyMainContent": True,
            "formats": [{"type": "json", "schema": PRICE_SCHEMA}],
        },
    }


def call_firecrawl(query: str) -> tuple[str, dict, dict, int]:
    """Search the web and extract structured prices in one call.

    Returns (request_url, body, response_dict, status_code). The body is safe
    to persist: the API key travels in the Authorization header, never here.
    Never raises — failures come back as {"error": ...} with status_code 0.
    """
    body = _build_body(query)

    if not settings.firecrawl_api_key:
        return (
            FIRECRAWL_SEARCH_URL,
            body,
            {"error": "Firecrawl is not configured. Set FIRECRAWL_API_KEY."},
            0,
        )

    headers = {"Authorization": f"Bearer {settings.firecrawl_api_key}"}

    try:
        with httpx.Client(timeout=_TIMEOUT_SECONDS) as client:
            response = client.post(FIRECRAWL_SEARCH_URL, json=body, headers=headers)
    except httpx.TimeoutException:
        logger.warning("Firecrawl timeout | query=%s", query)
        return (
            FIRECRAWL_SEARCH_URL,
            body,
            {"error": f"Request timed out after {_TIMEOUT_SECONDS} seconds"},
            0,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Firecrawl call failed | query=%s", query)
        return FIRECRAWL_SEARCH_URL, body, {"error": str(exc)}, 0

    # Parsed outside the try above so a malformed body keeps the real HTTP
    # status instead of collapsing into the generic status_code=0 branch.
    status_code = response.status_code
    ct = response.headers.get("content-type", "")
    response_data: dict[str, Any] = {"raw": response.text}
    if "json" in ct:
        try:
            response_data = response.json()
        except ValueError:
            logger.warning("Firecrawl returned unparseable JSON | status=%d", status_code)

    logger.debug(
        "Firecrawl response | query=%s status=%d credits=%s",
        query,
        status_code,
        response_data.get("creditsUsed") if isinstance(response_data, dict) else None,
    )
    return FIRECRAWL_SEARCH_URL, body, response_data, status_code
