# Firecrawl Price Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Web search" tab beside "Google Lens" in the crop panel that text-searches the web via Firecrawl, extracts confirmed retail prices from the result pages, and lets a specialist apply one to the item.

**Architecture:** One synchronous `POST https://api.firecrawl.dev/v2/search` call performs search *and* schema-guided price extraction together. Results normalize to the exact dict shape `_extract_google_lens` already emits, so the existing `_serp_result.html` template and `serp_apply` endpoint consume them unchanged. Persistence reuses the `serp_searches` table with `service="firecrawl"` — no migration.

**Tech Stack:** Python 3.11+, FastAPI, Jinja2, HTMX, SQLAlchemy 2.x, `httpx` (already a dependency), pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-09-09-firecrawl-price-search-design.md`

## Global Constraints

- **Currency is always integer cents.** Never store or compute currency as a `float`. Conversion happens only in `_parse_price_cents`.
- **No new dependencies.** `httpx` is already in `pyproject.toml`. Do not add `firecrawl-py` or any SDK.
- **No inline JavaScript event handlers** (`onclick=`, `onchange=`, `hx-on::…`) in new markup — CSP `script-src` has no `unsafe-inline`. Wire interactivity via `data-*` attributes and delegated listeners in `src/cvp/static/app.js`.
- **Type hints everywhere**, modern syntax (`list[str]`, `X | None`).
- **Line length 100.** Run `uv run ruff format .` then verify `uv run ruff format --check .` reports zero files before every commit.
- **Router files stay under 200 lines.** `src/cvp/routers/serp.py` is currently 208 and must end this work *below* 200.
- **The API key must never appear** in `SerpSearch.request_params`, which is persisted and rendered to admins in the "Show raw response" block.
- **`match_type` valid values are `exact` / `nearest_comparable` / `category_average`** only (`docs/data-model.md:126`).
- Run the full suite with `uv run pytest` before each commit.

---

### Task 1: Probe the live Firecrawl API

The spec's §4 mapping depends on one undocumented detail: whether per-result extracted output lands at `data.web[i].json`. Confirm it before writing code against it. **This task produces knowledge, not committed code.**

**Files:**
- Create (throwaway, do not commit): `/private/tmp/claude-501/-Users-cmondor-consulting-tor/95a0d71a-1908-401c-ac80-3a9c6d0a8b37/scratchpad/probe_firecrawl.py`

**Interfaces:**
- Consumes: `FIRECRAWL_API_KEY` from the repo `.env`
- Produces: the confirmed JSON path to per-result extracted fields, used by Task 5

- [ ] **Step 1: Write the probe script**

```python
"""Throwaway probe — confirms where /v2/search puts per-result extracted JSON."""

import json
import os
import pathlib

import httpx

env = pathlib.Path(__file__).resolve().parents[0]
for line in (pathlib.Path("/Users/cmondor/consulting/tor/.env")).read_text().splitlines():
    if line.startswith("FIRECRAWL_API_KEY="):
        os.environ["FIRECRAWL_API_KEY"] = line.split("=", 1)[1].strip()

body = {
    "query": "Stickley oak dining chair",
    "limit": 2,
    "sources": [{"type": "web"}],
    "country": "US",
    "scrapeOptions": {
        "onlyMainContent": True,
        "formats": [
            {
                "type": "json",
                "schema": {
                    "type": "object",
                    "properties": {
                        "product_title": {"type": "string"},
                        "price": {"type": "number"},
                        "currency": {"type": "string"},
                        "retailer": {"type": "string"},
                        "in_stock": {"type": "boolean"},
                        "is_product_page": {"type": "boolean"},
                    },
                },
            }
        ],
    },
}

resp = httpx.post(
    "https://api.firecrawl.dev/v2/search",
    json=body,
    headers={"Authorization": f"Bearer {os.environ['FIRECRAWL_API_KEY']}"},
    timeout=120,
)
print("HTTP", resp.status_code)
data = resp.json()
print("top-level keys:", list(data.keys()))
print("creditsUsed:", data.get("creditsUsed"))
web = data.get("data", {}).get("web", [])
print("web result count:", len(web))
if web:
    print("per-result keys:", list(web[0].keys()))
    print(json.dumps(web[0], indent=2)[:3000])
