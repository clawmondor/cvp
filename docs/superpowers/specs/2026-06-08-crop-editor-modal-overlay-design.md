# Crop Editor Modal Overlay — Design

**Date:** 2026-06-08
**Status:** Approved by user; ready for implementation plan
**Scope:** UI refactor — no schema, no route changes, no new server logic

## Problem

Today the crop editor on the Evidence tab loads as a sibling of `#evidence-grid` (HTMX `swap: 'afterend'`), so it appears *below* the image grid. A specialist editing crops on the 15th image must scroll back down to reach the 16th when finished. The "Edit crop" link on the Items tab forces the user into a new browser tab pointed at `?file=...&crop=...#evidence`, losing their place in the items list and breaking the flow.

Two changes are wanted:

1. **Move the crop editor above the image list on the Evidence tab** — so the user's scroll position in the grid is preserved while editing.
2. **When "Edit crops" is clicked on an image, any previously open crop editor is closed** — only one editor open at a time.

A literal "move it above the grid" satisfies #1 but still requires scrolling past the editor each time it opens, and it does nothing for the Items tab. Promoting the editor to a **viewport-level modal** mounted once at the page root satisfies both requirements structurally, makes the close-previous rule automatic, and unlocks an in-place "Edit crop" experience from the Items tab.

## Goals

- The crop editor opens as a centered modal overlaying whichever tab the user is on.
- Closing the modal returns the user to their exact prior scroll position and tab state.
- "Edit crop" on the Items tab opens the modal in-place — no new tab, no tab switch.
- The legacy deep-link `/matters/<id>?file=X&crop=Y#evidence` continues to work (lands on Evidence tab, opens the modal).
- Only one crop editor open at a time, enforced structurally by the modal root + backdrop.

## Non-goals

- No URL syncing while the modal is open (no `?file=&crop=` query string write on open, no clear on close). Sharing a live-editor state via URL is deferred.
- No backdrop-click-to-close. Canvas drags going outside the dialog would mis-fire as close events.
- No keyboard navigation between crop boxes beyond what exists today.
- No server-side changes to the `GET /api/evidence/<file_id>/crop-editor` route handler or to the `POST .../recrop` flow.
- No schema, migration, or model changes.

## Architecture

**Single viewport-level mount point.** A new `<div id="crop-editor-modal-root">` is added to `base.html` immediately before `</body>`, initially empty. Every trigger that previously opened the crop editor now issues the same HTMX request into this root.

**Modal shell lives inside the partial.** The existing `_crop_editor.html` partial is rewritten so its outermost element is a fixed-position backdrop (`fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4`) wrapping a centered dialog card (`relative max-w-5xl w-full max-h-[90vh] overflow-auto bg-white rounded-lg shadow-xl p-4`). The existing header, canvas, sidebar, ✕ button, status line, and inline `<script type="application/json">` payload sit inside the dialog card unchanged.

**One HTMX target.** Every trigger ("Edit crops" button on the Evidence grid, "Edit crop" button on the Items table thumbnail, the legacy `?file=&crop=` deep-link auto-open) routes through the existing delegated `data-toggle-crop-editor` click handler in `src/cvp/static/app.js`, which calls `htmx.ajax('GET', '/api/evidence/<file_id>/crop-editor', { target: '#crop-editor-modal-root', swap: 'innerHTML' })`. Templates do not use `hx-get` attributes for this — the handler is the single place the request is issued.

**Close clears the root.** ✕ and Esc both set `#crop-editor-modal-root.innerHTML = ''`. No HTMX request is issued. The backdrop, dialog, and canvas state are all destroyed in one step.

**Why this works for the cross-tab goal:** the modal lives outside any tab's DOM. Opening it from the Items tab does not touch the Items tbody, its scroll position, its sort, or its filter. Closing it does not either. The same is true for Evidence and any future tab.

## Components

### Templates

**`src/cvp/templates/base.html`** — add `<div id="crop-editor-modal-root"></div>` immediately before `</body>`. No other changes.

**`src/cvp/templates/_crop_editor.html`** — wrap the existing root `<div id="crop-editor-{{ evidence_file.id }}" data-init="crop-editor" ...>` in two new outer elements:

- A backdrop `<div class="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4">`.
- Inside it, a dialog `<div class="relative max-w-5xl w-full max-h-[90vh] overflow-auto bg-white rounded-lg shadow-xl p-4">`.

Remove the existing `mt-4 rounded-lg border border-gray-200 bg-white p-4 shadow-sm` classes from the inner `crop-editor-<id>` div — the dialog wrapper provides the card chrome now. The inner div keeps its `id`, `data-init`, and `data-ef-id` / `data-img-w` / `data-img-h` / `data-img-src` attributes (consumed by `crop-editor.js`).

The ✕ button (`data-crop-editor-close="<id>"`) is kept for backward compatibility of markup but its handler behavior changes (see JS).

