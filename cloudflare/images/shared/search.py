"""Find one purchasable retail match for an item.

One OpenRouter call with the web-search plugin does search and reasoning
together. Measured on 2026-09-10: ~$0.0098 per call at five results, of which
only ~$0.0028 is inference — search dominates, so result count matters far more
than model choice.

Blocked retailer pages are meant to escalate to a Cloudflare Browser Run Quick
Action rather than shipping a browser in this image — but that escalation is
Phase 2 and is NOT wired up yet: `fetch_blocked_page()` below has no caller and
`browser_run_used` is always False. The credentials are plumbed through so
enabling it is a code change, not a redeploy.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

import httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
# COUPLED with `sleepAfter` on CustomPythonAgent in cloudflare/src/index.ts.
# The container has no port, so nothing refreshes its inactivity timer: this
# timeout must stay comfortably under `sleepAfter` or a slow search gets the
# instance reclaimed mid-run. Raise one, raise the other.
_TIMEOUT_SECONDS = 120.0
_MAX_RESULTS = 5

PROMPT = (
    "You are pricing an item for a first-party property insurance claim. "
    "Find ONE currently-purchasable retail match for: {query}. "
    "Reply with ONLY a JSON object with keys: product_title, price_usd, "
    "retailer, source_url, match_type (exact or brand), rationale. "
    "source_url must be the real product page you found. "
    "If you cannot find a match, reply exactly: no match found"
)


@dataclass
class SearchResult:
    product_title: str
    #: As the model reported it, minus currency formatting — never coerced to
    #: float. `dollars_to_cents` takes it from here through Decimal.
    price_usd: str | float
    retailer: str
    source_url: str
    match_type: str
    rationale: str


#: Everything that is not a digit, a decimal point, or a leading minus.
_PRICE_JUNK = re.compile(r"[^0-9.\-]")


def clean_price(value: Any) -> str | int | float | None:
    """Normalise a model-supplied price, or return None if it is not a price.

    A model replying `"price_usd": "$1,299.99"` is ordinary output, and
    `float(price)` raised ValueError on it — wasting a paid search and showing
    the specialist a Python traceback. Numbers pass through untouched; strings
    lose their currency symbols and thousands separators and stay strings, so
    `dollars_to_cents` hands Decimal the exact digits the model wrote.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    if not isinstance(value, str):
        return None
    stripped = _PRICE_JUNK.sub("", value.strip())
    if not stripped:
        return None
    try:
        Decimal(stripped)
    except InvalidOperation:
        # A range ("$100-$200"), a stray word, anything not a single amount.
        return None
    return stripped


def dollars_to_cents(amount: str | int | float | Decimal) -> int:
    """Convert dollars to integer cents, half-up. Currency is never a float."""
    cents = (Decimal(str(amount)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(cents)


def usd_to_micro(amount: float) -> int:
    """Convert a USD cost to integer micro-USD (see spec 5.1)."""
    return int((Decimal(str(amount)) * 1_000_000).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def build_query(description: str, brand: str | None, model: str | None) -> str:
    parts = [brand, model, description]
    cleaned = [re.sub(r"\s+", " ", p).strip() for p in parts if p and p.strip()]
    return " ".join(cleaned)


def _post_openrouter(url: str, headers: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
    """Split out so tests can substitute a payload without a network call."""
    with httpx.Client(timeout=_TIMEOUT_SECONDS) as client:
        response = client.post(url, headers=headers, json=body)
    response.raise_for_status()
    return response.json()


def _extract_json(text: str) -> dict[str, Any] | None:
    """Pull a JSON object out of a reply that may be fenced or prose-wrapped."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    raw = fenced.group(1) if fenced else None
    if raw is None:
        bare = re.search(r"\{.*\}", text, re.DOTALL)
        raw = bare.group(0) if bare else None
    if raw is None:
        return None
    try:
        parsed = json.loads(raw)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def search_for_item(
    *,
    description: str,
    brand: str | None,
    model: str | None,
    model_slug: str,
    openrouter_key: str,
    browser_account_id: str,
    browser_token: str,
) -> tuple[SearchResult | None, int, bool]:
    """Return (result, cost_micro_usd, browser_run_used).

    A result missing a usable source_url or price is discarded: every RCV must
    carry a source, so an unsourced match is not a match.
    """
    query = build_query(description, brand, model)
    body = {
        "model": model_slug,
        "max_tokens": 1200,
        "plugins": [{"id": "web", "max_results": _MAX_RESULTS}],
        "usage": {"include": True},
        "messages": [{"role": "user", "content": PROMPT.format(query=query)}],
    }
    headers = {
        "Authorization": f"Bearer {openrouter_key}",
        "Content-Type": "application/json",
    }

    data = _post_openrouter(OPENROUTER_URL, headers, body)
    cost_micro = usd_to_micro((data.get("usage") or {}).get("cost") or 0)

    choices = data.get("choices") or []
    content = choices[0].get("message", {}).get("content", "") if choices else ""

    parsed = _extract_json(content)
    if not parsed:
        return None, cost_micro, False

    source_url = str(parsed.get("source_url") or "").strip()
    retailer = str(parsed.get("retailer") or "").strip()
    price = clean_price(parsed.get("price_usd"))
    if not source_url or not retailer or price is None:
        return None, cost_micro, False

    match_type = str(parsed.get("match_type") or "exact").strip().lower()
    if match_type not in ("exact", "brand"):
        match_type = "brand"

    return (
        SearchResult(
            product_title=str(parsed.get("product_title") or "").strip(),
            price_usd=price,
            retailer=retailer,
            source_url=source_url,
            match_type=match_type,
            rationale=str(parsed.get("rationale") or "").strip(),
        ),
        cost_micro,
        False,
    )


def fetch_blocked_page(account_id: str, token: str, url: str) -> str:
    """Fetch a bot-blocked page as markdown via a Browser Run Quick Action.

    Quick Actions are plain REST — no Puppeteer session and no Workers binding,
    which is why this image ships no browser. Paid-plan limit is 30 req/s.
    """
    endpoint = (
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}/browser-rendering/markdown"
    )
    with httpx.Client(timeout=_TIMEOUT_SECONDS) as client:
        response = client.post(
            endpoint,
            headers={"Authorization": f"Bearer {token}"},
            json={"url": url},
        )
    response.raise_for_status()
    return (response.json() or {}).get("result", "")
