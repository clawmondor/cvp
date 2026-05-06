# OpenRouter vision integration — design

**Status:** approved (brainstorm)
**Date:** 2026-05-06
**Owner:** specialist tooling

## Summary

Replace the direct Anthropic SDK call in the evidence-scan pipeline with an OpenRouter HTTP client so specialists can pick from any vision-capable model when running a scan. Admins curate the available models through `/admin/vision-models`; the catalog of selectable models is populated from a live fetch of OpenRouter's `/api/v1/models` endpoint, filtered to vision-capable entries. A small per-model adapter layer normalizes bounding-box coordinates so cropping continues to work for models (e.g., Gemini) that don't return pixel coords.

Motivation is the union of (a) experimentation across providers, (b) cost flexibility, and (c) vendor redundancy. Model selection is a first-class workflow choice, not a hidden config.

## Goals

- Specialists can pick a vision model per scan from a curated list, with a system default and a per-user "last used" sticky preference.
- Admins can add or remove models via `/admin/vision-models`, picking from a live OpenRouter catalog.
- Cropping continues to work for any model whose bbox format we know how to normalize.
- A `VisionRun` row's audit story (which model ran, what it cost, what adapter normalized the output) is durable across pricing changes and removed catalog rows.

## Non-goals

- Automatic fallback between models on error. If a scan fails, the specialist re-runs with a different model. Predictable cost and provenance > automatic resilience.
- Per-image model selection. Model is per-scan-batch.
- Per-model prompt forking. One prompt template (`SCAN_PROMPT_VERSION`) for all models. Differences are absorbed in the bbox adapter, not the prompt.
- Surfacing the model slug on generated PDFs/CSVs. Model choice is internal-only.
- Live retailer scraping or any change to the depreciation/cost flow downstream of item creation.

## Decisions made during brainstorming

| Decision | Choice | Rationale |
|---|---|---|
| Motivation | Broad model selection as first-class workflow choice | Covers experimentation, cost, and redundancy in one feature. |
| UI scope | Global default + per-scan override | Mirrors today's `vision_model` config; lets admin standardize while keeping per-scan control. |
| Provider strategy | Replace Anthropic SDK entirely with OpenRouter | One client, one key, one billing surface. Accepts loss of prompt caching and ~5% markup as a worthwhile simplification. |
| Catalog source | Admin-managed DB rows; admin "add" UI fetches dynamically from OpenRouter | Curated list keeps the picker short and scoped to models with known adapters; live fetch removes hardcoded slug maintenance. |
| Bbox handling | Per-model adapter; unknown adapter ⇒ items only, no crop | Addresses real format differences (Gemini normalized 0–1000, Claude pixel) without prompt forking. |

## Architecture

### Provider client

`src/cvp/services/vision.py` no longer instantiates `anthropic.Anthropic`. A new `src/cvp/services/openrouter.py` exposes:

```python
def call_vision(
    model_slug: str,
    image_bytes: bytes,
    mime_type: str,
    prompt: str,
    *,
    timeout_seconds: float = 120.0,
) -> str:
    """POST to OpenRouter chat completions; return the raw text content of the
    first choice. Raises OpenRouterError on 4xx/5xx, httpx.TimeoutException on
    timeout."""
```

Implementation: `httpx.Client.post("https://openrouter.ai/api/v1/chat/completions", ...)` with OpenAI-compatible payload (text part + `image_url` part using a base64 `data:` URL), `Authorization: Bearer {OPENROUTER_API_KEY}`, optional `HTTP-Referer` and `X-Title` headers from settings. The `httpx` dep is already in `pyproject.toml`; no new packages.

`run_scan` in `vision.py` calls `openrouter.call_vision(...)` instead of `client.messages.create(...)`. The 500 ms inter-call sleep stays. The response-parsing logic (`_parse_response`) is unchanged because the prompt continues to require a JSON-array response.

### Data model

**New table `vision_models`** (Alembic migration):