The inline `<script type="application/json" id="crop-data-<id>">{{ crops_json | tojson }}</script>` block stays exactly as is.

**`src/cvp/templates/_evidence_grid.html`** — markup unchanged. The existing `<button data-toggle-crop-editor="{{ f.id }}">Edit crops</button>` (around line 25) keeps working because `data-toggle-crop-editor` is already wired through the delegated handler.

**`src/cvp/templates/_item_row.html`** — replace the `<a href="/matters/{{ item.matter_id }}?file={{ item.crops[0].evidence_file_id }}&crop={{ item.crops[0].id }}#evidence" target="_blank" ...>Edit crop</a>` (lines 14-22) with:

```jinja
<button type="button"
        data-toggle-crop-editor="{{ item.crops[0].evidence_file_id }}"
        data-preselect-crop="{{ item.crops[0].id }}"
        aria-label="Edit crop for {{ item.description }}"
        class="absolute inset-x-0 bottom-0 flex items-center justify-center py-1
               bg-black/50 opacity-0 group-hover/thumb:opacity-100
               transition-opacity rounded-b text-white text-xs font-medium">
  Edit crop
</button>
```

The visual appearance and hover behavior are preserved; only the element type, attributes, and lack of `target="_blank"` change.

### JavaScript

**`src/cvp/static/app.js`**

- `toggleCropEditor(fileId, opts)` — change the HTMX target from `#evidence-grid` with `swap: 'afterend'` to `#crop-editor-modal-root` with `swap: 'innerHTML'`. The "if existing then remove" branch is replaced by "if root has children then return early" (re-entrancy guard). Accept an optional `preselectCropId` argument; when provided, set `document.getElementById('crop-editor-modal-root').dataset.preselectCrop = preselectCropId` before the request.
- Delegated click handler at app.js:243-275 — read `data-preselect-crop` off the clicked button if present, pass to `toggleCropEditor` as `preselectCropId`.
- New keydown listener on `document` — if `key === 'Escape'` and `#crop-editor-modal-root` has at least one child element and `e.target` is not an `INPUT`/`TEXTAREA`/`SELECT`, clear the root and remove the body scroll-lock class.
- Body scroll lock — when `toggleCropEditor` actually issues an open, add `document.body.classList.add('overflow-hidden')`. When the root is cleared (either path), remove the class.
- DOMContentLoaded deep-link block (app.js:130-150) — unchanged in spirit. Continue to read `?file=&crop=` from the URL, but route through the updated `toggleCropEditor(fileId, { preselectCropId: cropId })` instead of the old two-step "open then probe `ceSelect_*`" pattern. The post-init preselect logic moves into `crop-editor.js` (see below).

**`src/cvp/static/crop-editor.js`**

- The `data-crop-editor-close` click handler at lines 4-9 — replace "remove the editor container" with "clear `#crop-editor-modal-root.innerHTML` and remove `document.body.overflow-hidden`."
- The `htmx:afterSettle` initializer at lines 12-17 — after calling `initCropEditor(container)`, check `document.getElementById('crop-editor-modal-root').dataset.preselectCrop`. If set, call `window['ceSelect_' + EF_ID.replace(/-/g, '_')](cropId)` (the existing per-instance selector exposed by the editor IIFE) and delete the dataset attribute. This consolidates the preselect logic — both the Items tab click and the legacy deep-link path use it.

### Backend

No changes. The route `GET /api/evidence/<file_id>/crop-editor` returns the same partial; only the partial's outer markup is different. The `POST .../recrop` endpoint and its response handling are untouched.

## Data flow

**Open from Evidence tab grid card**

1. User clicks `[data-toggle-crop-editor="<file_id>"]`.
2. Delegated handler calls `toggleCropEditor(fileId)`. Root is empty → handler proceeds.
3. `htmx.ajax('GET', '/api/evidence/<file_id>/crop-editor', { target: '#crop-editor-modal-root', swap: 'innerHTML' })` fires.
4. Server returns `_crop_editor.html` (backdrop + dialog + canvas markup + inline JSON).
5. HTMX swaps it in. `htmx:afterSettle` fires.
6. `crop-editor.js` initializer matches `[data-init="crop-editor"]:not([data-ready])`, marks `data-ready=1`, runs `initCropEditor(container)`.
7. Canvas sized, image loaded, boxes drawn. Body scroll lock active.

**Open from Items tab thumbnail**

1. User clicks `[data-toggle-crop-editor="<file_id>" data-preselect-crop="<crop_id>"]`.
2. Delegated handler reads `data-preselect-crop`, sets `#crop-editor-modal-root.dataset.preselectCrop = "<crop_id>"`, then calls `toggleCropEditor(fileId)`.
3. Steps 3-7 as above.
4. After `initCropEditor` completes, the post-init block in `crop-editor.js` reads `dataset.preselectCrop`, calls `window['ceSelect_<file_id>'](cropId)`, and clears the attribute. The named crop is now selected in the editor.