```

- [ ] **Step 2: Run the probe**

```bash
source ~/.venvs/shared/bin/activate && python /private/tmp/claude-501/-Users-cmondor-consulting-tor/95a0d71a-1908-401c-ac80-3a9c6d0a8b37/scratchpad/probe_firecrawl.py
```

- [ ] **Step 3: Record the answer**

Write down, for use in Task 5:
1. The exact key holding extracted fields on each web result (expected `json`).
2. Whether `creditsUsed` reflects ~1 credit per scraped page.
3. Whether results lacking extraction omit the key or set it to `null`.

**If the key is not `json`**, update `docs/superpowers/specs/2026-09-09-firecrawl-price-search-design.md` §4 with the real path and commit that doc fix before continuing. Task 5's `_extract_firecrawl` must read the confirmed key.

- [ ] **Step 4: Delete the probe**

```bash
rm /private/tmp/claude-501/-Users-cmondor-consulting-tor/95a0d71a-1908-401c-ac80-3a9c6d0a8b37/scratchpad/probe_firecrawl.py
```

---

### Task 2: Wire `FIRECRAWL_API_KEY` into settings

**Files:**
- Modify: `src/cvp/config.py:23` (beside `serp_api_key`)
- Modify: `.env.example`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `settings.firecrawl_api_key: str` (defaults to `""`), consumed by Task 4

- [ ] **Step 1: Write the failing test**

Append to `tests/test_config.py`:

```python
def test_firecrawl_api_key_defaults_to_empty():
    from cvp.config import Settings

    s = Settings(_env_file=None)
    assert s.firecrawl_api_key == ""


def test_firecrawl_api_key_reads_env(monkeypatch):
    from cvp.config import Settings

    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-test-123")
    s = Settings(_env_file=None)
    assert s.firecrawl_api_key == "fc-test-123"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_config.py -k firecrawl -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'firecrawl_api_key'`

- [ ] **Step 3: Add the setting**

In `src/cvp/config.py`, immediately after the `serp_api_key` line:

```python
    firecrawl_api_key: str = ""
```

- [ ] **Step 4: Add it to `.env.example`**

Append after the SerpAPI block:

```
# ── Firecrawl — web product search and price extraction ──────────────────────
FIRECRAWL_API_KEY=
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 6: Format and commit**

```bash
uv run ruff format . && uv run ruff format --check .
git add src/cvp/config.py .env.example tests/test_config.py
git commit -m "feat(config): add FIRECRAWL_API_KEY setting"
```

---

### Task 3: `build_query` — turn an item into a search string

**Files:**
- Create: `src/cvp/services/firecrawl.py`
- Test: `tests/test_firecrawl_service.py`

**Interfaces:**
- Produces: `build_query(item: Item) -> str`, consumed by Task 6

- [ ] **Step 1: Write the failing tests**

Create `tests/test_firecrawl_service.py`:

```python
"""Unit tests for the Firecrawl service."""

from cvp.models import Item
from cvp.services.firecrawl import build_query


def _item(**kw) -> Item:
    defaults = {"description": "", "brand": None, "model": None}
    defaults.update(kw)
    return Item(**defaults)


def test_build_query_joins_brand_model_description():
    item = _item(brand="Stickley", model="A-12", description="oak dining chair")
    assert build_query(item) == "Stickley A-12 oak dining chair"


def test_build_query_skips_missing_brand_and_model():
    item = _item(description="oak dining chair")
    assert build_query(item) == "oak dining chair"


def test_build_query_skips_blank_strings():
    item = _item(brand="   ", model="", description="lamp")
    assert build_query(item) == "lamp"


def test_build_query_collapses_internal_whitespace():
    item = _item(brand="West  Elm", description="floor\tlamp\n")
    assert build_query(item) == "West Elm floor lamp"


def test_build_query_all_empty_returns_empty_string():
    assert build_query(_item()) == ""
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_firecrawl_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cvp.services.firecrawl'`

- [ ] **Step 3: Write the minimal implementation**

Create `src/cvp/services/firecrawl.py`:

```python
"""Firecrawl web search with schema-guided price extraction.

One POST to /v2/search both searches and scrapes each result page, so a
specialist's click maps to exactly one HTTP call. The async /v2/extract
endpoint is deliberately unused — it polls, which a synchronous HTMX
request cannot do.
"""

import logging
import re
from typing import Any

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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_firecrawl_service.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Format and commit**

```bash
uv run ruff format . && uv run ruff format --check .
git add src/cvp/services/firecrawl.py tests/test_firecrawl_service.py
git commit -m "feat(firecrawl): add build_query"
```

---

### Task 4: `call_firecrawl` — the HTTP call

Mirrors `call_serp`'s contract exactly: returns a 4-tuple, never raises into the router.

**Files:**
- Modify: `src/cvp/services/firecrawl.py`
- Test: `tests/test_firecrawl_service.py`

**Interfaces:**
- Consumes: `settings.firecrawl_api_key` (Task 2)
- Produces: `call_firecrawl(query: str) -> tuple[str, dict, dict, int]` returning `(request_url, safe_body, response_dict, status_code)`; and `PRICE_SCHEMA: dict[str, Any]`. Consumed by Task 6.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_firecrawl_service.py`:

