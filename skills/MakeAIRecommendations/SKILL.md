---
name: MakeAIRecommendations
description: "Poll CVP for items needing pricing, search for product matches, submit two sourced price recommendations per item."
---

# MakeAIRecommendations

Poll the Contents Valuation Platform for items that need pricing recommendations,
search the web for matching products, and submit two sourced recommendations per
item.

## Workflow

1. **Collect API key** from `CVP_AGENT_KEY` environment variable. Base URL:
   `https://cvp.cmondor.com`.

2. **Poll items** — `GET /api/agent/items?limit={N}` with `X-API-Key` header.
   Default limit is **5** unless the user specifies otherwise.

3. **For each item**, search the web (Brave) for two product matches:
   - Search query: `{brand} {description} price buy online`
   - Fetch top results to get confirmed prices
   - Prefer exact-size matches; fall back to similar-size or brand-only

4. **Submit recommendations** — `POST /api/agent/items/{item_id}/recommendations`
   with `proposed_retail_unit_cents` (integer cents), `source_url`,
   `source_retailer`, `match_type` (`exact` or `brand`), `product_title`,
   and `rationale`. Set `proposed_shipping_cents=0` unless shipping is confirmed.

5. **Print a summary table** with item description, retailer, unit price, and
   recommendation ID for each submitted recommendation.

## Rules

- Currency is **integer cents** (e.g. `$3.97` → `397`). Never use floats.
- Every recommendation needs a `source_url` and `source_retailer` — no blanks.
- Submit exactly **2 recommendations per item** (unless only one match is found).
- **409** (5-pending cap) → skip that item. **401** → stop; key is bad/revoked.
- Prefer exact size/brand for rec 1; different retailer or smaller size OK for rec 2.
- Blocked retailer pages (Imperva/hCaptcha) — note price as `~` estimate and use
  the best available data.

## API reference

Base URL: `https://cvp.cmondor.com`
Auth: `X-API-Key: <CVP_AGENT_KEY>`

```
GET  /api/agent/items?limit=N&min_confidence=high
POST /api/agent/items/{item_id}/recommendations
     Body: {
       "proposed_retail_unit_cents": int,
       "proposed_shipping_cents": int,       (default 0)
       "source_url": str,
       "source_retailer": str,
       "match_type": "exact" | "brand",      (default "exact")
       "product_title": str,
       "rationale": str,
       "item_crop_id": str | null
     }
```

## Prompting tip

When the user says "make recommendations" or "price the next N items" without
specifying a number, use the default limit of 5.
