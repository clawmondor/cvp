# Editable Export Templates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users edit a saved custom CSV export template in the existing builder UI, instead of deleting and recreating it.

**Architecture:** The backend already supports updates (`PUT .../export-templates/{tid}` + `svc.update_template()`) — no service or model changes. This plan adds a GET endpoint that returns the builder fragment pre-filled for one template, makes the single builder form mode-aware (create vs. update) in Jinja, and surfaces Edit/Cancel controls. Columns are pre-rendered server-side and the hidden `columns-json` input is pre-filled server-side, so a no-op update posts the correct payload with **zero JS changes**.

**Tech Stack:** FastAPI, Jinja2, HTMX, SQLAlchemy 2.x, pytest. Package `cvp` (this work lives on the `cvp-legacy` line — the export-templates feature exists only there, not on `main`).

## Global Constraints

- Never use inline JavaScript event handlers (`onclick=` etc.); CSP blocks them. Interactivity is delegated in `src/cvp/static/app.js`. (This plan requires **no** app.js change.)
- Type hints everywhere; modern syntax (`X | None`).
- One happy-path integration test per router change; Vision mocked (N/A here).
- Run `uv run ruff format .` then `uv run ruff format --check .` before every commit (line length 100); CI enforces zero reformatted files.
- Currency/ACV/depreciation rules — untouched by this feature.
- Do not change Xactimate CSV column names — untouched.

---

### Task 1: Editable builder (endpoint + mode-aware template)

**Files:**
- Modify: `src/cvp/routers/export_templates.py` — thread `editing` through `_builder_context` / `_render_body`; add GET `.../{tid}/edit` endpoint.
- Modify: `src/cvp/templates/_export_templates_body.html` — Edit button per row; mode-aware form (`hx-put` vs `hx-post`); scalar prefills; pre-rendered `col-list`; server-filled `columns-json`; Cancel control.
- Test: `tests/test_export_templates_router.py` — add edit-form + update tests.

**Interfaces:**
- Consumes (existing, unchanged): `svc.get_template(db, template_id, group_id) -> ExportTemplate | None`; `svc.update_template(...)`; `require_matter_role("contributor")`; `_matter_group_id(db, matter_id) -> str`.
- Produces: GET route `/api/matters/{matter_id}/export-templates/{tid}/edit` returning the `#builder-root` HTML fragment in edit mode. `_builder_context(...)` and `_render_body(...)` gain an optional `editing: ExportTemplate | None = None` parameter and a computed `editing_columns: list[dict]` context key.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_export_templates_router.py`:

```python
def test_list_row_has_edit_button(seeded_db, make_client):
    client, matter_id = make_client()
    client.post(f"/api/matters/{matter_id}/export-templates", data=_payload())
    page = client.get(f"/matters/{matter_id}/export-templates")
    assert ">Edit<" in page.text
    assert "/edit" in page.text


def test_edit_form_prefills_and_is_put_mode(seeded_db, make_client):
    client, matter_id = make_client()
    client.post(
        f"/api/matters/{matter_id}/export-templates",
        data=_payload(
            name="Editable",
            columns=[
                {"field_key": "description", "header_label": "Item", "static_value": None},
                {"field_key": None, "header_label": "Note", "static_value": "n/a"},
            ],
        ),
    )
    page = client.get(f"/matters/{matter_id}/export-templates")
    tid = re.search(r'data-template-id="([^"]+)"', page.text).group(1)

    r = client.get(f"/api/matters/{matter_id}/export-templates/{tid}/edit")
    assert r.status_code == 200
    assert 'id="builder-root"' in r.text
    assert f'hx-put="/api/matters/{matter_id}/export-templates/{tid}"' in r.text
    assert "Update template" in r.text
    assert 'value="Editable"' in r.text  # name prefilled
    assert 'value="Item"' in r.text  # field-column header prefilled
    assert 'value="n/a"' in r.text  # static-column value prefilled
    # hidden columns-json is server-filled so a no-op update posts the real columns
    assert '"field_key": "description"' in r.text or '"field_key":"description"' in r.text


def test_edit_form_missing_template_404(seeded_db, make_client):
    client, matter_id = make_client()
    r = client.get(f"/api/matters/{matter_id}/export-templates/nope/edit")
    assert r.status_code == 404