```python
from unittest.mock import patch

import httpx
import pytest

from cvp.services.firecrawl import FIRECRAWL_SEARCH_URL, call_firecrawl


class _Resp:
    def __init__(self, status_code=200, payload=None, text="", ct="application/json"):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text
        self.headers = {"content-type": ct}

    def json(self):
        return self._payload


@pytest.fixture
def _key(monkeypatch):
    monkeypatch.setattr("cvp.config.settings.firecrawl_api_key", "fc-secret-abc123")


def test_call_firecrawl_unconfigured_key_returns_error(monkeypatch):
    monkeypatch.setattr("cvp.config.settings.firecrawl_api_key", "")
    url, body, data, status = call_firecrawl("lamp")
    assert status == 0
    assert "not configured" in data["error"]
    assert url == FIRECRAWL_SEARCH_URL


def test_call_firecrawl_success_returns_payload(_key):
    payload = {"success": True, "data": {"web": []}, "creditsUsed": 3}
    with patch("httpx.Client.post", return_value=_Resp(200, payload)):
        url, body, data, status = call_firecrawl("oak chair")
    assert status == 200
    assert data == payload
    assert body["query"] == "oak chair"
    assert body["limit"] == 5
    assert body["scrapeOptions"]["formats"][0]["type"] == "json"


def test_call_firecrawl_never_leaks_the_api_key(_key):
    """The returned body is persisted to SerpSearch.request_params and shown to admins."""
    payload = {"success": True, "data": {"web": []}}
    with patch("httpx.Client.post", return_value=_Resp(200, payload)):
        _url, body, _data, _status = call_firecrawl("oak chair")
    assert "fc-secret-abc123" not in str(body)
    assert "Authorization" not in str(body)


def test_call_firecrawl_timeout_returns_error(_key):
    with patch("httpx.Client.post", side_effect=httpx.TimeoutException("boom")):
        _url, _body, data, status = call_firecrawl("lamp")
    assert status == 0
    assert "timed out" in data["error"]


def test_call_firecrawl_non_json_body_is_wrapped(_key):
    with patch("httpx.Client.post", return_value=_Resp(502, text="Bad Gateway", ct="text/html")):
        _url, _body, data, status = call_firecrawl("lamp")
    assert status == 502
    assert data == {"raw": "Bad Gateway"}


def test_call_firecrawl_unexpected_error_returns_error(_key):
    with patch("httpx.Client.post", side_effect=RuntimeError("kaboom")):
        _url, _body, data, status = call_firecrawl("lamp")
    assert status == 0
    assert "kaboom" in data["error"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_firecrawl_service.py -k call_firecrawl -v`
Expected: FAIL — `ImportError: cannot import name 'call_firecrawl'`

- [ ] **Step 3: Write the implementation**

Add to `src/cvp/services/firecrawl.py` — note `httpx` and `settings` imports go at the top with the existing ones:

```python
import httpx

from cvp.config import settings

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
        status_code = response.status_code
        ct = response.headers.get("content-type", "")
        response_data = response.json() if "json" in ct else {"raw": response.text}
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

    logger.debug(
        "Firecrawl response | query=%s status=%d credits=%s",
        query,
        status_code,
        response_data.get("creditsUsed") if isinstance(response_data, dict) else None,
    )
    return FIRECRAWL_SEARCH_URL, body, response_data, status_code
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_firecrawl_service.py -v`
Expected: PASS (11 tests)

- [ ] **Step 5: Format and commit**

```bash
uv run ruff format . && uv run ruff format --check .
git add src/cvp/services/firecrawl.py tests/test_firecrawl_service.py
git commit -m "feat(firecrawl): add call_firecrawl with header auth and no key leakage"
```

---

### Task 5: Normalize results — `_extract_firecrawl` and honest `match_type`

Two changes to `serp_display.py`: generalize `_parse_price_cents` to accept a bare number, and add the Firecrawl extractor. Both extractors gain a `match_type` field so Task 7 can stop hardcoding it.

**Files:**
- Modify: `src/cvp/services/serp_display.py`
- Test: `tests/test_serp_display.py`

**Interfaces:**
- Consumes: the confirmed extracted-fields key from Task 1 (assumed `json` below — **substitute the real key if Task 1 found otherwise**)
- Produces: `extract_results(service: str, response_dict: dict, brand: str | None = None) -> list[dict]`, where each dict has `title`, `source`, `link`, `thumbnail`, `source_icon`, `price_cents`, `match_type`. Consumed by Tasks 6 and 7.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_serp_display.py`:

```python
from cvp.services.serp_display import extract_results


def _fc(results):
    return {"success": True, "data": {"web": results}}


def _hit(url="https://shop.example/p/1", title="Result", **extracted):
    payload = {
        "product_title": "Oak Dining Chair",
        "price": 129.99,
        "currency": "USD",
        "retailer": "Shop Example",
        "is_product_page": True,
    }
    payload.update(extracted)
    return {"url": url, "title": title, "json": payload}


def test_extract_firecrawl_maps_fields():
    [r] = extract_results("firecrawl", _fc([_hit()]))
    assert r["title"] == "Oak Dining Chair"
    assert r["source"] == "Shop Example"
    assert r["link"] == "https://shop.example/p/1"
    assert r["price_cents"] == 12999
    assert r["thumbnail"] is None
    assert r["source_icon"] is None


