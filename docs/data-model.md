# Data Model

**Status:** Source of truth for SQLAlchemy models and Alembic migrations
**Last reviewed:** [date]

This document describes the full relational schema for the Contents Valuation Prototype, explains the design decisions behind it, and serves as the reference for any future migration. If you're changing the schema, update this file in the same commit as the migration.

---

## Philosophy

Five principles drive the design:

1. **Audit trail is the product.** Every row that contributes to a price in a delivered report must be traceable to its source, its capture time, and the specialist who confirmed it. The schema forces this — you cannot store an RCV without a `source_url`, `source_retailer`, `source_captured_at`, and `match_type`.

2. **Currency as integer cents, everywhere.** No `FLOAT`, no `NUMERIC`, no `DECIMAL` column ever stores money. Every money field is `INTEGER` and named with a `_cents` suffix. Formatting to dollars happens at the template and export layer only. This eliminates an entire class of rounding bugs that matter a lot in a litigation context.

3. **UUID strings, not integers, for primary keys.** External IDs in URLs, filenames, and file paths should never expose a monotonically increasing counter that leaks business metrics ("oh, they're on matter #47"). Store UUIDs as TEXT in SQLite — no native UUID type, and SQLAlchemy handles the conversion transparently.

4. **Deletes are rare and usually soft.** Matters and items are archived, not deleted, once any delivered report has referenced them. The exceptions are evidence files (which the specialist can remove before scanning) and draft items that failed Vision recognition. A `status` column on matters captures archival state; items use an `excluded` flag to keep history intact.

5. **Schema changes need a migration.** Never modify an existing migration file. Never edit `models.py` without generating a new Alembic revision in the same commit. Never drop a column without checking that no delivered report's regeneration path still references it.

---

## Tables

### ER diagram (logical)

```
matters ─┬─< rooms
         ├─< items ──> categories
         ├─< evidence_files ──< vision_runs ──> items
         └─< exports
```

Every entity below `matters` is scoped to one matter. There are no cross-matter relationships in v0 — a matter is fully self-contained, which means a matter can be archived, exported as a tarball, or deleted without cascading to anything outside its own subtree.

### `matters`

One row per insurance claim the firm is working on.

| Column                | Type        | Null | Default        | Notes |
|:----------------------|:------------|:-----|:---------------|:------|
| id                    | TEXT        | no   |                | UUID string, primary key |
| firm_name             | TEXT        | no   |                | Name of the law firm that hired us |
| attorney_name         | TEXT        | no   |                | Responsible attorney |
| attorney_email        | TEXT        | no   |                | Delivery email for the final report |
| policyholder_name     | TEXT        | no   |                | Underlying claim owner |
| loss_location         | TEXT        | no   |                | Full street address of the loss |
| loss_type             | TEXT        | no   |                | Enum: `total_loss` / `partial_loss` / `smoke` / `water` / `theft` / `other` |
| loss_event            | TEXT        | no   |                | Free text: "Palisades Fire", "Eaton Fire", or custom |
| loss_date             | DATE        | no   |                | Date of the covered event |
| carrier               | TEXT        | no   |                | Insurance carrier name |
| policy_number         | TEXT        | yes  |                | May not be available at intake |
| claim_number          | TEXT        | yes  |                | May not be available at intake |
| coverage_c_limit_cents| INTEGER     | yes  |                | Personal property limit, in cents |
| firm_file_number      | TEXT        | yes  |                | Firm's internal file reference |
| status                | TEXT        | no   | `'draft'`      | Enum: `draft` / `in_review` / `delivered` / `archived` |
| target_delivery_date  | DATE        | yes  |                | SLA the firm was quoted |
| delivered_date        | DATE        | yes  |                | Set when status transitions to `delivered` |
| invoice_amount_cents  | INTEGER     | yes  |                | What we billed the firm |
| internal_notes        | TEXT        | yes  |                | Private notes for the specialist |
| created_at            | DATETIME    | no   | UTC now        | Timezone-aware UTC |
| updated_at            | DATETIME    | no   | UTC now        | Auto-updated on every write |

**Indexes:** `status`, `(firm_name, status)` for dashboard queries, `created_at DESC` for recency ordering.

