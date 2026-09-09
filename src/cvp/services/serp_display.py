"""Per-service result extractors for SerpAPI and Firecrawl responses.

Public API
----------
extract_results(service, response_dict, brand=None) -> list[dict]
    Returns up to 5 normalized result dicts for the given service.
    Returns [] for unmapped services or empty responses.
    `brand` (optional) is used to determine match_type when a service
    can confirm a title actually names the known brand.

Each result dict has these keys (all values may be None unless noted):
    title       : str | None
    source      : str | None
    link        : str | None
    thumbnail   : str | None
    source_icon : str | None
    price_cents : int | None   — extracted price in integer cents, or None
    match_type  : str          — "exact" or "nearest_comparable"
"""

import json
from collections.abc import Callable
from urllib.parse import urlparse

_RESULT_LIMIT = 5

# Spec §7 copy. Kept verbatim — these strings are what the specialist reads.
NOT_CONFIGURED_MESSAGE = "Firecrawl is not configured"
TIMEOUT_MESSAGE = "Search timed out"
NO_PRICED_PAGES_MESSAGE = "No priced product pages found — try editing the query"


def extract_results(service: str, response_dict: dict, brand: str | None = None) -> list[dict]:
    extractor = _EXTRACTORS.get(service)
    if extractor is None:
        return []
    return extractor(response_dict, brand)


# ---------------------------------------------------------------------------
# Price parsing
# ---------------------------------------------------------------------------


def _parse_price_cents(price_obj: object) -> int | None:
    """Extract integer cents from SerpAPI's {"extracted_value": 49.99} or a bare number."""
    if isinstance(price_obj, dict):
        extracted = price_obj.get("extracted_value")
    else:
        extracted = price_obj
    if extracted is None:
        return None
    if isinstance(extracted, bool) or not isinstance(extracted, (int, float)):
        return None
    try:
        cents = round(float(extracted) * 100)
    except (TypeError, ValueError):
        return None
    return cents if cents > 0 else None


def _hostname(url: str) -> str | None:
    try:
        return urlparse(url).hostname or None
    except ValueError:
        return None


def _match_type(title: str | None, brand: str | None) -> str:
    """`exact` only when a known brand actually appears in the product title."""
    if brand and title and brand.strip().lower() in title.lower():
        return "exact"
    return "nearest_comparable"


# ---------------------------------------------------------------------------
# Per-service extractors
# ---------------------------------------------------------------------------


def _extract_google_lens(response_dict: dict, brand: str | None = None) -> list[dict]:
    raw = response_dict.get("visual_matches", [])
    matches = [m for m in raw if isinstance(m, dict)][:_RESULT_LIMIT]
    return [
        {
            "title": m.get("title"),
            "source": m.get("source"),
            "link": m.get("link"),
            "thumbnail": m.get("thumbnail"),
            "source_icon": m.get("source_icon"),
            "price_cents": _parse_price_cents(m.get("price")),
            # A visual match is a resemblance, never a confirmed exact product.
            "match_type": "nearest_comparable",
        }
        for m in matches
    ]


def _extract_firecrawl(response_dict: dict, brand: str | None = None) -> list[dict]:
    """Normalize /v2/search results, dropping anything without a usable USD price.

    A blocked or non-product page yields nothing rather than a guessed price —
    an unsourced number cannot satisfy the audit-trail rule.
    """
    data = response_dict.get("data")
    if not isinstance(data, dict):
        return []

    # A present-but-null "web" key is not the same as a missing one, and the
    # SerpSearch row is already committed by the time we parse it — a TypeError
    # here would make the item permanently unopenable.
    web = data.get("web")
    if not isinstance(web, list):
        return []

    results: list[dict] = []
    for hit in web:
        if not isinstance(hit, dict):
            continue
        extracted = hit.get("json")
        if not isinstance(extracted, dict):
            continue
        if extracted.get("is_product_page") is False:
            continue

        currency = extracted.get("currency")
        if isinstance(currency, str) and currency.strip().upper() not in ("", "USD"):
            continue

        price_cents = _parse_price_cents(extracted.get("price"))
        if price_cents is None:
            continue

        # Rule 2: a price with no source URL is an invalid audit trail, so the
        # whole hit is dropped rather than offered as an appliable price.
        link = hit.get("url")
        if not isinstance(link, str) or not link.strip():
            continue
        link = link.strip()

        title = extracted.get("product_title") or hit.get("title")
        results.append(
            {
                "title": title,
                "source": extracted.get("retailer") or _hostname(link),
                "link": link,
                "thumbnail": None,
                "source_icon": None,
                "price_cents": price_cents,
                "match_type": _match_type(title, brand),
            }
        )
        if len(results) >= _RESULT_LIMIT:
            break
    return results


# ---------------------------------------------------------------------------
# Failure surfacing (spec §7)
# ---------------------------------------------------------------------------


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else ""


def serp_error_message(service: str, response_json: str | None, status_code: int | None) -> str:
    """Human-readable failure text for a stored search row, or "" when it succeeded.

    Takes the persisted column values rather than the ORM row so the display
    layer stays free of model imports and stays trivially unit-testable.
    """
    if service != "firecrawl":
        return ""
    try:
        payload = json.loads(response_json) if response_json else {}
    except ValueError:
        return ""
    if not isinstance(payload, dict):
        return ""

    error = _text(payload.get("error"))
    warning = _text(payload.get("warning"))
    if error:
        if "timed out" in error.lower():
            return TIMEOUT_MESSAGE
        if "not configured" in error.lower():
            return NOT_CONFIGURED_MESSAGE
        return error
    if status_code is not None and not 200 <= status_code < 300:
        suffix = f": {warning}" if warning else ""
        return f"Search failed (HTTP {status_code}){suffix}"
    if payload.get("success") is False:
        return warning or "Search failed"
    return warning


# Dispatch table — add new services here as they are implemented
_EXTRACTORS: dict[str, Callable[[dict, str | None], list[dict]]] = {
    "google_lens": _extract_google_lens,
    "firecrawl": _extract_firecrawl,
}