def test_extract_firecrawl_falls_back_to_result_title_and_hostname():
    hit = _hit(product_title=None, retailer=None)
    [r] = extract_results("firecrawl", _fc([hit]))
    assert r["title"] == "Result"
    assert r["source"] == "shop.example"


def test_extract_firecrawl_drops_non_product_pages():
    assert extract_results("firecrawl", _fc([_hit(is_product_page=False)])) == []


def test_extract_firecrawl_drops_non_usd():
    assert extract_results("firecrawl", _fc([_hit(currency="GBP")])) == []


def test_extract_firecrawl_keeps_missing_currency():
    [r] = extract_results("firecrawl", _fc([_hit(currency=None)]))
    assert r["price_cents"] == 12999


def test_extract_firecrawl_drops_missing_price():
    assert extract_results("firecrawl", _fc([_hit(price=None)])) == []


def test_extract_firecrawl_drops_zero_price():
    assert extract_results("firecrawl", _fc([_hit(price=0)])) == []


def test_extract_firecrawl_drops_results_without_extraction():
    assert extract_results("firecrawl", _fc([{"url": "https://x.example", "title": "X"}])) == []


def test_extract_firecrawl_caps_at_5():
    assert len(extract_results("firecrawl", _fc([_hit() for _ in range(9)]))) == 5


def test_extract_firecrawl_empty_response():
    assert extract_results("firecrawl", {}) == []


def test_extract_firecrawl_match_type_exact_when_brand_in_title():
    [r] = extract_results(
        "firecrawl", _fc([_hit(product_title="Stickley Oak Chair")]), brand="Stickley"
    )
    assert r["match_type"] == "exact"


def test_extract_firecrawl_match_type_nearest_when_brand_absent():
    [r] = extract_results("firecrawl", _fc([_hit()]), brand="Stickley")
    assert r["match_type"] == "nearest_comparable"


def test_extract_firecrawl_match_type_nearest_when_no_brand_known():
    [r] = extract_results("firecrawl", _fc([_hit()]))
    assert r["match_type"] == "nearest_comparable"


def test_extract_google_lens_match_type_is_nearest_comparable():
    """A visual match is a resemblance, not a confirmed exact product."""
    resp = {"visual_matches": [{"title": "Chair", "link": "https://x.example"}]}
    [r] = extract_results("google_lens", resp)
    assert r["match_type"] == "nearest_comparable"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_serp_display.py -v`
Expected: FAIL — the `firecrawl` service is unmapped so `extract_results` returns `[]`, and `match_type` is absent from Lens results.

- [ ] **Step 3: Write the implementation**

In `src/cvp/services/serp_display.py`:

Add `from urllib.parse import urlparse` to the imports, then generalize the price parser:

```python
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
```

Add the hostname helper and the Firecrawl extractor:

```python
def _hostname(url: str) -> str | None:
    try:
        return urlparse(url).hostname or None
    except ValueError:
        return None


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


def _match_type(title: str | None, brand: str | None) -> str:
    """`exact` only when a known brand actually appears in the product title."""
    if brand and title and brand.strip().lower() in title.lower():
        return "exact"
    return "nearest_comparable"
```

Update `_extract_google_lens` to accept the new argument and emit `match_type`:

```python
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
```

Update the dispatcher and table:

```python
def extract_results(service: str, response_dict: dict, brand: str | None = None) -> list[dict]:
    extractor = _EXTRACTORS.get(service)
    if extractor is None:
        return []
    return extractor(response_dict, brand)


_EXTRACTORS: dict[str, Callable[[dict, str | None], list[dict]]] = {
    "google_lens": _extract_google_lens,
    "firecrawl": _extract_firecrawl,
}
```

Finally, update the module docstring's `extract_results` signature line and add `match_type` to its documented key list.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_serp_display.py -v`
Expected: PASS — including all pre-existing `google_lens` tests.

- [ ] **Step 5: Format and commit**

```bash
uv run ruff format . && uv run ruff format --check .
git add src/cvp/services/serp_display.py tests/test_serp_display.py
git commit -m "feat(serp): add firecrawl extractor and honest match_type"
```

---

### Task 6: Router — shared helper, then the Firecrawl endpoint

`routers/serp.py` is 208 lines, over the 200-line ceiling. Factor the duplicated *run → persist → render → audit* body out first, then add the new endpoint into the space that frees.

**Files:**
- Modify: `src/cvp/routers/serp.py`
- Test: `tests/test_serp_router.py` (create)

**Interfaces:**
- Consumes: `build_query`, `call_firecrawl` (Tasks 3–4); `extract_results` (Task 5)
- Produces: `POST /api/items/{item_id}/crops/{crop_id}/serp/firecrawl`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_serp_router.py`. This mirrors the fixture style of `tests/test_crops_router.py`:

```python
"""Integration tests for the SERP router's Firecrawl endpoint."""

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import cvp.dependencies as deps
from cvp.db import get_db
from cvp.dependencies import CurrentUser, require_active_user
from cvp.models import Base, Category, EvidenceFile, Item, ItemCrop, Matter, SerpSearch


