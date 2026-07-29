# Hover-to-Enlarge Crop Thumbnails (Items Tab)

**Date:** 2026-07-28
**Status:** Approved, ready for implementation
**Branch context:** `cvp-legacy`

## Problem

On the Items tab, each row shows a small 96×96 `object-contain` crop thumbnail
(`src/cvp/templates/_item_row.html`). Specialists want to see the crop at a
readable size without leaving the table. Clicking the thumbnail's "Edit crop"
overlay already opens the crop editor; that behavior must be preserved.

## Goal

Hovering the mouse over a crop thumbnail floats an enlarged copy of that same
crop image next to the thumbnail. It dismisses on mouseleave. The existing
click-to-open-editor path is untouched.

## Non-goals (YAGNI)

- No zoom/pan, no click-to-pin, no keyboard trigger.
- No showing the full original evidence image — just the crop, enlarged.
- No server, data-model, depreciation, or export changes.

## Design

### Template change — `src/cvp/templates/_item_row.html`

Add two data attributes to the existing thumbnail `<img>` (lines ~11–13):

- `data-crop-preview="/crops/<crop_path>{?v=<crop_updated_at>}"` — the full crop
  URL, using the same cache-busting `?v=` query the `src` already uses.
- `data-crop-preview-alt="{{ item.description }}"`.

No structural/markup changes beyond these attributes, so the live-items HTMX
row swaps (`_item_row.html` is re-rendered on scan/rescan/edit) keep working
with no extra wiring.

### JS change — `src/cvp/static/app.js`

Follow the existing delegated-listener + no-inline-JS convention (CSP has no
`unsafe-inline`; see the `data-toggle-crop-editor` block near line 351).

1. **Single floating element, lazily created.** One `<img id="crop-hover-preview">`
   appended to `<body>` on first use, styled:
   `position: fixed; pointer-events: none;` a `z-index` above the items table,
   `max-width`/`max-height` ~400px, `object-fit: contain`, white background,
   thin border, soft shadow, rounded corners, hidden by default
   (`display: none`). `pointer-events: none` guarantees it never intercepts
   clicks or hover, so the "Edit crop" button and its click handler are
   unaffected.

2. **Delegated `mouseover` listener.** If
   `e.target.closest('[data-crop-preview]')` matches:
   - Set the preview `src` from `data-crop-preview` and `alt` from
     `data-crop-preview-alt`.
   - Position with `getBoundingClientRect()` of the thumbnail: default to the
     **right** of the thumbnail with a small gap; if it would overflow the
     right viewport edge, flip to the **left**. Clamp the top so the preview
     stays fully on-screen vertically.
   - Show it (`display: block`).

3. **Delegated `mouseout` listener.** If leaving a `[data-crop-preview]`
   element (`e.target.closest('[data-crop-preview]')` truthy), hide the preview.

Because both listeners are document-level delegation, thumbnails inserted by
HTMX swaps (scan / region-rescan / row edit) get the behavior automatically.
`position: fixed` sidesteps `<td>`/`<table>` overflow clipping.

### Interaction with existing "Edit crop" overlay

The overlay button appears via `group-hover/thumb` at the bottom of the
thumbnail. Because the button is a child of the thumbnail div and the preview
is `pointer-events: none`, hovering toward the button keeps the pointer inside
the `[data-crop-preview]` element, so the preview stays visible and the button
click still fires `toggleCropEditor(...)`.

## Testing / verification

Client-side, visual-only change — no Python, data-model, or export impact, so
no unit tests. Verify by driving the app:

1. Open a matter's Items tab that has crops.
2. Hover a thumbnail → enlarged preview appears next to it, positioned within
   the viewport (including rows near the right edge and near the top/bottom).
3. Move mouse away → preview disappears.
4. Click "Edit crop" → crop editor still opens (regression check).
5. After a scan/rescan HTMX swap, hover a newly-inserted thumbnail → preview
   works (delegation check).
