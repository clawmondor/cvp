# Design: Product Detector Integration — Item Crops + Google Lens RCV Search

**Date:** 2026-04-23  
**Status:** Approved

## Summary

Integrate the core features of `productdetector` into the CVP app to enable specialists to:
1. Auto-crop individual items from evidence photos during Vision scans
2. Run Google Lens searches on those crops via SerpAPI
3. Pre-fill an item's RCV fields (`source_url`, `source_retailer`, `rcv_unit_cents`) from a search result in one click

The entry point is the Items tab inline — a "Find price" panel that expands below each item row.

---

## Data Model

### New table: `item_crops`

| column | type | notes |
|---|---|---|
| `id` | String PK | UUID |
| `item_id` | String FK → items | |
| `evidence_file_id` | String FK → evidence_files | which photo this came from |
| `bbox_left` | Integer | pixels, original image coordinates |
| `bbox_upper` | Integer | |
| `bbox_right` | Integer | |
| `bbox_lower` | Integer | |
| `crop_path` | String | relative path under `data/crops/` |
| `created_at` | DateTime | server_default now |

- `Item` gains a `crops` relationship (one-to-many)
- `EvidenceFile` gains a `crops` relationship (one-to-many)

### New table: `serp_searches`

| column | type | notes |
|---|---|---|
| `id` | String PK | UUID |
| `item_crop_id` | String FK → item_crops | the specific crop that was searched |
| `service` | String | `"google_lens"` for now |
| `image_url` | String | URL sent to SerpAPI |
| `request_url` | String | full SerpAPI request URL |
| `request_params` | Text | JSON |
| `response_json` | Text | raw SerpAPI response |
| `status_code` | Integer | |
| `ran_at` | DateTime | server_default now |

`SerpSearch` is deliberately tied to `item_crop_id` (not `item_id`) because the search uses the crop image as input — this preserves the full audit chain. When text-based services are added later, `item_crop_id` becomes nullable.

### Modified: `Item`

- Add `search_hint` String column — promoted from the `notes` text bag where it was previously stored as `search_hint:...`
- `notes` reverts to freeform specialist annotation only

### Config additions

`SERP_API_KEY` and `PUBLIC_BASE_URL` added to `config.py` and `.env.example`.

- `PUBLIC_BASE_URL`: when set, crop URLs auto-populate for Google Lens (production path)
- When unset, a manual URL paste field is shown (dev path)

### Migration

One Alembic migration:
1. Creates `item_crops` table
2. Creates `serp_searches` table
3. Adds `Item.search_hint` column
4. Backfills `search_hint` by parsing existing `notes` values (regex on `search_hint:...` prefix)
5. Strips `search_hint:...` fragment from existing `notes` values

---

## Vision Prompt + Scan Service

### New prompt: `SCAN_PROMPT_V3` in `services/vision_prompts.py`

Merges tor v2 and productdetector v7:

- **Insurance framing** from tor v2: "expert contents inventory specialist", RCV documentation purpose
- **Bounding box field** from productdetector v7 with full guidance:
  - `"bounding_box": [left, upper, right, lower]` in pixels
  - Generous box instructions: extend 10–15% past item edges
  - Overlapping boxes explicitly allowed
  - Include full item extent (soles, legs, handles, straps)
- **`build_scan_prompt(width, height)`** function — injects actual image dimensions and inline example coordinates
- All tor v2 **category hints** and field definitions preserved
- **Merged rules**: tor v2 structural exclusions + productdetector v7 visibility rules (skip partial items, skip items in display racks/shelving)
- Prompt version bumped to `"v3"`

### Updated `run_scan()` in `services/vision.py`

