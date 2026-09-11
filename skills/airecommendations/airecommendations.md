# AI Recommendations Agent Skill

How an external AI agent reads items that need pricing and submits pricing
**recommendations** to the Contents Valuation Platform.

Recommendations are *proposals*: they never change an item's valuation directly.
A human specialist reviews each one in the app and Accepts or Dismisses it.
Your job as an agent is to find a well-matched product for an item and submit a
sourced price.

## When to use

Use this skill when operating an external agent that:

1. polls for items the vision scan identified with high confidence but that have
   no price yet, and
2. shops external retailers for a matching product, then
3. submits a recommendation (source URL, unit price, shipping) back to the API.

The agent is fully decoupled from the app — it only needs the base URL and an
API key. It never logs in as a user and never touches the database directly.

## Authentication

Every request sends an `X-API-Key` header:

```
X-API-Key: agk_live_<prefix>_<secret>
```

An admin mints the key in the app under **System Admin → Agent Keys**. The full
key is shown **once** at creation — copy it then; only its hash is stored, so it
cannot be retrieved later. If a key is compromised, an admin revokes it and
issues a new one.

Provide the key to the reference client via the constructor or the
`AI_RECS_API_KEY` environment variable.

A missing, malformed, unknown, or revoked key returns **401**.

## The loop

```
GET /api/agent/items            # items needing a recommendation (paged)
  -> for each item:
GET /api/agent/crops/{path}     # (optional) fetch the crop image(s) to identify it
  -> shop external retailers for a match
POST /api/agent/items/{id}/recommendations   # submit your proposal
```

An item stops appearing in the feed once it has a source (a recommendation was
accepted) or already has 5 pending recommendations.

## Rules the agent must respect

- **Currency is integer cents.** Send `proposed_retail_unit_cents` /
  `proposed_shipping_cents` as whole-number cents (e.g. `$129.99` → `12999`).
  Use `dollars_to_cents()` from the reference client. Negative values are
  rejected (422).
- **Every recommendation must be sourced.** `source_url` and `source_retailer`
  are required and must be non-empty (empty → 422). This is what lets a
  specialist accept the price with an audit trail.
- **Five pending per item.** Submitting a 6th pending recommendation for the
  same item returns **409**. Skip the item and move on (a specialist will clear
  the queue by accepting or dismissing).
- **Confidence threshold is admin-configurable.** By default only `high`
  confidence items appear. You can request a lower bar with
  `min_confidence=medium|low`, but the server may still cap what it returns.

## Endpoint reference

All paths are under the app base URL and require the `X-API-Key` header.

### `GET /api/agent/items`

List items needing a recommendation.

Query params:

| param            | type | default | notes                                            |
|------------------|------|---------|--------------------------------------------------|
| `min_confidence` | str  | server  | `high` / `medium` / `low`; overrides default     |
| `matter_id`      | str  | —       | scope the feed to one matter                     |
| `item_id`        | str  | —       | scope the feed to one item                       |
| `limit`          | int  | 50      | 1–200                                            |
| `offset`         | int  | 0       | paging offset                                    |

`matter_id` and `item_id` still respect the eligibility rules (unpriced, above
the confidence threshold, below the 5-pending cap), so a matter or item whose
work is already done returns an empty list.

Response `200`:

```json
{
  "items": [
    {
      "item_id": "…",
      "description": "oak dining chair",
      "brand": "Stickley",
      "model": null,
      "category": "Furniture",
      "quantity": 4,
      "vision_confidence": "high",
      "matter_id": "…",
      "crops": [
        { "item_crop_id": "…", "image_url": "/api/agent/crops/crops/abc123.jpg" }
      ]
    }
  ]
}
```

### `GET /api/agent/items/{item_id}`

One item's detail, same shape as a feed entry. `404` if the item does not exist.

### `GET /api/agent/crops/{crop_path}`

The raw crop image bytes for the `image_url` returned in a feed entry. `404` if
the file is missing, `403` on a path-traversal attempt.

### `POST /api/agent/items/{item_id}/recommendations`

Submit a recommendation. Request body:

```json
{
  "proposed_retail_unit_cents": 12999,
  "proposed_shipping_cents": 950,
  "source_url": "https://retailer.example/product/123",
  "source_retailer": "Retailer",
  "match_type": "exact",
  "product_title": "Oak dining chair, set of 1",
  "rationale": "Same maker and silhouette as the crop",
  "item_crop_id": "…",
  "agent_run_id": "…"
}
```

`proposed_shipping_cents` defaults to `0`; `match_type` defaults to `"exact"`;
`product_title`, `rationale`, `item_crop_id`, and `agent_run_id` are optional.
`agent_run_id` attributes the submission to a CVP-launched agent run; a
standalone external agent has no run and omits it.

Responses:

| status | meaning                                                        |
|--------|---------------------------------------------------------------|
| `201`  | created — `{ "id", "status": "pending", "item_id" }`          |
| `401`  | missing / invalid / revoked API key                           |
| `404`  | item does not exist                                           |
| `409`  | item already has 5 pending recommendations — skip it          |
| `422`  | validation error (empty source fields, negative cents, etc.)  |

## Usage — reference client

`scripts/agent_client.py` is a zero-dependency (standard-library only) client.
Copy it into your agent or import it directly.

```python
from agent_client import AiRecommendationsClient, AgentApiError, dollars_to_cents

client = AiRecommendationsClient("https://app.example.com", api_key="agk_live_...")

for item in client.list_items(min_confidence="high", limit=50):
    crop_bytes = None
    if item["crops"]:
        crop_bytes = client.fetch_crop(item["crops"][0]["image_url"])

    # ... your product search produces a match ...

    try:
        client.submit_recommendation(
            item["item_id"],
            retail_unit_cents=dollars_to_cents("129.99"),
            shipping_cents=dollars_to_cents("9.50"),
            source_url="https://retailer.example/product/123",
            source_retailer="Retailer",
            product_title="Oak dining chair",
            rationale="Same maker and silhouette as the crop",
            item_crop_id=item["crops"][0]["item_crop_id"] if item["crops"] else None,
        )
    except AgentApiError as exc:
        if exc.status == 409:
            continue  # cap reached — move on
        raise
```

CLI demo of the poll→submit loop (use `--dry-run` to only list items):

```bash
export AI_RECS_API_KEY=agk_live_...
python skills/airecommendations/scripts/agent_client.py \
  --base-url https://app.example.com --min-confidence high --dry-run
```

## Error handling

The client raises `AgentApiError` (with `.status` and `.detail`) on any non-2xx
response. Recommended handling:

- **401** — stop; the key is bad or revoked. Get a fresh key from an admin.
- **404** — the item was removed; drop it and continue.
- **409** — the item's pending queue is full; skip and continue.
- **422** — a bug in your payload (empty source, negative cents). Fix and retry.

## Testing

`tests/test_agent_client_skill.py` wires the reference client's network seam to
the app's FastAPI test client and drives the real `/api/agent/*` endpoints, so
the client stays in lockstep with the API. Run it with:

```bash
uv run pytest tests/test_agent_client_skill.py -v
```
