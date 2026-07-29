# Items table: row-click edit, close icon, and narrower layout

**Date:** 2026-07-29
**Branch:** `items-row-click-edit` (off `cvp-legacy`)
**Scope:** Items table UI in the legacy CVP app (`src/cvp`). No data-model, router, or endpoint changes.

## Goal

Three usability fixes to the per-matter Items table:

1. Clicking anywhere on an item row opens that item's inline editor (no separate "Edit" link).
2. In the expanded editor, replace the "Cancel" button with an ✕ close-icon button in the
   top-left corner of the expanded section.
3. Reduce the table's width so specialists no longer have to scroll right to see a full row.

## Files touched

- `src/cvp/templates/_item_row.html` — read-only row
- `src/cvp/templates/_item_row_edit.html` — expanded editor row
- `src/cvp/templates/_items_head.html` — column headers
- `src/cvp/templates/_items_region.html` — table wrapper (empty-state colspan)
- `src/cvp/templates/_items_rows_fragment.html` — "Loading…" row colspan
- `src/cvp/templates/_items_tbody.html` — empty-state row colspan
- `src/cvp/static/app.js` — delegated row-click listener

No changes to `src/cvp/routers/items.py`. The existing `GET /api/items/{id}/edit` and
`GET /api/items/{id}/view` endpoints are reused as-is.

## 1. Row click opens the editor

- Add `data-item-edit-url="/api/items/{{ item.id }}/edit"` and `cursor-pointer` to the read-only
  `<tr id="item-row-{{ item.id }}">` in `_item_row.html`.
- Remove the **Edit** button from the Actions cell. Keep the **Del** button unchanged.
- New delegated click listener in `app.js` (following the existing `data-*` delegated pattern):

  ```js
  document.addEventListener('click', function (e) {
      if (e.target.closest('a, button, input, select, textarea, label, summary')) return;
      var row = e.target.closest('tr[data-item-edit-url]');
      if (!row) return;
      htmx.ajax('GET', row.dataset.itemEditUrl, { target: '#' + row.id, swap: 'outerHTML' });
  });
  ```

  The interactive-element guard preserves every existing control on the row: the crop
  "Edit crop" button, the retailer search links (`<a>`), the Comments button, the confirm-toggle
  button, and the Del button. Clicking the crop thumbnail image or any plain cell text opens the
  editor. No inline JS handlers (CSP-safe).

## 2. Close icon replaces Cancel

In `_item_row_edit.html`:

- Remove the **Cancel** button (the `hx-get=".../view"` button in the numeric-fields row).
  The **Save** button becomes full-width in its cell.
- Add an ✕ icon button as the **first element inside the expanded `<td>`**, before the `<form>`,
  so it is visually top-left and never submits the form. It reuses the same view endpoint:

  ```html
  <button type="button"
          hx-get="/api/items/{{ item.id }}/view"
          hx-target="#item-row-{{ item.id }}"
          hx-swap="outerHTML"
          aria-label="Close editor"
          class="mb-2 rounded p-1 text-gray-400 hover:bg-gray-200 hover:text-gray-600">
    <svg class="h-4 w-4" ... X-icon path ...></svg>
  </button>
  ```

## 3. Narrow the table

- **Remove the Age and Cond columns** — both the header cells in `_items_head.html` (drop the
  `("Age", ...)` and `("Cond", ...)` entries from the `cols` list) and the corresponding `<td>`s
  in `_item_row.html`. These fields stay editable in the expanded editor.
- **Compress the Category column** — cap its cell width and truncate with a full-name tooltip:
  change the Category `<td>` to `max-w-[7rem] truncate` and add `title="{{ category name }}"`.
  (The header stays but no longer forces `whitespace-nowrap` width.)
- Column count drops 13 → 11. Update **all four** `colspan="13"` to `colspan="11"`:
  - `_item_row_edit.html` (the expanded `<td>`)
  - `_items_region.html` (the empty-state row)
  - `_items_rows_fragment.html` (the "Loading…" row)
  - `_items_tbody.html` (the empty-state row)
- Keep `overflow-x-auto` on the table container as a safety fallback for very small viewports.

## Out of scope

- No changes to sorting/filtering behavior (the removed Age/Cond columns simply lose their
  sort headers; their sort keys are never emitted, so no dead links).
- No changes to CSV export or the report templates.
- No delete-inside-editor (Del stays on the row).

## Verification

Drive the real page (matter items tab):

1. Click a row body → editor expands. Click the crop "Edit crop", a retailer link, Comments,
   confirm toggle, and Del → each does its own thing, editor does **not** open.
2. In the editor, the ✕ (top-left) collapses back to the read-only row; there is no Cancel button.
3. The table shows no Age/Cond columns, Category is truncated with a tooltip, and a typical
   row fits without horizontal scrolling on a standard laptop width.
4. `uv run pytest` and `uv run ruff format --check .` pass.
