# Firecrawl Price Search — Design Spec

**Date:** 2026-09-09
**Status:** Approved design, ready for implementation planning
**Branch context:** `cvp-legacy`

## Summary

Add a **Web search** tab beside **Google Lens** in the existing crop panel. The
specialist clicks it for an item; we build a text query from the item's fields,
send one Firecrawl `/v2/search` call that both searches and extracts structured
prices from the result pages, and render the hits in the same result list Lens
already uses. The specialist clicks **Apply** on the hit they want, which sets
the item's price and its four source fields.

Lens searches by image; this searches by text. They are independent paths over
the same panel, and a specialist picks whichever suits the item.

## Goals

1. Price items that Lens cannot match — unbranded, oddly-shaped, or poorly-cropped
   goods where a reverse-image search returns nothing usable.
2. Return a **confirmed live price** read off the retailer's page, not a price
   guessed from a search snippet.
3. Reuse the Lens result shape end-to-end so the display template and the apply
   endpoint work unchanged.
4. Keep the audit trail whole: every applied price carries `source_url`,
   `source_retailer`, `source_captured_at`, and an honest `match_type`.

## Non-goals

- **No AI Recommendations.** This path applies prices directly to the item,
  matching the Lens tab's behaviour. It does not write `ai_recommendations`
  rows. See "Deferred" below.
- **No background or batch runs.** One search per click, synchronous. No worker
  thread, no job table, no scheduling.
- **No replacement of SerpAPI Lens.** Both tabs stay.
- **No crawling.** We call `/v2/search` only. No `/crawl`, no `/map`, no
  site-wide traversal.

## Immutable-rule compliance

| Rule | How this design satisfies it |
|------|------------------------------|
| 1 — integer cents | Prices convert to cents at exactly one place, the existing `_parse_price_cents` in `serp_display.py`. No float reaches the DB. |
| 2 — every RCV sourced | `serp_apply` already stamps all four fields. This spec additionally fixes `match_type`, which is currently hardcoded (see §6). |
| 3 — ACV computed | `serp_apply` already recomputes ACV via `compute_acv`. Unchanged. |
| 6 — approved services | Firecrawl is added to the rule 6 list in the same PR as this spec. |
| 7 — sequential vision calls | Untouched. This path makes no vision calls. |

## 1. Why one `/v2/search` call, not `/search` + `/extract`

Verified against Firecrawl's live docs on 2026-09-09:

- **`/v2/extract` is asynchronous.** It returns `{"status": "processing"|"completed"|...}`
  and requires polling. That is incompatible with a synchronous HTMX click, which
  must return rendered HTML in one request.
- **`/v2/search` accepts `scrapeOptions`**, and `scrapeOptions.formats` accepts
  `{"type": "json", "schema": {...}}`. Firecrawl therefore searches, fetches each
  result page, and runs schema-guided extraction — all inside one HTTP call.

So the whole pipeline is a single POST. This is both simpler and the only option
that fits the interaction model.

**One detail to verify before building:** the `/scrape` docs place extracted
output at `data.json`; the `/search` response nests results under
`data.web[]`. Per-result extracted output is therefore *expected* at
`data.web[i].json`, but this is inference, not documented fact. **Task 1 of the
implementation plan is a single live probe** (one query, `limit: 2`) to confirm
the exact key before `_extract_firecrawl` is written against it.

## 2. Configuration

`FIRECRAWL_API_KEY` is **already present in the developer `.env`** but is wired
nowhere. Add:

- `src/cvp/config.py` — `firecrawl_api_key: str = ""`, placed beside
  `serp_api_key`.
- `.env.example` — a `# ── Firecrawl — web product search ──` block with
  `FIRECRAWL_API_KEY=`.
- Railway — the key must be set in the service environment before deploy.

An empty key must degrade gracefully: the tab renders with a disabled button and
the message "Firecrawl is not configured," mirroring how the Lens tab handles a
missing `PUBLIC_BASE_URL`. It must never 500.

## 3. `services/firecrawl.py`

New module, modelled closely on `services/serp.py`.

```python
FIRECRAWL_SEARCH_URL = "https://api.firecrawl.dev/v2/search"

def build_query(item: Item) -> str: ...
def call_firecrawl(query: str) -> tuple[str, dict, dict, int]: ...
```

**`call_firecrawl` returns the same 4-tuple contract as `call_serp`** —
`(request_url, params_dict, response_dict, status_code)` — and never raises into
the router. Timeouts, non-2xx, and non-JSON bodies all come back as
`{"error": "..."}` with `status_code=0`, exactly as `call_serp` does today.