@pytest.fixture(scope="module")
def db_engine(tmp_path_factory):
    base = tmp_path_factory.mktemp("serp_router")
    engine = create_engine(f"sqlite:///{base}/test.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    db.add(Category(id=1, name="Furniture", useful_life_years=10, acv_floor_pct=0.20))
    db.add(Matter(id="m1", policyholder_name="Test"))
    db.add(
        EvidenceFile(
            id="ef1", matter_id="m1", filename="p.jpg",
            stored_path="ef1/p.jpg", kind="image", scanned=True,
        )
    )
    db.add(
        Item(
            id="item1", matter_id="m1", category_id=1, line_number=1,
            description="oak dining chair", brand="Stickley",
        )
    )
    db.add(Item(id="item2", matter_id="m1", category_id=1, line_number=2, description="lamp"))
    db.add(
        ItemCrop(
            id="crop1", item_id="item1", evidence_file_id="ef1",
            bbox_left=0, bbox_upper=0, bbox_right=10, bbox_lower=10,
            crop_path="ef1/crop1.jpg",
        )
    )
    db.commit()
    db.close()
    return engine


@pytest.fixture(scope="module")
def client(db_engine):
    import cvp.routers.serp as serp_mod

    Session = sessionmaker(bind=db_engine)
    app = FastAPI()
    app.include_router(serp_mod.router)

    async def mock_user() -> CurrentUser:
        return CurrentUser(
            id="test-user", email="t@t.com", system_role="system_admin",
            group_id="g1", group_kind="internal",
        )

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[require_active_user] = mock_user
    app.dependency_overrides[get_db] = override_get_db

    with (
        patch.object(serp_mod, "SessionLocal", Session),
        patch.object(deps, "_check_matter_access", return_value=True),
    ):
        with TestClient(app) as c:
            yield c, Session


_PAYLOAD = {
    "success": True,
    "creditsUsed": 5,
    "data": {
        "web": [
            {
                "url": "https://shop.example/p/1",
                "title": "Result",
                "json": {
                    "product_title": "Stickley Oak Dining Chair",
                    "price": 129.99,
                    "currency": "USD",
                    "retailer": "Shop Example",
                    "is_product_page": True,
                },
            }
        ]
    },
}


def test_firecrawl_search_renders_results_and_persists(client):
    c, Session = client
    with patch(
        "cvp.routers.serp.call_firecrawl",
        return_value=("https://api.firecrawl.dev/v2/search", {"query": "q"}, _PAYLOAD, 200),
    ):
        resp = c.post("/api/items/item1/crops/crop1/serp/firecrawl", data={"query": "Stickley oak chair"})

    assert resp.status_code == 200
    assert "Stickley Oak Dining Chair" in resp.text
    assert "129.99" in resp.text

    db = Session()
    row = db.query(SerpSearch).filter_by(service="firecrawl").one()
    assert row.item_crop_id == "crop1"
    assert row.status_code == 200
    db.close()


def test_firecrawl_search_rejects_crop_from_another_item(client):
    c, _ = client
    with patch("cvp.routers.serp.call_firecrawl", return_value=("u", {}, _PAYLOAD, 200)):
        resp = c.post("/api/items/item2/crops/crop1/serp/firecrawl", data={"query": "lamp"})
    assert resp.status_code == 403


def test_firecrawl_search_404s_on_unknown_crop(client):
    c, _ = client
    with patch("cvp.routers.serp.call_firecrawl", return_value=("u", {}, _PAYLOAD, 200)):
        resp = c.post("/api/items/item1/crops/nope/serp/firecrawl", data={"query": "x"})
    assert resp.status_code == 404


def test_firecrawl_search_defaults_query_from_item_fields(client):
    c, _ = client
    with patch(
        "cvp.routers.serp.call_firecrawl",
        return_value=("u", {}, _PAYLOAD, 200),
    ) as spy:
        c.post("/api/items/item1/crops/crop1/serp/firecrawl", data={"query": ""})
    spy.assert_called_once_with("Stickley oak dining chair")


def test_firecrawl_search_surfaces_error_without_500(client):
    c, _ = client
    with patch(
        "cvp.routers.serp.call_firecrawl",
        return_value=("u", {}, {"error": "Firecrawl is not configured."}, 0),
    ):
        resp = c.post("/api/items/item1/crops/crop1/serp/firecrawl", data={"query": "x"})
    assert resp.status_code == 200
    assert "No results found." in resp.text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_serp_router.py -v`
Expected: FAIL — 404, the route does not exist.

- [ ] **Step 3: Extract the shared helper**

In `src/cvp/routers/serp.py`, add this above `run_google_lens`:

```python
def _run_and_render(
    request: Request,
    background_tasks: BackgroundTasks,
    user: CurrentUser,
    item_id: str,
    crop_id: str,
    service: str,
    caller: Callable[[ItemCrop, Item | None], tuple[str, dict, dict, int]],
    image_url_fn: Callable[[ItemCrop], str] = lambda _crop: "",
) -> HTMLResponse:
    """Run a search, persist it, render the result partial, and audit.

    `caller` receives the loaded crop and item and returns the shared 4-tuple
    (request_url, params, response_dict, status_code). Both callables run
    inside this function's single session — do not open another.
    """
    db = SessionLocal()
    try:
        crop = db.get(ItemCrop, crop_id)
        if crop is None:
            raise HTTPException(status_code=404, detail="Crop not found")
        if crop.item_id != item_id:
            raise HTTPException(status_code=403, detail="Crop does not belong to this item")

        item = db.get(Item, item_id)
        request_url, params_dict, response_dict, status_code = caller(crop, item)

        search = SerpSearch(
            item_crop_id=crop.id,
            service=service,
            image_url=image_url_fn(crop),
            request_url=request_url,
            request_params=json.dumps(params_dict),
            response_json=json.dumps(response_dict),
            status_code=status_code,
        )
        db.add(search)
        db.commit()
        db.refresh(search)

        brand = item.brand if item else None
        display_results = extract_results(service, response_dict, brand)
        matter_id = item.matter_id if item else None

        html = templates.get_template("_serp_result.html").render(
            s=search, display_results=display_results, item_id=item_id
        )
    finally:
        db.close()

    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="serp.run",
        resource_type="item",
        resource_id=item_id,
        matter_id=matter_id,
        ip_address=get_client_ip(request),
    )
    return HTMLResponse(html)