def test_update_via_put_persists_and_resets_to_create(seeded_db, make_client):
    client, matter_id = make_client()
    client.post(f"/api/matters/{matter_id}/export-templates", data=_payload(name="Before"))
    page = client.get(f"/matters/{matter_id}/export-templates")
    tid = re.search(r'data-template-id="([^"]+)"', page.text).group(1)

    r = client.put(
        f"/api/matters/{matter_id}/export-templates/{tid}",
        data=_payload(
            name="After",
            columns=[
                {"field_key": "description", "header_label": None, "static_value": None},
                {"field_key": "room", "header_label": None, "static_value": None},
            ],
        ),
    )
    assert r.status_code == 200
    # response resets to blank create mode
    assert "Save template" in r.text
    assert "Update template" not in r.text

    t = seeded_db.get(ExportTemplate, tid)
    assert t.name == "After"
    assert len(t.columns) == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib uv run pytest tests/test_export_templates_router.py -k "edit_form or edit_button or put_persists" -v`
Expected: FAIL — the `/edit` route 404s (route not defined) and the template lacks the Edit button / prefilled values.

(The `DYLD_FALLBACK_LIBRARY_PATH` prefix is only needed if running in a fresh worktree venv where WeasyPrint's native libs aren't found; harmless otherwise.)

- [ ] **Step 3: Thread `editing` through the router context helpers**

In `src/cvp/routers/export_templates.py`, replace `_builder_context`, `_render_page`, and `_render_body` with versions that accept `editing`:

```python
def _builder_context(
    request: Request,
    db,
    matter_id: str,
    group_id: str,
    user: CurrentUser,
    editing=None,
) -> dict:
    tmpls = svc.list_templates(db, group_id)
    editing_columns: list[dict] = []
    if editing is not None:
        editing_columns = [
            {
                "field_key": c.field_key,
                "header_label": c.header_label,
                "static_value": c.static_value,
            }
            for c in editing.columns
        ]
    return {
        "request": request,
        "user": user,
        "matter_id": matter_id,
        "templates_list": tmpls,
        "field_groups": field_groups(),
        "sort_fields": svc.SORT_FIELDS,
        "xactimate_defaults": svc.xactimate_default_columns(),
        "editing": editing,
        "editing_columns": editing_columns,
    }


def _render_page(
    request: Request, db, matter_id: str, group_id: str, user: CurrentUser
) -> HTMLResponse:
    """Full page (extends base.html) — used by the GET builder page."""
    return templates.TemplateResponse(
        request,
        "export_templates_builder.html",
        _builder_context(request, db, matter_id, group_id, user),
    )


def _render_body(
    request: Request, db, matter_id: str, group_id: str, user: CurrentUser, editing=None
) -> HTMLResponse:
    """Swappable ``#builder-root`` fragment only — create/update/delete/edit."""
    return templates.TemplateResponse(
        request,
        "_export_templates_body.html",
        _builder_context(request, db, matter_id, group_id, user, editing),
    )
```

- [ ] **Step 4: Add the GET edit endpoint**

In `src/cvp/routers/export_templates.py`, add after the `create` handler (near the other `/{tid}` routes):

```python
@router.get(
    "/api/matters/{matter_id}/export-templates/{tid}/edit", response_class=HTMLResponse
)
def edit_form(
    request: Request,
    matter_id: str,
    tid: str,
    user: CurrentUser = Depends(require_matter_role("contributor")),
) -> HTMLResponse:
    db = SessionLocal()
    try:
        group_id = _matter_group_id(db, matter_id)
        template = svc.get_template(db, tid, group_id)
        if template is None:
            raise HTTPException(status_code=404, detail="Template not found")
        return _render_body(request, db, matter_id, group_id, user, editing=template)
    finally:
        db.close()
```

- [ ] **Step 5: Add the Edit button to each list row**

In `src/cvp/templates/_export_templates_body.html`, replace the single Delete button in the list `<li>` (the `<button ... hx-delete=...>Delete</button>` block) with an Edit + Delete pair:

```html
        <span class="flex gap-2">
          <button type="button"
                  hx-get="/api/matters/{{ matter_id }}/export-templates/{{ t.id }}/edit"
                  hx-target="#builder-root" hx-swap="outerHTML"
                  class="text-xs text-indigo-500 hover:text-indigo-700">Edit</button>
          <button type="button"
                  hx-delete="/api/matters/{{ matter_id }}/export-templates/{{ t.id }}"
                  hx-target="#builder-root" hx-swap="outerHTML"
                  class="text-xs text-red-500 hover:text-red-700">Delete</button>
        </span>