| column | type | notes |
|---|---|---|
| `id` | int PK | |
| `slug` | str unique not null | OpenRouter model id, e.g. `anthropic/claude-opus-4` |
| `display_name` | str not null | shown in pickers |
| `adapter` | str not null | `pixel_passthrough` \| `gemini_normalized_1000` \| `none` |
| `prompt_image_cost_cents` | int nullable | per-image cost snapshot from OpenRouter pricing at add/refresh time; null ⇒ unknown |
| `context_length` | int nullable | snapshot from OpenRouter |
| `supports_bbox` | bool not null | derived from `adapter != 'none'`; stored for query convenience |
| `is_default` | bool not null default false | exactly one row may be true (enforced by partial unique index `WHERE is_default`) |
| `is_enabled` | bool not null default true | soft-disable without deletion |
| `recommended` | bool not null default false | derived from internal `RECOMMENDED_SLUGS` set at insert time; informational badge |
| `added_by_user_id` | uuid FK users.id | audit |
| `added_at` | tstz not null | audit |

Seed (in the same migration): one row for `anthropic/claude-opus-4` with `adapter=pixel_passthrough`, `is_default=true`, `is_enabled=true`, `recommended=true`, `added_by_user_id=null`. Pricing is nullable on the seed row; the admin can hit "refresh pricing" once OpenRouter is wired up.

**`User` table change:** add `last_vision_model_slug` (str nullable). Single-column migration. Used as the per-user picker default.

**`VisionRun` table change:** add two audit columns:
- `adapter` (str not null default `"none"`) — which adapter ran for this scan.
- `cost_cents_estimated` (int nullable) — snapshot of `prompt_image_cost_cents` at scan time. Null when pricing was unknown.

`VisionRun.model` (already a string column) continues to record the slug. No FK to `vision_models` — keeping it a string preserves audit history when catalog rows are removed.

### Adapters

`src/cvp/services/vision_adapters.py`:

```python
def pixel_passthrough(raw, w, h): ...
def gemini_normalized_1000(raw, w, h): ...
def none_adapter(raw, w, h): return None

REGISTRY: dict[str, Callable[[Any, int, int], tuple[int, int, int, int] | None]] = {
    "pixel_passthrough": pixel_passthrough,
    "gemini_normalized_1000": gemini_normalized_1000,
    "none": none_adapter,
}
```

Each adapter signature: `(raw_bbox: Any, img_width: int, img_height: int) -> tuple[int, int, int, int] | None`.

- `pixel_passthrough` is the existing `_parse_bbox` body, lifted unchanged including the 15% generous padding.
- `gemini_normalized_1000` accepts a 4-element list/tuple of integers in `[0, 1000]`, scales to image dimensions, then applies the same 15% padding and clamping logic.
- `none_adapter` always returns `None`. Used for models we don't know how to crop with.

The existing `_parse_bbox` in `vision.py` is removed; `run_scan` now calls `REGISTRY[adapter_name](raw, w, h)`. Unknown adapter name ⇒ treated as `"none"` with a warning logged.

### Configuration

`src/cvp/config.py` changes:

```python
# removed
anthropic_api_key: str
vision_model: str
vision_model_fallback: str

# added
openrouter_api_key: str = ""
openrouter_referer: str = ""    # sent as HTTP-Referer header (optional)
openrouter_app_title: str = "CVP"  # sent as X-Title header (optional)
```

`.env.example`:

```
OPENROUTER_API_KEY=
OPENROUTER_REFERER=https://your-domain.example
OPENROUTER_APP_TITLE=CVP
```

The `anthropic` package stays in `pyproject.toml` for one release cycle to ease rollback, then is removed in a follow-up cleanup PR. No production code path imports it after this change.

## Admin UI: `/admin/vision-models`

New page registered under the existing `/admin` router. Admin role required (existing RBAC).

**Index view.** Server-rendered table of all `vision_models` rows. Columns:
- Display name (with recommended badge if `recommended`)
- Slug (monospace)
- Per-image cost (`$0.0YYY` or `?` if null)
- Bbox support (✓ / —)
- Default (radio button — selecting flips the previous default in the same POST)
- Enabled (toggle)
- Actions: "Refresh pricing", "Remove"