```

Then rewrite `run_google_lens` to use it:

```python
@router.post("/api/items/{item_id}/crops/{crop_id}/serp/google_lens", response_class=HTMLResponse)
def run_google_lens(
    request: Request,
    item_id: str,
    crop_id: str,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_matter_role("editor")),
    image_url: str = Form(""),
) -> HTMLResponse:
    """Run a Google Lens reverse-image search for one crop and persist the result."""
    pasted = image_url.strip() or None
    return _run_and_render(
        request, background_tasks, user, item_id, crop_id,
        service="google_lens",
        caller=lambda crop, _item: call_serp("google_lens", crop, pasted),
        image_url_fn=lambda crop: pasted or build_crop_url(crop) or "",
    )
```

Add `from collections.abc import Callable` to the imports.

- [ ] **Step 4: Add the Firecrawl endpoint**

```python
@router.post("/api/items/{item_id}/crops/{crop_id}/serp/firecrawl", response_class=HTMLResponse)
def run_firecrawl(
    request: Request,
    item_id: str,
    crop_id: str,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_matter_role("editor")),
    query: str = Form(""),
) -> HTMLResponse:
    """Run a Firecrawl web product search for one item and persist the result.

    An empty query falls back to the item's own fields, so the endpoint is
    usable without the pre-filled input.
    """
    typed = query.strip()
    return _run_and_render(
        request, background_tasks, user, item_id, crop_id,
        service="firecrawl",
        caller=lambda _crop, item: call_firecrawl(typed or (build_query(item) if item else "")),
    )
```

Add the imports at the top of the file:

```python
from cvp.services.firecrawl import build_query, call_firecrawl
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_serp_router.py -v`
Expected: PASS (5 tests)

- [ ] **Step 6: Verify the line-count constraint**

Run: `wc -l src/cvp/routers/serp.py`
Expected: **under 200**. If it is not, move `_run_and_render` into `src/cvp/services/serp_runner.py` and import it — the router must end below the ceiling.

- [ ] **Step 7: Run the full suite, format, and commit**

```bash
uv run pytest && uv run ruff format . && uv run ruff format --check .
git add src/cvp/routers/serp.py tests/test_serp_router.py
git commit -m "feat(serp): add firecrawl endpoint, factor shared search runner"
```

---

### Task 7: Stop hardcoding `match_type` on apply

`serp_apply` stamps every applied result `exact` (`routers/serp.py:162`) regardless of what it is. Carry the extractor's honest value through the form instead.

**Files:**
- Modify: `src/cvp/routers/serp.py` (the `serp_apply` handler)
- Modify: `src/cvp/templates/_serp_result.html`
- Test: `tests/test_serp_router.py`

**Interfaces:**
- Consumes: `match_type` on each normalized result (Task 5)
- Produces: `serp_apply` accepting a `match_type` form field

- [ ] **Step 1: Write the failing test**

Append to `tests/test_serp_router.py`:

```python
def test_serp_apply_honors_submitted_match_type(client):
    c, Session = client
    resp = c.post(
        "/api/items/item1/serp-apply",
        data={
            "source_url": "https://shop.example/p/1",
            "source_retailer": "Shop Example",
            "rcv_unit_cents": "12999",
            "match_type": "nearest_comparable",
        },
    )
    assert resp.status_code == 200

    db = Session()
    item = db.get(Item, "item1")
    assert item.match_type == "nearest_comparable"
    assert item.source_url == "https://shop.example/p/1"
    assert item.source_captured_at is not None
    db.close()


