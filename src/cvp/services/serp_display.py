"""Per-service result extractors for SerpAPI responses.

Public API
----------
extract_results(service, response_dict) -> list[dict]
    Returns up to 5 normalized result dicts for the given service.
    Returns [] for unmapped services or empty responses.

Each result dict has these keys (all values may be None unless noted):
    title       : str | None
    source      : str | None
    link        : str | None
    thumbnail   : str | None
    source_icon : str | None
    price_cents : int | None   — extracted price in integer cents, or None
"""

from collections.abc import Callable

_RESULT_LIMIT = 5


def extract_results(service: str, response_dict: dict) -> list[dict]:
    extractor = _EXTRACTORS.get(service)
    if extractor is None:
        return []
    return extractor(response_dict)


# ---------------------------------------------------------------------------
# Price parsing
# ---------------------------------------------------------------------------


def _parse_price_cents(price_obj: object) -> int | None:
    """Extract integer cents from a SerpAPI price object like {"extracted_value": 49.99}."""
    if not isinstance(price_obj, dict):
        return None
    extracted = price_obj.get("extracted_value")
    if extracted is None:
        return None
    try:
        return round(float(extracted) * 100)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Per-service extractors
# ---------------------------------------------------------------------------


def _extract_google_lens(response_dict: dict) -> list[dict]:
    matches = response_dict.get("visual_matches", [])[:_RESULT_LIMIT]
    return [
        {
            "title": m.get("title"),
            "source": m.get("source"),
            "link": m.get("link"),
            "thumbnail": m.get("thumbnail"),
            "source_icon": m.get("source_icon"),
            "price_cents": _parse_price_cents(m.get("price")),
        }
        for m in matches
    ]


# Dispatch table — add new services here as they are implemented
_EXTRACTORS: dict[str, Callable[[dict], list[dict]]] = {
    "google_lens": _extract_google_lens,
}