**Why enums are stored as TEXT:** SQLite has no native ENUM type. Using TEXT with a CHECK constraint (via SQLAlchemy) gives us the same validation without the portability headaches. The enum values are defined once as Python literals in `src/cvp/models.py` and imported wherever needed.

### `rooms`

Rooms are per-matter, not global. Every matter defines its own rooms because "Primary bedroom" in a 4,500 sq ft Palisades home is not the same thing as "Primary bedroom" in a 1,200 sq ft Altadena bungalow.

| Column       | Type     | Null | Default | Notes |
|:-------------|:---------|:-----|:--------|:------|
| id           | TEXT     | no   |         | UUID string |
| matter_id    | TEXT     | no   |         | FK → matters.id, ON DELETE CASCADE |
| name         | TEXT     | no   |         | "Primary bedroom", "Kitchen", "Garage" |
| sort_order   | INTEGER  | no   | 0       | Ascending; specialist-controlled |
| created_at   | DATETIME | no   | UTC now |
| updated_at   | DATETIME | no   | UTC now |

**Indexes:** `(matter_id, sort_order)` for ordered rendering in the UI.

**Design note:** rooms used to be an enum in an earlier draft, but real Palisades properties have wine cellars, pool houses, guest casitas, and "the kids' reading nook" that don't map to any clean fixed list. Free-text per-matter is the right call.

### `categories`

The 42 depreciation categories. **Read-only in v0**, seeded from `docs/depreciation-schedule.md`. Seed via `uv run seed`, idempotently.

| Column             | Type     | Null | Default | Notes |
|:-------------------|:---------|:-----|:--------|:------|
| id                 | INTEGER  | no   |         | 1–42, matches the schedule doc |
| name               | TEXT     | no   |         | "Clothing, everyday" |
| useful_life_years  | INTEGER  | yes  |         | NULL = non-depreciable (artwork, jewelry, etc.) |
| acv_floor_pct      | REAL     | no   |         | 0.0 to 1.0; the floor for ACV/RCV ratio |
| notes              | TEXT     | yes  |         | Examples and guidance |

**Why integer ID instead of UUID:** categories are a fixed, small, human-referenceable enumeration. Integer IDs are more readable in logs, exports, and URLs. This is the only exception to the UUID-primary-key rule.

**Validation:** seed script asserts exactly 42 rows exist after seeding, and that IDs are contiguous 1–42. A missing category is a fatal startup error.

### `items`

The single most important table. Every delivered report is, at its core, a filtered view of this table.

| Column                | Type     | Null | Default  | Notes |
|:----------------------|:---------|:-----|:---------|:------|
| id                    | TEXT     | no   |          | UUID string |
| matter_id             | TEXT     | no   |          | FK → matters.id, ON DELETE CASCADE |
| room_id               | TEXT     | yes  |          | FK → rooms.id, ON DELETE SET NULL |
| line_number           | INTEGER  | no   |          | Per-matter sequential, assigned on confirm |
| description           | TEXT     | no   |          | Human-readable item description |
| brand                 | TEXT     | yes  |          | Manufacturer, if identified |
| model                 | TEXT     | yes  |          | Specific model or SKU, if identified |
| category_id           | INTEGER  | no   |          | FK → categories.id |
| quantity              | INTEGER  | no   | 1        | Always ≥ 1 |
| age_years             | REAL     | no   | 0.0      | Fractional years allowed |
| condition             | TEXT     | no   | `'average'` | Enum: `excellent` / `above_average` / `average` / `below_average` |
| rcv_unit_cents        | INTEGER  | yes  |          | Per-unit replacement cost; NULL before pricing |
| rcv_total_cents       | INTEGER  | yes  |          | Computed: quantity × rcv_unit_cents |
| acv_total_cents       | INTEGER  | yes  |          | Computed via depreciation formula |
| acv_override_cents    | INTEGER  | yes  |          | Manual override of the computed ACV |
| acv_override_reason   | TEXT     | yes  |          | Required whenever override is set |
| match_type            | TEXT     | yes  |          | Enum: `exact` / `nearest_comparable` / `category_average` |
| source_retailer       | TEXT     | yes  |          | "westelm.com", "amazon.com", etc. |
| source_url            | TEXT     | yes  |          | Full URL captured |
| source_captured_at    | DATETIME | yes  |          | When the price was captured |
| source_screenshot_path| TEXT     | yes  |          | Relative path under `./data/uploads/` |
| confirmed             | BOOLEAN  | no   | 0        | 0 = draft from Vision, 1 = specialist-confirmed |
| excluded              | BOOLEAN  | no   | 0        | 1 = specialist chose to exclude from the final report |
| notes                 | TEXT     | yes  |          | Internal notes about this item |
| created_at            | DATETIME | no   | UTC now  |
| updated_at            | DATETIME | no   | UTC now  |