**Add model flow.**

1. "Add model" button opens a modal.
2. Modal fetches `GET /admin/vision-models/openrouter-catalog` server-side. The handler calls `https://openrouter.ai/api/v1/models`, filters to entries whose `architecture.input_modalities` includes `"image"`, excludes slugs already present in our DB, and returns the filtered list. Result is cached in-process for 1 hour to avoid hammering OpenRouter.
3. Modal renders a searchable table: slug, display name (from OpenRouter `name`), per-image price (from `pricing.image`, which OpenRouter returns as a decimal-string USD-per-image; we parse to float, multiply by 100, round to int cents for storage), context length, description blurb. A small icon marks slugs in our internal `RECOMMENDED_SLUGS` constant. Models with a missing or zero `pricing.image` are still listed but show `?` and store `prompt_image_cost_cents=null`.
4. Admin picks a row; a second step asks which adapter to use. Default suggestion comes from an internal lookup table:
   - `anthropic/*` → `pixel_passthrough`
   - `google/gemini-*` → `gemini_normalized_1000`
   - everything else → `none`
   Admin can override the suggestion via dropdown.
5. Submit POSTs to `POST /admin/vision-models` which inserts the row, snapshotting `display_name`, `prompt_image_cost_cents`, `context_length` from the OpenRouter response.

**Refresh pricing.** `POST /admin/vision-models/{id}/refresh-pricing` re-hits OpenRouter for that one slug, updates `prompt_image_cost_cents` and `context_length`. No-op if the slug is no longer listed by OpenRouter (a warning is rendered inline).

**Removal.** `POST /admin/vision-models/{id}/disable` flips `is_enabled` to false. Hard delete (`DELETE /admin/vision-models/{id}`) is allowed only when no `VisionRun` references the slug; otherwise the UI shows "in use — disable instead." Cannot disable or delete the row that is `is_default`.

**Internal `RECOMMENDED_SLUGS` constant** lives in `src/cvp/services/vision_models.py` alongside the adapter-suggestion table:

```python
RECOMMENDED_SLUGS: set[str] = {
    "anthropic/claude-opus-4",
    "anthropic/claude-sonnet-4",
    "google/gemini-2.5-pro",
}
ADAPTER_SUGGESTIONS: list[tuple[str, str]] = [
    ("anthropic/", "pixel_passthrough"),
    ("google/gemini-", "gemini_normalized_1000"),
]
```

Updates to these constants are code changes; that's intentional — adding a new "recommended" or new auto-adapter mapping is an engineering decision, not an admin one.

## Specialist UI: per-scan picker

The matter detail page already has a "Scan Selected Images" form. It gains:

- A `<select name="model_slug">` populated from `vision_models` where `is_enabled=true`, ordered by `recommended desc, display_name asc`.
- Default selected option:
  - `current_user.last_vision_model_slug` if set and the row is still enabled, else
  - the row with `is_default=true`.
- Each option label includes the per-image cost, e.g., `Claude Opus 4 — ~$0.025`. Options where `supports_bbox=false` get a `📎` indicator and a `(no auto-crop)` suffix.

`POST /api/matters/{matter_id}/vision-scan` (in `routers/vision.py`) accepts a new `model_slug` form field. It validates the slug against `vision_models` (must be enabled). The handler:
- Updates `current_user.last_vision_model_slug = model_slug`.
- Writes the audit log with `model_slug` in metadata.
- Calls `vision_svc.create_job(image_ids)` and `BackgroundTasks.add_task(vision_svc.run_scan, job_id, matter_id, image_ids, model_slug)`.

`run_scan` signature changes to accept `model_slug`. It looks up the matching `VisionModel` row once at the top to capture `adapter` and `prompt_image_cost_cents`, then uses those for every file in the batch. Each `VisionRun` row written for the batch records `model=slug`, `adapter=resolved_adapter`, `cost_cents_estimated=snapshot`.

## Cost display