```

- [ ] **Step 6: Make the form mode-aware (heading, action, scalar prefills, submit copy)**

In the same file, add a heading with Cancel just above the `<form id="builder-form">`, and edit the form open tag + scalar inputs + submit button.

Heading (insert immediately before the `<form ...>`):

```html
  {% if editing %}
  <div class="flex items-center justify-between">
    <p class="text-sm font-semibold text-indigo-700">Editing: {{ editing.name }}</p>
    <button type="button"
            hx-get="/matters/{{ matter_id }}/export-templates"
            hx-target="#builder-root" hx-swap="outerHTML" hx-select="#builder-root"
            class="text-xs text-gray-500 hover:text-gray-700">Cancel</button>
  </div>
  {% endif %}
```

Form open tag — swap the fixed `hx-post` for a conditional:

```html
  <form id="builder-form"
        {% if editing %}hx-put="/api/matters/{{ matter_id }}/export-templates/{{ editing.id }}"{% else %}hx-post="/api/matters/{{ matter_id }}/export-templates"{% endif %}
        hx-target="#builder-root" hx-swap="outerHTML"
        class="space-y-4 rounded-lg border border-gray-200 bg-gray-50 p-4">
```

Name input — add `value`:

```html
        <input name="name" required value="{{ editing.name if editing else '' }}"
               class="mt-1 w-full rounded border px-2 py-1 text-sm">
```

Sort select — mark the selected option:

```html
          {% for s in sort_fields %}<option value="{{ s }}"{% if editing and editing.sort_field == s %} selected{% endif %}>{{ s }}</option>{% endfor %}
```

Description input — add `value`:

```html
      <input name="description" value="{{ editing.description if editing else '' }}"
             class="mt-1 w-full rounded border px-2 py-1 text-sm">
```

Checkboxes — add conditional `checked`:

```html
      <label><input type="checkbox" name="include_needs_review" value="true"{% if editing and editing.include_needs_review %} checked{% endif %}> Include needs-review items</label>
      <label><input type="checkbox" name="include_excluded" value="true"{% if editing and editing.include_excluded %} checked{% endif %}> Include excluded items</label>
```

Submit button label:

```html
    <button type="submit" class="rounded-md bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-500">
      {{ 'Update template' if editing else 'Save template' }}
    </button>
```

- [ ] **Step 7: Pre-render the columns and pre-fill the hidden `columns-json`**

Replace the empty `<ol id="col-list" ...></ol>` with a loop that mirrors exactly what `app.js` `makeRow()` produces (same classes/`data-field-key`/`.col-label`/`.col-header`/`.col-static` so the existing `serialize()` reads them unchanged), and replace the hidden input to carry the server-serialized columns:

```html
      <div>
        <p class="mb-1 text-xs font-semibold text-gray-600">Columns (in order)</p>
        <ol id="col-list" class="space-y-1">
          {% if editing %}
          {% for c in editing.columns %}
          {% if c.field_key %}
          <li class="col-row flex items-center gap-2 rounded border border-gray-200 bg-white p-2" data-field-key="{{ c.field_key }}">
            <span class="col-label flex-1 text-xs"><span class="font-mono text-gray-700">{{ c.field_key }}</span></span>
            <input type="text" class="col-header w-36 rounded border px-1 text-xs" placeholder="header" value="{{ c.header_label or '' }}">
            <button type="button" data-action="move-col-up" class="text-gray-400 hover:text-gray-700">↑</button>
            <button type="button" data-action="move-col-down" class="text-gray-400 hover:text-gray-700">↓</button>
            <button type="button" data-action="remove-col" class="text-red-400 hover:text-red-700">✕</button>
          </li>
          {% else %}
          <li class="col-row flex items-center gap-2 rounded border border-gray-200 bg-white p-2" data-field-key="">
            <span class="col-label flex-1 text-xs"><span class="font-semibold text-gray-500">Static:</span> <input type="text" class="col-static ml-1 rounded border px-1 text-xs" placeholder="fixed value" value="{{ c.static_value or '' }}"></span>
            <input type="text" class="col-header w-36 rounded border px-1 text-xs" placeholder="header (required)" value="{{ c.header_label or '' }}">
            <button type="button" data-action="move-col-up" class="text-gray-400 hover:text-gray-700">↑</button>
            <button type="button" data-action="move-col-down" class="text-gray-400 hover:text-gray-700">↓</button>
            <button type="button" data-action="remove-col" class="text-red-400 hover:text-red-700">✕</button>
          </li>
          {% endif %}
          {% endfor %}
          {% endif %}
        </ol>
      </div>