Auth is `Authorization: Bearer <key>` (not SerpAPI's query-param style). The
`_mask_key`/`_mask_params` helpers in `serp.py` mask a query param, so masking
here must cover the **header** instead — the key must never reach
`SerpSearch.request_params`, which is persisted and admin-visible. Extract the
masking helpers to a shared location rather than duplicating them.

**Request body:**

```json
{
  "query": "<built from item fields>",
  "limit": 5,
  "sources": [{"type": "web"}],
  "country": "US",
  "scrapeOptions": {
    "onlyMainContent": true,
    "formats": [{
      "type": "json",
      "schema": {
        "type": "object",
        "properties": {
          "product_title":  {"type": "string"},
          "price":          {"type": "number"},
          "currency":       {"type": "string"},
          "retailer":       {"type": "string"},
          "in_stock":       {"type": "boolean"},
          "is_product_page":{"type": "boolean"}
        }
      }
    }]
  }
}
```

`is_product_page` is deliberate: it lets the extractor discard review articles,
listicles, and category pages that carry a number resembling a price. `currency`
guards against applying a GBP or CAD figure as USD.

**`build_query`** joins `brand`, `model`, and `description`, dropping empties and
collapsing whitespace. It appends no marketing words ("buy", "price") — those
skew results toward affiliate spam. The query is a plain string the specialist
can overwrite (§5).

## 4. `_extract_firecrawl` in `serp_display.py`

Add to the existing `_EXTRACTORS` dispatch table. Returns the **same normalized
dict** as `_extract_google_lens`:

```
title, source, link, thumbnail, source_icon, price_cents
```

Because the shape matches, `_serp_result.html` renders Firecrawl hits with no
template change and `serp_apply` accepts them unmodified.

Mapping, per result in `data.web[]`:

| Output field  | Source |
|---------------|--------|
| `title`       | extracted `product_title`, falling back to the result's `title` |
| `source`      | extracted `retailer`, falling back to the URL's hostname |
| `link`        | the result `url` |
| `thumbnail`   | `None` (v1 — `/search` web results carry no product image) |
| `source_icon` | `None` |
| `price_cents` | extracted `price` → cents |

**Drop a result entirely** when: `is_product_page` is false, `currency` is
present and not `USD`, or no positive price was extracted. A result with no
usable price is worse than no result — rule 2 exists so that an unsourced number
never enters the report. Cap at 5, matching `_RESULT_LIMIT`.

Reuse `_parse_price_cents` for the conversion. It currently expects SerpAPI's
`{"extracted_value": 49.99}` wrapper, so it needs a small generalization to also
accept a bare number — one function, covered by existing tests.

## 5. UI

`_serp_panel.html` gains a two-tab strip per crop — **Google Lens** | **Web
search** — with the same delegated-listener pattern already used for the
multi-crop selector strip. **No inline event handlers** (CSP forbids them);
wire via `data-*` attributes and `app.js`.

The Web search tab holds:

- A **pre-filled, editable text input** carrying `build_query(item)`, so a bad
  auto-query can be corrected and re-run. This mirrors the panel's existing
  escape hatch (the manual `image_url` field when `PUBLIC_BASE_URL` is unset).
- A submit button with the established `hx-post` / `hx-target` / `hx-indicator` /
  `hx-disabled-elt` wiring, targeting `#firecrawl-result-{{ crop.id }}`.
- The result list, rendered by the existing `_serp_result.html`.

Unlike the Lens button, the search button is **not** disabled after one run —
editing the query and re-running is the core interaction.

## 6. Router

New endpoint, mirroring `run_google_lens`:

```
POST /api/items/{item_id}/crops/{crop_id}/serp/firecrawl
```

`require_matter_role("editor")`, crop-ownership validation (404 / 403 as in the
Lens endpoint), `SerpSearch` row persisted with `service="firecrawl"`, audit log
written with action `serp.run`.

**No migration.** `SerpSearch.image_url` already defaults to `""`, so a text
search leaves it blank; the query lives in `request_params` with the rest of the
request record. `creditsUsed` from the response is captured for free because the
entire response body is persisted in `response_json`.

### 6.1 Two problems to fix while here

**`routers/serp.py` is already 208 lines**, over the 200-line ceiling CLAUDE.md
sets, before this adds ~60 more. Rather than split the resource, factor the
shared body — *run a search → persist `SerpSearch` → render result → audit* —
into a helper so both endpoints shrink to roughly 15 lines each. That removes the
duplication and brings the file back under the limit.

**`serp_apply` hardcodes `item.match_type = "exact"`** (`routers/serp.py:164`).
Every applied result is stamped as an exact product match regardless of what it
is. This is wrong today for Lens visual matches and would be wrong for text hits,
and it becomes load-bearing once a second path feeds the same endpoint. Fix:
carry `match_type` on each result row and pass it through the apply form.

The valid enum is **`exact` / `nearest_comparable` / `category_average`**
(`docs/data-model.md:126`, `docs/PRD.md:141`). A Firecrawl hit is `exact` only
when a brand was in the query and appears in the extracted title; otherwise
`nearest_comparable`.

Two related defects found while specifying this, both out of scope but worth
recording:

- **The enum has no shared constant.** Its only enumeration in code is a
  hardcoded list inside a Jinja loop (`_item_row_edit.html:150`); every Python
  default is a bare `"exact"` string. Anything validating `match_type` should
  introduce a module-level constant rather than repeat the literals a fourth
  time.

  *Correction (final review):* implementation initially left the Jinja loop
  hardcoded, on the recorded rationale that a template cannot see a Python
  tuple without adding a Jinja context processor. That rationale is wrong.
  `_item_row_edit_html` (`routers/items.py`) renders the template with explicit
  keyword arguments, so `match_types=MATCH_TYPES` is a one-line addition and no
  new surface is involved. `MATCH_TYPES` is now the template's source of truth.
- **`skills/MakeAIRecommendations/SKILL.md:34` instructs agents to submit
  `match_type` of `"brand"`** — not a member of the enum. Nothing validates it,
  so an accepted recommendation writes an invalid value straight into the
  report's audit column.

## 7. Error handling

Every failure renders inside the panel; none produce a 500.

| Condition | Behaviour |
|-----------|-----------|
| Key unset | Disabled button, "Firecrawl is not configured" |
| Timeout | "Search timed out" — 30s client timeout, below Firecrawl's 60s default |
| Non-2xx | Status and Firecrawl's message, key masked |
| `success: false` / `warning` | Surface the warning text |
| Zero usable results | "No priced product pages found — try editing the query" |
| Blocked page | That result is dropped, not shown with a guessed price |

The last row is a deliberate departure from the `MakeAIRecommendations` skill,
which currently instructs the agent to "note price as `~` estimate" on
Imperva/hCaptcha blocks. An estimate cannot satisfy rule 2. Here, a blocked page
yields nothing.

## 8. Testing

Mirrors existing conventions. Note that the Lens path has **only** display-layer
tests today — no router or service coverage — so this work adds a layer its
neighbour lacks.

- **`tests/test_serp_display.py`** — extend with `_extract_firecrawl` cases:
  field mapping, ≤5 cap, price→cents, empty response, and one test per drop rule
  (non-product page, non-USD currency, missing price).
- **`tests/test_firecrawl_service.py`** (new) — `build_query` assembly with
  missing brand/model; `call_firecrawl` timeout, non-2xx, and non-JSON paths via
  a mocked `httpx`; and an assertion that **the API key never appears in the
  returned `params_dict`**.
- **`tests/test_serp_router.py`** (new) — one happy-path integration test per
  CLAUDE.md, with `call_firecrawl` monkeypatched; plus 403 on a crop belonging to
  another item, and a `match_type` regression test asserting a `similar` hit is
  not stamped `exact`.

No live Firecrawl calls in the test suite.

## Components & boundaries

| Component | Responsibility | Depends on |
|-----------|----------------|------------|
| `services/firecrawl.py` | Build query, call API, mask secrets, never raise | `httpx`, `config` |
| `serp_display._extract_firecrawl` | Normalize + filter to the shared result shape | pure function |
| `routers/serp.py` (endpoint) | Auth, ownership, persist, render, audit | both of the above |
| `_serp_panel.html` | Tab strip, editable query, HTMX wiring | `_serp_result.html` |

`services/firecrawl.py` performs no DB access. `_extract_firecrawl` is pure and
independently testable — same discipline as `depreciation.py`.

## Deferred

- **Writing `AiRecommendation` rows.** The panel could later grow a **Propose**
  button beside **Apply**, feeding the existing review queue instead of mutating
  the item. Both affordances share the normalized result shape, so this is
  additive — no rework. Explicitly out of scope here.
- **Firecrawl in the external agent.** `skills/MakeAIRecommendations` still uses
  Brave + raw fetch and still degrades to `~` estimates on blocked pages.
  Pointing it at Firecrawl is a separate, skill-only change.
- **Shipping extraction.** Shipping usually sits behind a cart flow that a
  product-page scrape cannot reach. `shipping_cents` stays specialist-entered.
- **`SerpAPI` in rule 6.** SerpAPI is a live production dependency
  (`config.py:23`) that the approved-services list still omits. Flagged in PR #68
  and unaddressed; not in this scope.

## Open items for the implementation plan

1. **Probe the live API first** — confirm whether per-result extracted output is
   at `data.web[i].json`. Everything in §4 depends on it.
2. Confirm credit cost per search at `limit: 5` with `scrapeOptions` (5 pages =
   ~5 credits + extraction tokens) and decide whether the default limit should be
   lower.
3. Decide whether the shared masking helpers move to a new
   `services/_http.py` or stay in `serp.py` and get imported.