def test_serp_apply_rejects_invalid_match_type(client):
    c, _ = client
    resp = c.post(
        "/api/items/item1/serp-apply",
        data={
            "source_url": "https://shop.example/p/2",
            "source_retailer": "Shop Example",
            "rcv_unit_cents": "100",
            "match_type": "brand",
        },
    )
    assert resp.status_code == 422
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_serp_router.py -k match_type -v`
Expected: FAIL — the item is stamped `exact`, and `brand` is accepted.

- [ ] **Step 3: Add the shared constant**

The valid values currently exist only as a hardcoded list inside a Jinja loop (`_item_row_edit.html:150`). Add a single source of truth in `src/cvp/models.py`, directly above the `Item` class:

```python
MATCH_TYPES: tuple[str, ...] = ("exact", "nearest_comparable", "category_average")
```

- [ ] **Step 4: Use it in `serp_apply`**

Replace the hardcoded assignment in `serp_apply`:

```python
    match_type: str = Form("nearest_comparable"),
```

and, inside the handler, in place of `item.match_type = "exact"`:

```python
        if match_type not in MATCH_TYPES:
            raise HTTPException(status_code=422, detail=f"Invalid match_type: {match_type}")
        item.match_type = match_type
```

Add `MATCH_TYPES` to the existing `from cvp.models import ...` line.

- [ ] **Step 5: Pass it from the template**

In `src/cvp/templates/_serp_result.html`, inside the apply form beside the other hidden inputs:

```html
          <input type="hidden" name="match_type" value="{{ result.match_type or 'nearest_comparable' }}">
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_serp_router.py -v`
Expected: PASS

- [ ] **Step 7: Run the full suite, format, and commit**

```bash
uv run pytest && uv run ruff format . && uv run ruff format --check .
git add src/cvp/models.py src/cvp/routers/serp.py src/cvp/templates/_serp_result.html tests/test_serp_router.py
git commit -m "fix(serp): carry honest match_type through apply instead of hardcoding exact"
```

---

### Task 8: The Web search tab

**Files:**
- Modify: `src/cvp/templates/_serp_panel.html`
- Modify: `src/cvp/static/app.js`
- Test: `tests/test_serp_panel_ui.py` (create)

**Interfaces:**
- Consumes: the endpoint from Task 6
- Produces: no Python interface

- [ ] **Step 1: Write the failing test**

Create `tests/test_serp_panel_ui.py`:

```python
"""The crop panel renders both search tabs with no inline event handlers."""

import re
from pathlib import Path

TPL = Path("src/cvp/templates/_serp_panel.html").read_text()


def test_panel_has_both_search_tabs():
    assert "data-serp-tab-target" in TPL
    assert "Google Lens" in TPL
    assert "Web search" in TPL


def test_panel_posts_to_the_firecrawl_endpoint():
    assert "/serp/firecrawl" in TPL


def test_panel_prefills_an_editable_query_input():
    assert re.search(r'name="query"[^>]*value="\{\{ *default_query', TPL)


def test_panel_has_no_inline_event_handlers():
    """CSP script-src has no unsafe-inline — handlers must be delegated via app.js."""
    for attr in ("onclick=", "onchange=", "onsubmit=", "hx-on:"):
        assert attr not in TPL, f"inline handler {attr} is CSP-blocked"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_serp_panel_ui.py -v`
Expected: FAIL — none of the tab markup exists yet.

- [ ] **Step 3: Pass `default_query` into the panel**

In `src/cvp/routers/serp.py`, in the `serp_panel` handler's `templates.get_template("_serp_panel.html").render(...)` call, add:

```python
            default_query=build_query(item),