**Indexes:**
- `(matter_id, line_number)` unique — prevents line-number collisions within a matter
- `(matter_id, confirmed, excluded)` — the most common filter in the Items tab
- `(matter_id, room_id)` — room grouping in the report
- `category_id` — for depreciation sanity checks and category-level totals

**Validation rules enforced at the ORM layer (not just in the UI):**

1. `rcv_unit_cents IS NOT NULL` implies all four source columns must be non-null: `source_retailer`, `source_url`, `source_captured_at`, `match_type`. This is the audit-trail constraint.
2. `acv_override_cents IS NOT NULL` implies `acv_override_reason` is non-empty.
3. `confirmed = 1` implies the item has a `category_id`, a `description`, and is ready to appear in a report.
4. `excluded = 1` items are never counted in report totals, but are listed in an "Excluded items" appendix for audit purposes.
5. `line_number` is assigned only when an item is first confirmed, and never reused within a matter.

**Why `rcv_total_cents` and `acv_total_cents` are stored, not computed at read time:** two reasons. First, every report view lists hundreds of rows, and recomputing on every page load is slow. Second, the stored value is an audit artifact — if the depreciation formula changes later, we need to know what the report said at the time it was delivered. The recompute-on-write model preserves history.

### `evidence_files`

Every file the specialist uploaded for a matter. Photos, videos, receipts, policy documents, prior inventories.

| Column         | Type     | Null | Default | Notes |
|:---------------|:---------|:-----|:--------|:------|
| id             | TEXT     | no   |         | UUID string |
| matter_id      | TEXT     | no   |         | FK → matters.id, ON DELETE CASCADE |
| filename       | TEXT     | no   |         | Original filename from the upload |
| stored_path    | TEXT     | no   |         | Relative path under `./data/uploads/` |
| mime_type      | TEXT     | no   |         | "image/jpeg", "video/mp4", "application/pdf" |
| size_bytes     | INTEGER  | no   |         | File size |
| kind           | TEXT     | no   |         | Enum: `photo` / `video` / `receipt` / `statement` / `policy_doc` / `other` |
| scanned        | BOOLEAN  | no   | 0       | Whether Vision has processed this file |
| sha256         | TEXT     | yes  |         | For dedup within a matter |
| created_at     | DATETIME | no   | UTC now |
| updated_at     | DATETIME | no   | UTC now |

**Indexes:** `(matter_id, kind)`, `(matter_id, scanned)`.

**Storage layout on disk:** files land under `./data/uploads/<matter_id>/<uuid>.<ext>`. The `stored_path` column holds the relative path from the `data/` root so the whole tree is portable (you can tar `./data/` and move it to a new machine without rewriting paths).

**Dedup:** when a specialist uploads the same photo twice, the second upload is detected by SHA-256 and the existing record is returned instead of creating a duplicate. This is enforced at the service layer, not by a database constraint.

### `vision_runs`

Every invocation of the Vision scan. Kept for debugging, cost tracking, and later analytics on prompt effectiveness.

| Column            | Type     | Null | Default | Notes |
|:------------------|:---------|:-----|:--------|:------|
| id                | TEXT     | no   |         | UUID string |
| matter_id         | TEXT     | no   |         | FK → matters.id, ON DELETE CASCADE |
| evidence_file_id  | TEXT     | no   |         | FK → evidence_files.id, ON DELETE CASCADE |
| model             | TEXT     | no   |         | "claude-opus-4-6", etc. |
| prompt_version    | TEXT     | no   |         | Version string for the prompt used |
| raw_response      | TEXT     | yes  |         | Full JSON response for later debugging |
| items_created     | INTEGER  | no   | 0       | Count of draft items generated |
| input_tokens      | INTEGER  | yes  |         | For cost tracking |
| output_tokens     | INTEGER  | yes  |         | For cost tracking |
| ran_at            | DATETIME | no   | UTC now |
| error             | TEXT     | yes  |         | Non-null if the run failed |