**Close (✕ button or Esc keypress)**

1. Handler clears `#crop-editor-modal-root.innerHTML` and removes `document.body.classList.remove('overflow-hidden')`.
2. No HTMX request.
3. The user is on the same tab, at the same scroll position, with the same selection/filter state — none of that was touched.

**Legacy deep-link `/matters/<id>?file=X&crop=Y#evidence`**

1. Page loads on Evidence tab via the existing hash routing.
2. `DOMContentLoaded` block reads query params, calls `toggleCropEditor(fileId, { preselectCropId: cropId })`.
3. Same flow as the Items tab open. URL is left unchanged (no `history.replaceState` calls).

**Concurrent-open invariant**

Because the modal root holds at most one editor's innerHTML at a time and the backdrop is `z-50` covering the full viewport (intercepting pointer events from anything underneath), there is no UI path to two editors being open simultaneously. The re-entrancy guard in `toggleCropEditor` (early return if root has children) covers the rare case of an in-flight HTMX request being followed by another click via keyboard or programmatic dispatch.

## Error handling and edge cases

**Route errors.** If `GET /api/evidence/<file_id>/crop-editor` returns a non-200 or an error template, HTMX swaps that body into the root, resulting in a stuck non-closeable overlay. The implementation must verify the route returns either a valid editor partial *or* an empty 200 with no children — in the latter case, no modal is shown. Existing inline behavior should already handle 404 gracefully; verify on the modal path.

**Image load failure.** If `bgImg.onerror` fires inside `crop-editor.js`, the canvas remains blank — same behavior as today. Out of scope for this change.

**Esc while focused on a future input.** The sidebar has no text inputs today, but adding the `INPUT`/`TEXTAREA`/`SELECT` guard now is cheap insurance.

**HTMX swaps elsewhere while modal is open.** The Items tab tbody re-renders, the Evidence grid re-renders after a re-crop, etc. The modal is mounted in `base.html` outside any tab DOM, so these swaps cannot touch it. Verified structurally.

**Body scroll lock.** Adding `overflow-hidden` on `<body>` prevents the page behind from scrolling while the modal is open. Removed on every close path.

**Re-entrancy.** Two rapid clicks on different "Edit crop" buttons must not stack two HTMX requests into the same root. The early-return guard in `toggleCropEditor` (root has children → bail) covers the post-load case. For the in-flight case, set `#crop-editor-modal-root.dataset.loading = '1'` immediately before `htmx.ajax`, clear it in an `htmx:afterSettle` listener on the root, and check both conditions in the guard.

**Tall images on short viewports.** The dialog uses `max-h-[90vh] overflow-auto`, so canvas + sidebar scroll inside the dialog if needed. The canvas already caps width at `MAX_W = 600` in `crop-editor.js`.

## Testing

This is a UI refactor with no new server logic, no schema, and no migrations. Coverage is mostly manual plus one light integration assertion.

**Existing tests.** Any test that hits `GET /api/evidence/<file_id>/crop-editor` will continue to pass — the response remains valid HTML for the editor. The outer markup is different (now wrapped in backdrop + dialog), so any assertion that pinned exact outer-element classes will need updating. None is expected, but verify.

**New integration assertion.** A single test that fetches the route and asserts the response body contains both the new modal shell (`fixed inset-0 z-50 bg-black/50`) and the existing inner div (`data-init="crop-editor"`). One assertion each. Mock the file lookup as needed.

**Manual checklist.** To be run before merging:

- Open editor from an Evidence grid card → modal appears, image and boxes render.
- Press Esc → modal closes, page scroll position preserved.
- Click ✕ → modal closes.
- Click Edit crop on an Items table row → modal opens on Items tab with the correct crop preselected. Close → Items table scroll/sort/filter preserved.
- Re-crop a box → existing POST flow succeeds, grid behind refreshes as it does today.
- Open editor, then visit legacy URL `/matters/<id>?file=X&crop=Y#evidence` in a fresh tab → lands on Evidence tab, modal opens, correct crop preselected.
- Open editor, then rapid-fire click another card's Edit crops → only the first modal opens; second click is a no-op.
- On a small viewport (height < 700px), open editor on a tall image → dialog scrolls internally without breaking layout.
- Confirm body scroll behind the modal is locked while open, restored on close.

No new unit tests for `depreciation.py` or `csv_export.py` — none of that code path is touched.

## Out of scope (deferred)

- URL synchronization of modal open state.
- Keyboard arrow navigation between crop boxes.
- Backdrop-click-to-close (rejected — canvas drag mis-fires).
- A reusable "modal" primitive shared with other features.
- Touch/pen input handling improvements on the canvas.
