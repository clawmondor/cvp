# Editable Export Templates — Design

**Date:** 2026-08-11
**Status:** Approved, ready for planning

## Problem

Custom CSV export templates (shipped in #56) can be created and deleted, but not
edited. Once a template is saved, fixing a typo in a header, reordering a column,
or toggling `include_excluded` requires deleting the template and rebuilding it
from scratch. This is tedious and error-prone for group-shared templates.

## Key finding

The backend already fully supports editing. `PUT
/api/matters/{matter_id}/export-templates/{tid}`
(`routers/export_templates.py:138`) and `svc.update_template()`
(`services/export_templates.py`) exist and work. **No backend or service changes
are required.** The feature is entirely about surfacing the existing update
capability in the UI.

## Scope

In scope:

- An **Edit** button on each saved-template row.
- A GET endpoint that returns the builder fragment pre-filled for a template.
- Making the single builder form mode-aware (create vs. update).
- A minimal JS adjustment so pre-filled columns serialize correctly.

Explicitly out of scope (YAGNI):

- Duplicate / clone-a-template.
- Inline per-row expansion editing.
- Any change to the `PUT` endpoint, `update_template()`, models, or migrations.

## Approach

Reuse the existing builder form as a single form with two modes. Editing is
driven server-side via an HTMX swap, matching the existing create/delete pattern
(no JSON blobs embedded in the DOM, CSP-safe).

### 1. Edit button in the template list

In `templates/_export_templates_body.html`, each existing-template row gains an
**Edit** button beside Delete:

```html
<button type="button"
        hx-get="/api/matters/{{ matter_id }}/export-templates/{{ t.id }}/edit"
        hx-target="#builder-root" hx-swap="outerHTML"
        class="text-xs text-indigo-500 hover:text-indigo-700">Edit</button>
```

### 2. New GET edit endpoint

Add to `routers/export_templates.py`:

```
GET /api/matters/{matter_id}/export-templates/{tid}/edit
```

- Requires `require_matter_role("contributor")` (same as create/update/delete).
- Loads the template via `svc.get_template(db, tid, group_id)`; 404 if missing.
- Returns the `_export_templates_body.html` fragment with an extra context key
  `editing=<template>`.

The `_builder_context()` helper gains an optional `editing` parameter (default
`None`) so the same context builder serves both the plain and pre-filled
fragments.

### 3. Mode-aware builder form

`_export_templates_body.html` branches on `editing`:

- **Form target:** when `editing`, the form uses
  `hx-put=".../export-templates/{{ editing.id }}"`; otherwise `hx-post` as today.
- **Heading / button copy:** "Editing: *name*" and a **Update template** submit
  button when editing; unchanged create copy otherwise.
- **Field pre-fill:** `name`, `description`, `sort_field` (selected option),
  `include_needs_review`, `include_excluded` (checked state) rendered from
  `editing`.
- **Columns pre-render:** the `<ol id="col-list">` is populated in Jinja with one
  `<li class="col-row">` per saved column, using the **same markup the JS
  `<template id="col-row-template">` produces**, so the existing `serialize()`
  reads them without JS changes:
  - Field columns: `data-field-key="{{ c.field_key }}"`, a `.col-label` showing
    the field key, and `.col-header` input valued from `c.header_label`.
  - Static columns: `data-field-key=""`, a `.col-static` input valued from
    `c.static_value`, and `.col-header` input valued from `c.header_label`.
  - Each row keeps the move-up / move-down / remove buttons.
- **Cancel:** a Cancel control that returns to the blank builder — an `hx-get` to
  the builder fragment (create mode) targeting `#builder-root`. Shown only when
  `editing`.

To avoid duplicating the column-row markup between the Jinja pre-render and the
JS `<template>`, extract the row's inner markup into a Jinja macro or a small
`{% include %}` partial that both the `<ol>` loop and the `<template>` element
render. Keeping them in one source prevents the two from drifting.

### 4. Hidden `columns-json` pre-fill (no JS change)

In `app.js`, the hidden `columns-json` input is only rewritten when the user
interacts with the builder (`serialize()` fires on click/input). A pre-filled
edit form submitted with no changes would otherwise post a stale `[]`.

Rather than add a JS load hook, the edit fragment **pre-fills the hidden input's
`value` server-side** with the template's columns already serialized (single-
quoted attribute + Jinja `tojson`, matching the existing `data-keys` pattern in
this file). So the correct payload is present the instant the fragment loads,
with no reliance on a client event firing. If the user then edits any row,
`serialize()` regenerates `columns-json` from the pre-rendered `.col-row`
elements exactly as it does for JS-created rows. **This feature requires no
`app.js` change.**

### After update

On a successful `PUT`, the `update()` handler already re-renders `#builder-root`
via `_render_body()`, which produces the **blank** builder (create mode) plus the
refreshed template list. This satisfies the confirmed requirement: after saving
an edit, the form resets to blank create mode. No change needed to the update
handler.

## Data flow

```
[Edit] clicked
  -> GET .../{tid}/edit
  -> fragment: builder form pre-filled (hx-put), col-list pre-rendered
  -> htmx:afterSwap -> serialize() -> columns-json populated
User edits fields/columns -> input/click -> serialize() keeps columns-json fresh
[Update template] submitted
  -> PUT .../{tid}  (existing endpoint, unchanged)
  -> fragment: blank builder (create mode) + refreshed list
```

## Error handling

- Edit of a nonexistent / wrong-group template: 404 (mirrors update/delete).
- Malformed columns / validation errors on PUT: unchanged — the existing update
  handler returns the red inline error partial.
- Cancel simply re-fetches the blank builder; no state to clean up.

## Testing

One integration test in `tests/` mirroring the existing export-templates tests:

1. Create a template with a mix of field and static columns.
2. GET the `.../{tid}/edit` fragment; assert the form is in PUT mode
   (`hx-put` present, "Update template" copy) and that name, a header label, and
   a static value appear pre-filled.
3. PUT an update (rename, add a column); assert the persisted template reflects
   the changes and column count.

The only genuinely new logic is the Jinja col-row pre-render and the edit
endpoint; the test targets both. Existing create/update/delete tests remain
unchanged.

## Files touched

- `src/cvp/routers/export_templates.py` — new GET edit endpoint; `editing` param
  threaded through `_builder_context` / `_render_body`.
- `src/cvp/templates/_export_templates_body.html` — Edit button, mode-aware form,
  pre-rendered col-list, Cancel control; shared col-row markup extracted to a
  macro/partial.
- `tests/` — edit-form + update integration tests.

(No `app.js` change — the hidden `columns-json` is pre-filled server-side.)
