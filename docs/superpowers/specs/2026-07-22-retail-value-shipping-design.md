# Retail value + shipping cost — design spec

**Date:** 2026-07-22
**Status:** Approved (pending spec review)
**Branches affected:** `main` (package `claimos`, domain `Claim`/`claim_id`) and `cvp-legacy` (package `cvp`, domain `Matter`/`matter_id`)

## Problem

Items currently store a single price in `rcv_unit_cents`, treated as the RCV
(replacement cost value). The stakeholder has clarified that **RCV includes
shipping costs**. RCV must therefore become a *computed* value:

```
RCV = retail value + shipping cost
```

We need to (1) introduce an explicit **retail value** field, (2) add a
**shipping cost** field, and (3) make RCV a derived quantity everywhere it
appears — across both the current ClaimOS codebase (`main`) and the frozen
legacy codebase (`cvp-legacy`) that still serves the existing internal
deployment.

## Decisions (locked)

1. **RCV is derived, not stored as a base.** `RCV = retail + shipping` in all
   cases.
2. **Shipping is part of RCV but passes through ACV undepreciated.** You cannot
   depreciate the cost of shipping a brand-new replacement item.
   - `rcv_total = retail_unit_cents × quantity + shipping_cents`
   - `acv_total = depreciate(retail_unit_cents, quantity, …) + shipping_cents`
3. **Shipping is a per-line total**, not per-unit. One `shipping_cents` value
   covers the whole line regardless of quantity.
4. **Field model:** rename the existing per-unit price column
   `rcv_unit_cents → retail_unit_cents` (it was always the retail unit price),
   and add `shipping_cents`. `rcv_total_cents` and `acv_total_cents` remain
   **stored-but-derived** columns, recomputed on every save (the existing
   denormalization pattern). "RCV" no longer names a stored base — only computed
   totals.
5. **Migration preserves data via rename-in-place.**
   `ALTER TABLE items RENAME COLUMN rcv_unit_cents TO retail_unit_cents`
   preserves every existing value automatically (the column is the same column
   with a new name — nothing is copied or lost). Then add `shipping_cents` with
   `server_default="0"` so existing rows backfill to zero.
6. **Xactimate CSV headers stay locked** (immutable rule — carriers match exact
   columns). Shipping surfaces in the CSV only via the existing `Notes` field.
7. **Override edge case:** when `acv_override_cents` is set it remains the
   absolute final ACV — shipping is **not** added on top of an override.
   `rcv_total` still includes shipping regardless of any override.

## Currency & source rules (unchanged, still enforced)