1. Open each image with Pillow before the API call to read `width` and `height`
2. Pass dimensions to `build_scan_prompt(width, height)`
3. Parse `bounding_box` from each item in the Vision response
4. Apply 15% padding to each bbox (clamped to image bounds)
5. Crop via Pillow, save JPEG to `data/crops/{evidence_file_id}/{item_id}.jpg`
6. Create `ItemCrop` row alongside each `Item` row
7. Write `search_hint` to `Item.search_hint` (not `notes`)
8. `notes` left empty (freeform field for specialist use)

Items where `bounding_box` is absent or invalid in the response get no `ItemCrop` — the item is still created, just without crop capability.

---

## SerpAPI Service + Routes

### `services/serp.py`

Ported from productdetector with minimal changes:

- `call_serp(service, item_crop, image_url)` — accepts `ItemCrop` instead of `DetectedItem`
- `build_crop_url(item_crop)` — builds public URL from `settings.public_base_url + item_crop.crop_path`
- `mask_params` / `mask_url` logging utilities included
- Google Lens only for now (`ENGINE_MAP` contains just `"google_lens"`)

### `services/serp_display.py`

Ported from productdetector:

- `extract_results("google_lens", response_dict)` → `list[dict]`
- Each result: `title`, `source`, `link`, `thumbnail`, `source_icon`
- Attempts to extract `price` from result metadata for "Use this" pre-fill

### `routers/serp.py`

**Endpoint 1 — Run search:**
```
POST /api/items/{item_id}/crops/{crop_id}/serp/google_lens
```
- Accepts optional `image_url` form field; falls back to `build_crop_url()` if not provided
- Persists `SerpSearch` row
- Returns `_serp_result.html` partial (HTMX)

**Endpoint 2 — Apply result:**
```
POST /api/items/{item_id}/serp-apply
```
- Accepts `source_url`, `source_retailer`, `rcv_unit_cents` (optional) as form fields
- Updates `Item`: sets `source_url`, `source_retailer`, `source_captured_at = now()`, `match_type = "exact"`
- If `rcv_unit_cents` provided: updates `rcv_unit_cents`, recomputes `rcv_total_cents = rcv_unit_cents * quantity`, and recomputes `acv_total_cents` via `depreciation.py` (unless `acv_override_cents` is set)
- Returns updated `_item_row.html` partial so the row refreshes in place; panel closes

---

## UI — Inline Search Panel in Items Tab

### `_item_row.html`

- Items **with** at least one `ItemCrop`: show a **"Find price"** button
- Items **without** a crop (pre-v3 scans): show a muted camera icon + tooltip "Re-scan evidence to enable Lens search"

Clicking "Find price" triggers:
```
GET /api/items/{item_id}/serp-panel   (hx-swap="afterend" on a wrapper <tr>)
```
Second click collapses the panel.

### `_serp_panel.html` (new template partial)

Structure:
1. **Crop thumbnail** — served via existing `/files/` static mount
2. **Crop selector strip** — if item has multiple crops, small thumbnails let specialist pick which to search
3. **Google Lens section:**
   - `PUBLIC_BASE_URL` set → auto-populated read-only URL field + Search button
   - Not set → manual URL paste field + Search button
   - HTMX spinner during request
4. **Results area** — up to 5 result cards:
   - Thumbnail + title + source domain + favicon
   - **"Use this"** button per card → posts to `/api/items/{item_id}/serp-apply`
5. After "Use this" fires:
   - Item row refreshes in place (shows populated source URL + price)
   - Panel closes
   - Row visually confirms RCV captured

### Items without crops

No dead end — the "Find price" slot shows: `📷 Re-scan evidence to enable Lens search` as a muted hint. The existing re-scan flow on the Evidence tab handles this.

---

## Future Work (out of scope for this task)

- Research additional image-based search services for RCV: eBay, Poshmark, and any SerpAPI-supported image engines
- Add text-based services (Google Shopping, Amazon) using `Item.search_hint` — `SerpSearch.item_crop_id` becomes nullable at that point
- ngrok / tunnel automation for dev environment if manual URL paste becomes a friction point
