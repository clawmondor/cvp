# Item "Needs review" flag — design

**Date:** 2026-07-29
**Branch:** cvp-legacy
**Status:** Approved for planning

## Problem

Specialists need a way to mark an item as "needs review" without dropping it
from the report. Today an item's state is expressed by two orthogonal booleans
on `Item` — `confirmed` and `excluded` — and only `confirmed and not excluded`
items flow into the PDF preview and the CSV / Xactimate exports. There is no way
to say "this item is good enough to keep in the report, but flag it for a second
look." Un-confirming would pull it from previews and exports, which is exactly
what we don't want.

## Goal

Add a third, independent boolean — `needs_review` — that a specialist can toggle
manually. It does **not** affect `confirmed`, so a flagged item keeps showing up
in previews and exports unchanged. The flag is an internal specialist worklist
aid; it never appears in client-facing output.

## Decisions (settled during brainstorming)

- **Who sets it:** manual toggle only. No Vision auto-flagging.
- **Export visibility:** internal only. No change to PDF, CSV, or the frozen
  Xactimate columns.
- **Shape:** plain on/off boolean. No reason column — the existing `notes`
  field covers "why" if a specialist wants to record it.
- **Filter:** add a "Needs review" option to the existing Items status filter.
- **Summary:** show a "Needs review: N" count in the items summary bar.
- **Visual:** an amber `⚑ review` pill in the row's status cell.

## Non-goals

- No change to `csv_export.py` or `pdf_generator.py` output.
- No Vision auto-flagging.
- No review-reason field.
- No change to the exclude/confirm semantics.

## Data model

Add one column to `Item` (`src/cvp/models.py`), alongside `confirmed` /
`excluded`:

```python
needs_review: Mapped[bool] = mapped_column(
    Boolean, default=False, nullable=False, server_default=text("0")
)
```

Fully orthogonal to `confirmed` and `excluded`. No relationship changes.

### Migration

New Alembic revision `add_needs_review_to_items`, following the
`20260723_b0fd3df9f4a6_retail_value_shipping` pattern: a single
`op.add_column("items", sa.Column("needs_review", sa.Boolean(), nullable=False,
server_default="0"))`. Existing rows default to `False`. Downgrade drops the
column.

## Toggle endpoint

New `POST /api/items/{item_id}/toggle-needs-review` in `routers/items.py`,
cloned from `toggle_exclude`:

- Same `require_matter_role("manager")` guard.
- Flips `item.needs_review`.
- Commits, refreshes, re-renders the row via `_item_row_html(...)`.
- Same `write_audit_log` background task (`action="item.update"`).

Manual only — nothing else sets the flag.

## UI

### Row status cell (`_item_row.html`)

Add a small button beside the existing ✓ / draft confirm toggle. HTMX-posts to
the new toggle endpoint, targeting `#item-row-{{ item.id }}` with
`hx-swap="outerHTML"` (same pattern as the confirm toggle).

- **Flagged:** amber pill — `bg-amber-100 text-amber-700 hover:bg-amber-200`,
  label `⚑ review`, title "Flagged for review — click to clear."
- **Not flagged:** muted outline — `bg-gray-100 text-gray-500
  hover:bg-gray-200`, label `flag`, title "Click to flag for review."

Amber matches the existing ACV-override star convention and stays visually
distinct from the green confirmed state, so an item reads clearly as *both*
confirmed and under review.

### Edit form (`_item_row_edit.html`)

Add a "Needs review" checkbox next to the existing "Confirmed" checkbox
(same `<label><input type="checkbox" name="needs_review" value="true">` markup).
`update_item` gains `needs_review: bool = Form(False)` and sets
`item.needs_review = needs_review`.

### Filter (`_items_controls.html` + `items.py`)

- Add `"needs_review"` to `_STATUS_VALUES`.
- Add a branch to `_apply_item_filters`: `Item.needs_review.is_(True)`.
- Add `("needs_review", "Needs review")` to the status `<option>` list.

### Summary (`_items_summary.html` + summary endpoint)

Add `needs_review_count` (count of `Item.needs_review` rows for the matter) to
the summary context and render "Needs review: N" in the summary bar. This is a
plain per-matter count of flagged items, independent of the confirmed/excluded
counts already shown.

## No JavaScript changes

Interactivity is pure HTMX attributes on the toggle button — no `app.js`
changes and no inline event handlers (CSP-safe).

## Testing

Router integration tests in `tests/` mirroring the existing items tests:

1. Toggle endpoint: flag on, then off; assert `needs_review` persists and the
   re-rendered row reflects state.
2. Filter: `status=needs_review` returns only flagged items.
3. Exports unaffected: a confirmed item that is also `needs_review` still appears
   in the CSV export (assert the flag does not change export membership).

Depreciation and export column formats are untouched, so no changes to those
test suites.

## Files touched

- `src/cvp/models.py` — new column
- `migrations/versions/<new>_add_needs_review_to_items.py` — migration
- `src/cvp/routers/items.py` — toggle endpoint, filter branch, `_STATUS_VALUES`,
  `update_item` form param, summary count
- `src/cvp/templates/_item_row.html` — amber pill toggle
- `src/cvp/templates/_item_row_edit.html` — checkbox
- `src/cvp/templates/_items_controls.html` — filter option
- `src/cvp/templates/_items_summary.html` — count
- `tests/` — toggle, filter, export-unaffected tests