- Integer cents everywhere; format to dollars only at display/export (rule #1).
- Shipping requires **no new source fields** — it rides on the item's existing
  `source_url`/`source_retailer`/`source_captured_at`/`match_type`, so the audit
  trail (rule #2) is intact. `shipping_cents` defaults to `0`; an item with no
  shipping is valid.
- ACV stays computed by `depreciation.py` (rule #3); the shipping term is added
  inside that module so the formula remains the single source of truth.

## Changes by layer (`main`; mirror on `cvp-legacy` with `cvp`/`Matter` naming)

### Data model — `src/claimos/models.py`
- Rename `Item.rcv_unit_cents` → `Item.retail_unit_cents` (Integer, default 0).
- Add `Item.shipping_cents: Mapped[int]` (Integer, `default=0`,
  `nullable=False`, `server_default="0"`).
- Keep `rcv_total_cents` and `acv_total_cents` as stored derived columns.

### Migration — new Alembic revision
```python
op.alter_column("items", "rcv_unit_cents", new_column_name="retail_unit_cents")
op.add_column("items", sa.Column(
    "shipping_cents", sa.Integer(), nullable=False, server_default="0"))
```
Downgrade reverses both. Verify the rename works under SQLite batch mode
(local dev) and Postgres (prod). Both branches get their own revision on top of
their own current head.

### Depreciation — `src/claimos/depreciation.py`
- `compute_acv(...)` gains `shipping_cents: int = 0`.
- Shipping is added **after** depreciation and is **not** depreciated.
- If `acv_override_cents` is set, return it as-is (shipping not added).

```python
def compute_acv(retail_unit_cents, quantity, age_years, useful_life_years,
                acv_floor_pct, condition, acv_override_cents=None,
                shipping_cents=0) -> int:
    if acv_override_cents is not None:
        return acv_override_cents          # absolute; shipping not added
    # ... existing depreciation of retail_unit_cents ...
    depreciated = acv_unit * quantity
    return depreciated + shipping_cents
```
(The first positional param is renamed `rcv_unit_cents → retail_unit_cents` for
clarity; it is the retail unit price.)

### Save paths — recompute totals wherever items are written
`routers/items.py`, `routers/serp.py` (and any other write site) must set:
```python
item.rcv_total_cents = item.retail_unit_cents * item.quantity + item.shipping_cents
item.acv_total_cents = compute_acv(
    retail_unit_cents=item.retail_unit_cents,
    quantity=item.quantity,
    ...,
    acv_override_cents=item.acv_override_cents,
    shipping_cents=item.shipping_cents,
)
```
- Form param `rcv_unit_dollars → retail_unit_dollars`; add `shipping_dollars`
  (parsed to cents via the existing `_parse_cents` helper).
- `services/vision.py` creates items with `retail_unit_cents=0`,
  `shipping_cents=0`, `rcv_total_cents=0`, `acv_total_cents=0` (unchanged zeros,
  renamed field).

### Rollups — no logic change
`routers/items.py` summary, `routers/claims.py` grand/room totals, and
`services/pdf_generator.py` already sum `rcv_total_cents` / `acv_total_cents`,
which now include shipping automatically. The only edits here are field renames
if any reference `rcv_unit_cents` directly (e.g. the `missing_price_count`
check → `retail_unit_cents == 0`).

### CSV export — `src/claimos/services/csv_export.py`
- **Headers unchanged.** `UnitPrice` = retail unit (`retail_unit_cents`),
  `Total` = `rcv_total_cents` (now includes shipping), `ACV` =
  `acv_total_cents` (includes shipping).
- Append `Shipping: $X.XX` to the existing `Notes` join when `shipping_cents > 0`
  so shipping stays auditable without touching the locked header set.

### PDF report — `src/claimos/templates/report/pdf.html` (+ `preview.html`)
- Add a dedicated, itemized **Shipping** column to the item table (no format
  constraint on the PDF). Show retail unit, shipping, computed RCV total, ACV.

### UI templates
- `_item_row_edit.html`: rename the price input to **Retail (unit)**
  (`retail_unit_dollars`), add a **Shipping (line)** input (`shipping_dollars`).
- `_item_row.html`, `_items_summary.html`, `_tab_items.html`,
  `_tab_overview.html`, `_serp_result.html`: display Retail, Shipping, and
  computed RCV/ACV; update any `rcv_unit_cents` references to `retail_unit_cents`.

### Legacy-cutover safety — `src/claimos/migrate_db.py` (`main` only)
`migrate-db` copies the legacy CVP `items` table via `SELECT *` and a rename map,
with a guard that raises if a source column has no target counterpart. To keep
cutover robust regardless of whether the `cvp-legacy` DB has been migrated yet,
add a rename entry to the `items` plan:
```python
("items", "items", {"matter_id": "claim_id", "rcv_unit_cents": "retail_unit_cents"}),
```
- If the legacy DB is **post-rename**, its column is already `retail_unit_cents`;
  the rename entry is a harmless no-op (source key `rcv_unit_cents` absent).
- If the legacy DB is **pre-rename**, `rcv_unit_cents` is remapped correctly.
- `shipping_cents` absent on the legacy side is fine — INSERT omits it and the
  target's `server_default="0"` applies.
Confirm `tests/test_migrate_db.py` invariants (TABLE_PLAN ↔ ORM metadata) still
pass; adding a column rename does not change table coverage.

## Tests

- `tests/test_depreciation.py`: add cases for the shipping term (shipping added
  undepreciated to ACV), the per-line semantics, and the override edge case
  (override returns as-is, shipping not added). Rename first-arg usages.
- `tests/test_csv_export.py`: assert headers are unchanged and `Notes` carries
  `Shipping: $X.XX` when shipping > 0; `Total`/`ACV` reflect shipping.
- Rename `rcv_unit_cents`/`rcv_unit_dollars` references across:
  `test_items_summary.py`, `test_items_pagination.py`, `test_items_template.py`,
  `test_item_approval.py`, `test_items_group_assignment.py`,
  `test_evidence_cleanup.py`.
- Add a small integration assertion that a saved item with retail + shipping
  yields `rcv_total = retail×qty + shipping` and correct ACV.

## Out of scope

- No new Xactimate CSV column (locked-header rule).
- No per-unit shipping.
- No shipping-specific source fields.
- No visual rebrand / new tokens.

## Execution — two branches, two PRs

1. **`main`** (this branch, `feat/retail-value-shipping`): implement all layers
   above with `claimos`/`Claim`/`claim_id` naming, including the `migrate_db.py`
   safety-net rename. Run `uv run ruff format .` + `--check`, `uv run pytest`.
2. **`cvp-legacy`**: branch off `origin/cvp-legacy`; mirror the same logic with
   `cvp`/`Matter`/`matter_id` naming. No `migrate_db.py` change there (legacy is
   the source, not the target). Its Alembic revision stacks on the cvp-legacy
   head.

Each branch is validated (format, lint, tests) independently before merge.
