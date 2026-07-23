# Correction: ACV excludes shipping — design spec

**Date:** 2026-07-22
**Status:** Approved (pending confirmation)
**Supersedes:** the ACV treatment in `2026-07-22-retail-value-shipping-design.md`
**Branches:** `main` (ClaimOS, off `origin/main` @ `cc7f88c` — PR #47 merged) and `cvp-legacy` (CVP, off `origin/cvp-legacy` @ `662780a` — PR #48 merged). Both old PRs squash-merged; this ships as **new** PRs on both.

## What changed

The shipping feature shipped with **ACV = depreciate(retail) + shipping** (shipping passed through to ACV undepreciated). That is wrong: **ACV must not account for shipping at all.** RCV still includes shipping (the stakeholder requirement stands).

## Corrected model

Let `retail_rcv = retail_unit_cents × quantity` (the depreciable base — RCV of the item, excluding shipping).

| Quantity | Formula | Change |
|---|---|---|
| `rcv_total_cents` | `retail_rcv + shipping_cents` | unchanged — RCV includes shipping |
| `acv_total_cents` | `compute_acv(retail…)` — depreciated retail **only** | **shipping removed** |
| depreciation | `retail_rcv − acv_total_cents` | **was `rcv_total − acv`**; now excludes shipping |
| shipping | `shipping_cents` | shown as its own reconciling total |

**Reconciliation, everywhere:** `RCV = ACV + Depreciation + Shipping`
(check: `acv + (retail_rcv − acv) + shipping = retail_rcv + shipping = rcv_total` ✓; holds under `acv_override_cents` too).

## Changes by layer (`main`; mirror on `cvp-legacy` with `cvp`/`Matter` naming)

### `depreciation.py`
Remove the `shipping_cents` parameter and both `+ shipping_cents` terms from `compute_acv`. It returns depreciated retail only. `acv_override_cents` still short-circuits as the absolute ACV.

### Save paths
- `routers/items.py` `_compute_and_set_totals`: `rcv_total_cents = retail_unit_cents * quantity + shipping_cents` (unchanged); `acv_total_cents = compute_acv(…)` **without** `shipping_cents`.
- `routers/serp.py`: same — drop `shipping_cents=` from its `compute_acv` call; `rcv_total` unchanged.

### Depreciation math — every display site switches to `retail_rcv − acv`
- **`services/csv_export.py`**: `dep_cents = (item.retail_unit_cents * item.quantity) - item.acv_total_cents` (was `rcv_total − acv`). `Total` column stays `rcv_total_cents` (RCV incl shipping); `ACV` stays `acv_total_cents`; `Shipping: $X.XX` stays in `Notes`.
- **`services/pdf_generator.py`**: rollups additionally accumulate `total_shipping_cents` and `total_retail_rcv_cents` (and per-room). Grand/room depreciation = `retail_rcv − acv`. Expose `total_shipping_cents` (+ per-room shipping) for the templates.
- **`routers/claims.py`**: any depreciation rollup it computes aligns to `retail_rcv − acv`; expose shipping total where RCV/ACV summaries are shown.
- **`templates/report/pdf.html` + `preview.html`**:
  - Blended-depreciation figure and %, room-summary `Depreciation` column, and grand-total `Depreciation` → all use `retail_rcv − acv` (never `rcv_total − acv`).
  - Add a **Shipping** total to the room-summary table and grand totals so `RCV = ACV + Depreciation + Shipping` is visible and reconciles. (The per-line-items table already has a Shipping column.)
  - Methodology box: `acv_total = acv_unit × quantity` (drop `+ shipping`); keep `rcv_total = retail_unit × quantity + shipping`; add `depreciation = retail_unit × quantity − acv_total` and a neutral sentence: "Shipping is part of RCV but is excluded from ACV and from depreciation; it is shown separately (RCV = ACV + Depreciation + Shipping)." Remove the old "passes through to ACV in full" wording.

### Xactimate CSV reconciliation note (accepted consequence)
Headers stay frozen (no `Shipping` column). Because `Total` now includes shipping while `ACV` and `Depreciation` exclude it, the three columns no longer self-sum: `Total − ACV − Depreciation = Shipping`, and shipping is documented in `Notes`. This is the direct, intended consequence of "RCV includes shipping; ACV/Depreciation exclude it; headers frozen."

## Tests
- `test_depreciation.py`: remove the three shipping-in-ACV tests (`test_shipping_added_undepreciated`, `test_shipping_is_per_line_not_per_unit`, `test_override_ignores_shipping`); `compute_acv` no longer takes `shipping_cents`. Add one test asserting ACV = depreciated retail with no shipping influence (the signature no longer accepts shipping).
- `test_csv_export.py`: `Depreciation` column now excludes shipping (retail depreciation only); `Shipping: $X.XX` still in `Notes`; assert `Total − ACV − Depreciation == shipping` for a shipped item.
- Items add-route integration test: keep `retail_unit_cents == 10000`, `shipping_cents == 2000`, `rcv_total_cents == 32000`; **add** `acv_total_cents` assertion proving shipping is excluded from ACV.
- Any other test asserting an ACV that previously bundled shipping → update to the retail-only value.

## Out of scope
- No change to `rcv_total_cents` (RCV still includes shipping).
- No new CSV columns (frozen headers).
- No new per-unit shipping, no new source fields.
- Read-only items-list shipping breakout remains backlog (unchanged).

## Execution
New branch per line: `fix/acv-exclude-shipping` off `origin/main`, then a `cvp-legacy` mirror off `origin/cvp-legacy` (no `main` history — isolation guard). Each validated (ruff + full suite) independently; two new PRs.