`estimate_cost(n_images, model_slug)` looks up `prompt_image_cost_cents` for the slug and returns `~$X.YY` (cents → dollars). If the row's price is null, returns `~$?` and the UI shows a tooltip directing the admin to refresh pricing. The hardcoded `_COST_PER_IMAGE_USD = 0.025` constant is removed.

The pre-scan cost line on the matter page becomes reactive to the selected model: a tiny HTMX `hx-trigger="change"` on the `<select>` swaps a `<span id="cost-estimate">` based on `GET /api/matters/{matter_id}/vision-scan/estimate?count=N&model_slug=...`.

## Error handling

`run_scan` replaces its `anthropic.APIError` branch with:

- `OpenRouterError` (raised by `openrouter.call_vision` for any 4xx/5xx, including upstream provider errors that OpenRouter forwards): recorded in `_jobs[job_id]["errors"]` as `f"File {file_id}: API error — {status} {message}"`. Scan continues.
- `httpx.TimeoutException`: recorded as `f"File {file_id}: timeout"`. Scan continues.
- `BboxParseError` (raised by an adapter only when raw input is so malformed that even `None` would mislead — currently only `gemini_normalized_1000` raising on a non-list value): caught inside the per-item loop, item is created without a crop, no error appended.
- Bare `Exception`: same fallback as today.

The 500 ms inter-call sleep stays. There is no automatic fallback to a second model.

## Audit

- `VisionRun.model` records the slug (existing column, new value semantics).
- `VisionRun.adapter` records which adapter ran (new column).
- `VisionRun.cost_cents_estimated` records the per-image price snapshot at scan time (new column).
- `VisionRun.raw_response` continues to capture the full raw text (unchanged).
- The `audit_log` row written by `start_scan` (action `vision.run`) gains `model_slug` in its metadata.
- The admin audit log captures `vision_model.add`, `vision_model.disable`, `vision_model.delete`, `vision_model.set_default`, `vision_model.refresh_pricing` actions, each tied to the actor `user_id`.

## Migration plan

One Alembic revision performs all of:

1. Create `vision_models` table.
2. Add `vision_runs.adapter` (default `"none"` for backfill — historical rows didn't track this), `vision_runs.cost_cents_estimated` (nullable, no backfill).
3. Add `users.last_vision_model_slug` (nullable).
4. Insert the seed row for `anthropic/claude-opus-4`.

No data deletion. Rollback drops the new columns/table.

## Tests

- **Unit (`tests/services/test_vision_adapters.py`):** for each adapter, happy path + clamping + out-of-bounds + malformed raw.
- **Unit (`tests/services/test_openrouter_catalog.py`):** filter logic produces vision-only results, dedupes against DB, surfaces price/context fields correctly.
- **Unit (`tests/services/test_vision_cost.py`):** `estimate_cost` happy path and null-price path.
- **Integration (`tests/routers/test_vision.py`):** mock `openrouter.call_vision` to a fixed JSON payload; assert `Item` and `ItemCrop` rows created, `VisionRun` records slug + adapter + cost snapshot. One test for the bbox-malformed path (item created, no crop, no error).
- **Integration (`tests/routers/test_admin_vision_models.py`):** add flow with OpenRouter catalog endpoint mocked; default-flip behavior; soft-disable; hard-delete guard when `VisionRun` references the slug.
- The pre-existing `_COST_PER_IMAGE_USD` test (if any) is removed.

## Backward compatibility

- Existing `VisionRun` rows keep their `model` strings (Anthropic model ids); they remain readable in audit views even though those slugs aren't in the new catalog.
- Specialists with no `last_vision_model_slug` get the system default — same UX as today.
- The `anthropic` package stays installed for one release. A follow-up cleanup PR removes it from `pyproject.toml` and deletes any remaining import sites surfaced by ruff.

## Out of scope (deferred)

- Per-image or per-room model selection.
- Auto-fallback between models on error.
- Cost dashboards or budget caps.
- Streaming responses from OpenRouter (we keep the synchronous request shape).
- Per-model prompt variants (one `SCAN_PROMPT_VERSION` for all models).
- Removing the `anthropic` dependency (separate cleanup PR).
