# CSP Inline Script Removal Design

**Date:** 2026-05-08
**Status:** Approved

## Problem

Three templates contain inline `<script>` blocks that are blocked by the app's `Content-Security-Policy` `script-src` directive, which does not include `'unsafe-inline'`. The affected templates are:

- `_tab_evidence.html` — drag-and-drop upload IIFE
- `_tab_rooms.html` — `startRename` global function and `hx-on::after-request` attribute
- `_crop_editor.html` — 275-line canvas crop editor IIFE with five server-rendered Jinja values

## Approach

Move all inline scripts to external static files (`app.js` and a new `crop-editor.js`). Pass server-rendered data to the JS layer via `data-*` attributes and `<script type="application/json">` tags (which CSP ignores since they are non-executable).

No changes to `middleware.py` are required.

---

## Tier 1 — `_tab_evidence.html` and `_tab_rooms.html`

Both templates are server-side `{% include %}`-d into `matter_detail.html`, so their elements are always present in the DOM at `DOMContentLoaded`. The fix is a direct relocation into `app.js`.

### Drag-drop upload (`_tab_evidence.html`)

- Extract the IIFE into a named `initEvidenceUpload()` function in `app.js`.
- Call it on `DOMContentLoaded`, guarded by `if (!document.getElementById('drop-zone')) return` so it is a no-op on pages that don't include the evidence tab.
- Remove the `<script>` block from `_tab_evidence.html`.

### Room rename and form reset (`_tab_rooms.html`)

- Move `startRename(roomId)` to `app.js` as-is. It is a plain global function with no Jinja dependencies.
- Replace the `hx-on::after-request` attribute on the add-room form with a delegated `htmx:afterRequest` listener in `app.js`. HTMX evaluates `hx-on` values with `new Function()`, which also requires `'unsafe-eval'` — absent from the current CSP. The listener is keyed on a new `id="add-room-form"` added to the form element.
- Remove the `<script>` block from `_tab_rooms.html`.

---

## Tier 2 — `_crop_editor.html`

The crop editor is loaded dynamically via HTMX (`toggleCropEditor` does an `htmx.ajax` GET to `/api/evidence/<file_id>/crop-editor`). It currently embeds five Jinja-rendered values directly inside the script:

| Value | Type | Current form |
|---|---|---|
| `evidence_file.id` | UUID string | `{{ evidence_file.id \| tojson }}` |
| `img_w` | integer | `{{ img_w }}` |
| `img_h` | integer | `{{ img_h }}` |
| `stored_path` | string | `{{ stored_path }}` |
| crops array | JSON array | `{{ crops_json \| safe }}` |

### Data externalization

**Scalar values** → `data-*` attributes on the container `<div>`:

```html
<div id="crop-editor-{{ evidence_file.id }}"
     data-init="crop-editor"
     data-ef-id="{{ evidence_file.id }}"
     data-img-w="{{ img_w }}"
     data-img-h="{{ img_h }}"
     data-img-src="/files/{{ stored_path }}"
     class="...">
```

**Crops array** → `<script type="application/json">` tag. The browser does not execute non-JS script types, so this is unaffected by CSP:

```html
<script type="application/json" id="crop-data-{{ evidence_file.id }}">{{ crops_json | safe }}</script>
```

### Close button

Replace the inline `onclick` attribute with a `data-*` attribute:

```html
<!-- before -->
<button onclick="document.getElementById('crop-editor-{{ evidence_file.id }}').remove()">

<!-- after -->
<button data-crop-editor-close="{{ evidence_file.id }}">
```

A delegated click listener in `crop-editor.js` reads `data-crop-editor-close` and removes the matching container.

### New `/static/crop-editor.js`

Contains all canvas editor logic extracted from the template. Responsibilities:

1. **Activation** — listens for `htmx:afterSettle` on `document`. On each event, queries `[data-init="crop-editor"]:not([data-ready])`, calls `initCropEditor(container)` on each match, then sets `data-ready="1"` to prevent double-init.

2. **Initialisation** — `initCropEditor(container)` reads `data-ef-id`, `data-img-w`, `data-img-h`, `data-img-src` from the container, parses the JSON from `#crop-data-<ef_id>`, then sets up the canvas, event listeners, and all existing functionality.

3. **Global function registration** — `ceSelect_<id>` and `ceReset_<id>` are registered on `window` during init, as they are today. This preserves the existing deep-link auto-init hook in `app.js`.

4. **Close button delegation** — a single delegated `click` listener on `document` checks `event.target.dataset.cropEditorClose` and removes the matching container.

5. **Sidebar DOM construction** — `updateSidebar()` currently builds HTML via `innerHTML` with an `onclick` string, which CSP blocks as an inline event handler. It is rewritten to use `document.createElement` + `addEventListener` for the "Reset to Claude bbox" button.

### Loading

`base.html` gets a `<script src="/static/crop-editor.js" defer></script>` tag. Already permitted by CSP `'self'`.

---

## Files changed

| File | Change |
|---|---|
| `src/cvp/static/app.js` | Add `initEvidenceUpload()`, `startRename()`, `htmx:afterRequest` handler for add-room form |
| `src/cvp/static/crop-editor.js` | **New.** All crop editor canvas logic |
| `src/cvp/templates/_tab_evidence.html` | Remove `<script>` block |
| `src/cvp/templates/_tab_rooms.html` | Remove `<script>` block; add `id="add-room-form"` to form; remove `hx-on::after-request` attribute |
| `src/cvp/templates/_crop_editor.html` | Remove `<script>` block; add `data-*` attrs and JSON script tag to container; replace `onclick` on close button |
| `src/cvp/templates/base.html` | Add `<script src="/static/crop-editor.js" defer>` |

## Files not changed

- `src/cvp/middleware.py` — CSP header unchanged
- All routers — no server-side changes required
