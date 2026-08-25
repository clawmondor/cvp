---
name: MakeAIRecommendations
description: "Poll CVP for items needing pricing, search for product matches, submit two sourced price recommendations per item."
---

# MakeAIRecommendations

Poll the Contents Valuation Platform for items that need pricing recommendations,
search the web for matching products, and submit two sourced recommendations per
item.

## Setup

Read the `airecommendations` skill at `skills/airecommendations/SKILL.md` for the
full API reference, authentication, endpoint shapes, and error handling. Do not
inline those details here — keep this skill focused on the workflow.

API key: `CVP_AGENT_KEY` env var. Base URL: `https://cvp.cmondor.com`.

## Workflow

1. **Poll items** — use `client.list_items(limit=N)` from the airecommendations
   client. Default limit is **5** unless the user specifies otherwise. To scope a
   run, pass `matter_id="…"` (all eligible items in one matter) or `item_id="…"`
   (a single item); both still return only items that need pricing.

2. **For each item**, search the web (Brave) for two product matches:
   - Search query: `{brand} {description} price buy online`
   - Fetch top results to get confirmed prices
   - Prefer exact-size matches; fall back to similar-size or brand-only

3. **Submit recommendations** — use `client.submit_recommendation()` with
   `proposed_retail_unit_cents` (integer cents), `source_url`, `source_retailer`,
   `match_type` (`exact` or `brand`), `product_title`, and `rationale`.
   Set `proposed_shipping_cents=0` unless shipping is confirmed.

4. **Print a summary table** with item description, retailer, unit price, and
   recommendation ID for each submitted recommendation.

## Rules

- Currency is **integer cents** (e.g. `$3.97` → `397`). Never use floats.
- Every recommendation needs a `source_url` and `source_retailer` — no blanks.
- Submit exactly **2 recommendations per item** (unless only one match is found).
- **409** (5-pending cap) → skip that item. **401** → stop; key is bad/revoked.
- Prefer exact size/brand for rec 1; different retailer or smaller size OK for rec 2.
- Blocked retailer pages (Imperva/hCaptcha) — note price as `~` estimate and use
  the best available data.

## Prompting tip

When the user says "make recommendations" or "price the next N items" without
specifying a number, use the default limit of 5. If they name a specific matter
or item (e.g. "price matter X" or "price this item"), pass `matter_id` or
`item_id` to `list_items` to scope the run.
