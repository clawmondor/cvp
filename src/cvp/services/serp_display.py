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

from collections.abc import Callable
from urllib.parse import urlparse

_RESULT_LIMIT = 5


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

    results: list[dict] = []
    for hit in data.get("web", []):
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

        link = hit.get("url") or ""
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


# Dispatch table — add new services here as they are implemented
_EXTRACTORS: dict[str, Callable[[dict, str | None], list[dict]]] = {
    "google_lens": _extract_google_lens,
    "firecrawl": _extract_firecrawl,
}