**Indexes:** `matter_id`, `evidence_file_id`, `ran_at DESC`.

**Why we keep the raw response:** when a specialist confirms an item and the carrier later challenges the pricing, we need to be able to show exactly what Vision returned on a given date for a given image. This is part of the audit trail, not optional.

### `exports`

One row per generated export file (PDF or CSV). Tracks what's been produced for a matter and when.

| Column        | Type     | Null | Default | Notes |
|:--------------|:---------|:-----|:--------|:------|
| id            | TEXT     | no   |         | UUID string |
| matter_id     | TEXT     | no   |         | FK → matters.id, ON DELETE CASCADE |
| format        | TEXT     | no   |         | Enum: `pdf` / `csv_xactimate` |
| file_path     | TEXT     | no   |         | Absolute path to the generated file |
| items_count   | INTEGER  | no   |         | Confirmed non-excluded items at time of export |
| rcv_total_cents | INTEGER| no   |         | Snapshot of the grand total at export time |
| acv_total_cents | INTEGER| no   |         | Snapshot of the grand total at export time |
| generated_at  | DATETIME | no   | UTC now |

**Indexes:** `(matter_id, format, generated_at DESC)` for "show me the latest PDF for this matter."

**Snapshotting totals in the row:** this is intentional. If a specialist exports a PDF, then edits items, the old export row still shows what the report said when it was sent. Historical integrity again.

---

## SQLite-specific configuration

The database needs a few PRAGMAs set at startup via a SQLAlchemy event listener:

```python
@event.listens_for(Engine, "connect")
def set_sqlite_pragmas(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")          # concurrent reads during writes
    cursor.execute("PRAGMA foreign_keys=ON")           # FK enforcement (off by default!)
    cursor.execute("PRAGMA synchronous=NORMAL")        # good balance for WAL mode
    cursor.execute("PRAGMA busy_timeout=5000")         # wait 5s instead of failing immediately
    cursor.close()
```

**Foreign keys are OFF in SQLite by default.** If you forget the `PRAGMA foreign_keys=ON` at connection time, cascades and constraints silently do nothing. This has bitten every person who's built a SQLite app. The pragma must be set on every connection.

---

## Migration policy

1. Every schema change requires a new Alembic revision. Generate with:
   ```bash
   uv run alembic revision --autogenerate -m "short descriptive message"
   ```
2. **Review auto-generated migrations before applying them.** Alembic's autogen is good, not perfect. It will miss index renames, enum additions, and constraint changes. Hand-edit the generated file.
3. Apply migrations with `uv run alembic upgrade head`. Test with a scratch database first.
4. Never edit a migration that has already been applied to the shared database (even if that database is only on the founder's laptop — consider it shared).
5. Write a downgrade path for every migration, even if it's just `pass`. This forces you to think about reversibility.
6. When you add a column that's non-nullable with no sensible default, add it in two steps: first a migration that adds the column as nullable, second a migration that backfills and makes it non-nullable.

---

## Migration history

| Revision | Date | Description |
|:---------|:-----|:------------|
| (initial)| [date] | Create `matters`, `rooms`, `categories`, `items`, `evidence_files`, `vision_runs`, `exports` |

Add a row to this table for every migration. A future operator reading this file in 18 months should be able to understand what changed and why.

---

## Open questions (track here, not in tickets)

- Should `categories` become user-editable in v1? Needed if a firm wants to add a category for "Rare musical instruments" or similar. For now, 42 is the answer.
- Do we need a `policyholders` table? Right now the policyholder name lives inline on the matter. If one policyholder ever has multiple matters (plausible for a family rebuilding in Palisades after a separate water loss), we might want to normalize. Not for v0.
- Do we need versioned `items` history (e.g., via a separate `item_revisions` table) for full auditability? Today, `updated_at` and the `exports` snapshot are enough. Revisit if a carrier formally requests a diff.
- Where do we store the methodology document used for a given matter? Today it's implicit in the report template. If methodology evolves, we need to version it and link a matter to the methodology that was in effect when the report was generated.