```

Hidden input (single-quoted attribute + `tojson`, matching the existing `data-keys='{{ ... | tojson }}'` pattern in this file so quotes are HTML-safe):

```html
    <input type="hidden" id="columns-json" name="columns_json" value='{% if editing %}{{ editing_columns | tojson }}{% else %}[]{% endif %}'>
```

Leave the `<template id="col-row-template">` block and all `data-action` buttons untouched — JS still builds newly-added rows from it, and `serialize()` still overwrites `columns-json` the moment the user edits any row.

- [ ] **Step 8: Run the tests to verify they pass**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib uv run pytest tests/test_export_templates_router.py -v`
Expected: PASS — all new tests plus the pre-existing ones (create/delete, cross-group 404s, custom export, builder catalog, fragment-not-full-page) stay green.

- [ ] **Step 9: Format and commit**

```bash
uv run ruff format .
uv run ruff format --check .
git add src/cvp/routers/export_templates.py src/cvp/templates/_export_templates_body.html tests/test_export_templates_router.py
git commit -m "feat(exports): edit saved custom export templates

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: End-to-end verification and PR

**Files:** none (verification + integration). Any defect found here is fixed in the Task 1 files and folded into this task's commit.

- [ ] **Step 1: Run the full test suite**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib uv run pytest -q`
Expected: PASS (the `cvp-legacy` line has one known pre-existing failing Vision test — see memory `project_weasyprint_worktree_dyld`; no other failures are acceptable).

- [ ] **Step 2: Browser-verify the edit flow**

Use the memory `project_browser_verify_recipe` (fresh DB + `AUTO_LOGIN` + `system_admin` + Playwright). Drive: create a template with a mix of field and static columns → click **Edit** on its row → confirm name/description/sort/checkboxes and every column (headers + static value) are pre-filled and the button reads **Update template** → reorder a column and change a header → **Update template** → confirm the list shows the change, the builder resets to a blank **Save template** form, and re-opening **Edit** reflects the new order. Also confirm **Cancel** returns to a blank builder without saving.

- [ ] **Step 3: Commit any verification fixes (if needed)**

```bash
uv run ruff format . && uv run ruff format --check .
git add -A
git commit -m "fix(exports): address edit-template verification findings

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

(Skip this step if verification surfaced nothing.)

- [ ] **Step 4: Finish the branch**

Use the `superpowers:finishing-a-development-branch` skill. Push `feat/editable-export-templates` and open a PR targeting **`cvp-legacy`** (not `main` — the export-templates feature exists only on the legacy line). Do not merge locally.

---

## Self-Review

**Spec coverage:**
- Edit button per row → Task 1, Step 5. ✓
- GET edit endpoint returning pre-filled fragment → Task 1, Steps 3–4. ✓
- Mode-aware form (hx-put, heading, submit copy) → Task 1, Step 6. ✓
- Scalar prefills (name/desc/sort/checkboxes) → Task 1, Step 6. ✓
- Columns pre-rendered matching `makeRow` output → Task 1, Step 7. ✓
- Cancel returns to blank builder → Task 1, Step 6 (heading block). ✓
- Reset to blank create mode after save → existing `update()` handler re-renders blank body; asserted in `test_update_via_put_persists_and_resets_to_create`. ✓
- No Duplicate, no inline expansion, no backend changes → honored. ✓
- Spec §4 "JS serialize-on-load" → superseded by server-filled `columns-json` (simpler, testable, zero JS change); spec §4 updated to match. ✓
- Testing (create → GET edit prefilled → PUT persists) → Task 1, Step 1. ✓

**Placeholder scan:** No TBD/TODO/"handle edge cases"; every code step has literal code. ✓

**Type consistency:** `editing` (ExportTemplate | None) and `editing_columns` (list[dict]) defined in `_builder_context` (Step 3) and consumed by the template (Steps 6–7); `edit_form` route path matches the `hx-get` in Step 5 and the tests in Step 1. `serialize()` contract (reads `.col-row` / `data-field-key` / `.col-header` / `.col-static`) matches the pre-rendered markup in Step 7. ✓
