"""Firecrawl web search with schema-guided price extraction.

One POST to /v2/search both searches and scrapes each result page, so a
specialist's click maps to exactly one HTTP call. The async /v2/extract
endpoint is deliberately unused — it polls, which a synchronous HTMX
request cannot do.
"""

import logging
import re

from cvp.models import Item

logger = logging.getLogger(__name__)

FIRECRAWL_SEARCH_URL = "https://api.firecrawl.dev/v2/search"

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