```

- [ ] **Step 4: Add the tab strip and the Web search form**

In `src/cvp/templates/_serp_panel.html`, replace the hardcoded heading `Google Lens — {{ item.description }}` with `Product search — {{ item.description }}`. Then, inside the per-crop `<div id="crop-panel-{{ crop.id }}">`, wrap the existing search form in a tab structure:

```html
          {# ── Tab strip ─────────────────────────────────────────────── #}
          <div class="flex gap-1 mb-3 border-b border-violet-200">
            <button data-serp-tab-target="lens-{{ crop.id }}"
                    data-serp-tab-group="{{ crop.id }}"
                    class="serp-tab text-xs px-3 py-1.5 border-b-2 border-violet-500 text-violet-800 font-medium">
              Google Lens
            </button>
            <button data-serp-tab-target="web-{{ crop.id }}"
                    data-serp-tab-group="{{ crop.id }}"
                    class="serp-tab text-xs px-3 py-1.5 border-b-2 border-transparent text-gray-500 hover:text-violet-700">
              Web search
            </button>
          </div>

          {# ── Pane: Google Lens ─────────────────────────────────────── #}
          <div id="serp-pane-lens-{{ crop.id }}" data-serp-pane-group="{{ crop.id }}">
```

Move the file's **existing** Lens markup inside this div verbatim — that is the
`<form hx-post=".../serp/google_lens" ... data-lens-form>` block through its
closing `</form>`, plus the `#lens-result-{{ crop.id }}` container that follows
it. Do not edit that markup; only re-parent it. Then close the div and continue:

```html
          </div>

          {# ── Pane: Web search ──────────────────────────────────────── #}
          <div id="serp-pane-web-{{ crop.id }}" data-serp-pane-group="{{ crop.id }}" class="hidden">
            <form hx-post="/api/items/{{ item.id }}/crops/{{ crop.id }}/serp/firecrawl"
                  hx-target="#firecrawl-result-{{ crop.id }}"
                  hx-swap="innerHTML"
                  hx-indicator="#firecrawl-spinner-{{ crop.id }}"
                  hx-disabled-elt="find button[type='submit']"
                  class="flex items-center gap-2 mb-3">
              <input type="text" name="query" value="{{ default_query }}"
                     placeholder="Search terms"
                     class="flex-1 text-xs border border-gray-300 rounded px-2 py-1.5
                            focus:outline-none focus:ring-1 focus:ring-violet-400" />
              <button type="submit"
                      class="text-xs px-3 py-1.5 rounded transition text-white
                             bg-violet-600 hover:bg-violet-700 whitespace-nowrap">
                Search web
              </button>
              <svg id="firecrawl-spinner-{{ crop.id }}"
                   class="htmx-indicator animate-spin h-4 w-4 text-violet-500"
                   xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z"></path>
              </svg>
            </form>
            <div id="firecrawl-result-{{ crop.id }}"></div>
          </div>
```

Unlike the Lens button, this button is never permanently disabled — editing the query and re-running is the core interaction.

- [ ] **Step 5: Add the delegated tab listener**

Append to `src/cvp/static/app.js`, beside the other delegated listeners (near line 476):

```javascript
// Delegated click: data-serp-tab-target → switch panes within one crop's panel
document.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-serp-tab-target]');
    if (!btn) return;
    var group = btn.dataset.serpTabGroup;

    document.querySelectorAll('[data-serp-pane-group="' + group + '"]').forEach(function (pane) {
        pane.classList.add('hidden');
    });
    var pane = document.getElementById('serp-pane-' + btn.dataset.serpTabTarget);
    if (pane) pane.classList.remove('hidden');

    document.querySelectorAll('[data-serp-tab-group="' + group + '"]').forEach(function (tab) {
        tab.classList.remove('border-violet-500', 'text-violet-800', 'font-medium');
        tab.classList.add('border-transparent', 'text-gray-500');
    });
    btn.classList.remove('border-transparent', 'text-gray-500');
    btn.classList.add('border-violet-500', 'text-violet-800', 'font-medium');
});
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_serp_panel_ui.py -v`
Expected: PASS (4 tests)

- [ ] **Step 7: Verify in the browser**

Start the app, open a matter with a scanned item that has a crop, open the product-search panel, and confirm: both tabs render, switching panes works, the query input arrives pre-filled from the item's fields, a search returns priced results, and **Use this** applies a price with a `nearest_comparable` match type.

- [ ] **Step 8: Run the full suite, format, and commit**

```bash
uv run pytest && uv run ruff format . && uv run ruff format --check .
git add src/cvp/templates/_serp_panel.html src/cvp/static/app.js src/cvp/routers/serp.py tests/test_serp_panel_ui.py
git commit -m "feat(ui): add Web search tab to the crop product-search panel"
```

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| §1 one `/v2/search` call; probe `data.web[i].json` | 1, 4 |
| §2 config, `.env.example`, graceful unset key | 2, 4 |
| §3 `services/firecrawl.py`, 4-tuple contract, header auth, no key leak | 3, 4 |
| §4 `_extract_firecrawl`, drop rules, `_parse_price_cents` reuse | 5 |
| §5 tab strip, editable query, no inline handlers | 8 |
| §6 endpoint, `service="firecrawl"`, no migration | 6 |
| §6.1 router under 200 lines; `match_type` fix + shared constant | 6, 7 |
| §7 error handling without 500s | 4, 6 |
| §8 testing across display, service, router | 3–8 |

**Deferred, per spec:** `AiRecommendation` rows, background/batch runs, shipping extraction, SerpAPI's absence from rule 6, and repointing `skills/MakeAIRecommendations` at Firecrawl (including its invalid `match_type: "brand"` instruction).

**Notes carried into execution:**
- Task 1 gates Task 5. If extracted output is not at `json`, fix the spec and the extractor together.
- `extract_results` gains a third parameter. Task 6's `_run_and_render` is its only in-app caller besides tests.
- Task 7 changes existing behavior: Lens results now apply as `nearest_comparable` rather than `exact`. Intentional — a visual match is a resemblance. Existing rows are untouched.
