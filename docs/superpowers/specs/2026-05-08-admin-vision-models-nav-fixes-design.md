# Admin Vision Models Nav & Default-Selection Fixes

**Date:** 2026-05-08  
**Status:** Approved

## Problem

Three related defects in the Vision Models admin UI:

1. No navigation link to `/admin/vision-models` from any admin sidebar.
2. `admin/vision_models.html` extends `base.html` (main app shell) instead of `admin/base.html`, so it renders without the admin sidebar.
3. The "Default" column uses `<input type="radio">` inside a **separate `<form>` per row**, making each radio its own single-element group. The browser cannot enforce mutual exclusion, so multiple rows can appear checked simultaneously.

## Design

### 1. Admin nav link + layout fix

- Change `src/cvp/templates/admin/vision_models.html` to extend `admin/base.html`.
- Add a `{% block sidebar %}` that lists the same system-admin links as other system pages, with "Vision Models" marked active.
- Add a "Vision Models" sidebar link (`/admin/vision-models`) to every system admin template that defines a sidebar block:
  - `admin/system/dashboard.html`
  - `admin/system/users.html`
  - `admin/system/user_detail.html`
  - `admin/system/groups.html`
  - `admin/system/group_detail.html`
  - `admin/system/matters.html`
  - `admin/system/audit.html`

### 2. Single form for default selection

- Remove the per-row `<form>` and `onchange="this.form.requestSubmit()"` from the Default column in `admin/_vision_models_row.html`.
- In `admin/vision_models.html`, wrap the table in:
  ```html
  <form method="POST" action="/admin/vision-models/set-default">
    <table>...</table>
    <button type="submit">Save default</button>
  </form>
  ```
- Each row's Default cell becomes a plain `<input type="radio" name="default_model_id" value="{{ r.id }}" {% if r.is_default %}checked{% endif %}>`. No enclosing form.

### 3. New endpoint

Add `POST /admin/vision-models/set-default` to `src/cvp/routers/admin/vision_models.py`:
- Accepts `default_model_id: int = Form(...)`.
- Executes the same DB logic as the existing `/{model_id}/set-default`: clear all `is_default`, set the target row, guard against disabled model, write audit log.
- Redirects 303 to `/admin/vision-models`.

The existing `POST /{model_id}/set-default` endpoint is removed (it was only called by the per-row HTMX forms being deleted).

## Scope

- Template changes: `admin/vision_models.html`, `admin/_vision_models_row.html`, 7 system admin sidebar templates.
- Router change: `src/cvp/routers/admin/vision_models.py` — add one endpoint, remove one.
- No data model changes, no migrations, no new dependencies.

## Out of Scope

- Changing enable/disable or refresh/delete per-row HTMX behavior (those remain as-is).
- Any changes to the `_vision_model_picker.html` used in matter detail.
