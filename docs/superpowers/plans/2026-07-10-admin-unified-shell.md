# Admin Unified Shell Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the admin area use the shared `base.html` app shell (top bar + left sidebar + theme-aware tokens) with a role-aware Admin nav group, retiring the separate `admin/base.html`.

**Architecture:** Add a role-aware `_admin_sidebar.html` partial and surface it as a contextual "Admin" group in `_app_sidebar.html` (shown under `/admin/`); teach the `base.html` topbar to render a `breadcrumbs` trail and default its title to `panel_title`. Then migrate all 26 admin page templates from `admin/base.html` to `base.html` (dropping their per-page `{% block sidebar %}`), and delete `admin/base.html`.

**Tech Stack:** FastAPI, Jinja2, Tailwind CSS v4 (standalone CLI), pytest.

## Global Constraints

- **Layout/chrome change only.** No admin route, `_ctx()`, RBAC, data-model, export, depreciation, Vision, or legal-copy behavior changes.
- **Existing design-system tokens only** — no new colors/fonts/radii; no raw Tailwind color families (e.g. `bg-indigo-600`). `scripts/audit_design_tokens.py` must stay clean.
- **No inline JS event handlers** (`onclick=` etc.). This plan adds none.
- **After any template change run `source .venv/bin/activate && uv run css`** to regenerate `src/claimos/static/app.css` (gitignored) so new utility classes are emitted.
- Always run Python/pytest through the venv: `source .venv/bin/activate && ...`. Never system Python.
- Branch `rebrand-teal` — do NOT switch branches.
- Before every commit: `uv run ruff format .` then `uv run ruff format --check .` and `uv run ruff check .` — all clean. Line length 100.
- Auth/RBAC gating of admin routes is unchanged — this only reskins chrome.

## File Structure

- `src/claimos/templates/_admin_sidebar.html` (new) — role-aware admin section nav; a local Jinja macro renders each item.
- `src/claimos/templates/_app_sidebar.html` (modify) — add the contextual Admin group under `/admin/`.
- `src/claimos/templates/base.html` (modify) — topbar renders `breadcrumbs` when present, else the title; title block defaults to `panel_title`.
- 26 admin page templates (modify) — extend `base.html`, drop `{% block sidebar %}`.
- `src/claimos/templates/admin/base.html` (delete) — after all pages migrated.
- `src/claimos/styles/theme.css` (modify) — one comment marking `admin-*` tokens dead.
- `DESIGN.md` (modify) — describe the unified admin shell.
- `tests/test_admin_shell.py` (new) — partial-render tests for the admin nav + gating.

---

### Task 1: Admin nav partial + shell wiring

**Files:**
- Create: `src/claimos/templates/_admin_sidebar.html`
- Modify: `src/claimos/templates/_app_sidebar.html`
- Modify: `src/claimos/templates/base.html`
- Test: `tests/test_admin_shell.py` (new)

**Interfaces:**
- Consumes: template context `request` (always), `user` (with `.system_role`), optional `group` (with `.id`), optional `unread_count`, optional `breadcrumbs` (list of `{"label","url"}`), optional `panel_title`.
- Produces: `_admin_sidebar.html` (included by `_app_sidebar.html` under `/admin/`); a `breadcrumbs`-aware topbar in `base.html`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_admin_shell.py`:

```python
"""Tests for the role-aware admin nav partial and its gating in the app sidebar."""

import types

from claimos.templating import templates


def _user(role):
    return types.SimpleNamespace(system_role=role)


def _render_admin(role, path, group=None, unread_count=0) -> str:
    tmpl = templates.env.get_template("_admin_sidebar.html")
    request = types.SimpleNamespace(url=types.SimpleNamespace(path=path))
    return tmpl.render(
        request=request, user=_user(role), group=group, unread_count=unread_count
    )


def _render_app_sidebar(path, user=None, group=None) -> str:
    tmpl = templates.env.get_template("_app_sidebar.html")
    request = types.SimpleNamespace(url=types.SimpleNamespace(path=path))
    return tmpl.render(request=request, user=user, group=group, claim=None)


def test_admin_nav_system_role_links():
    html = _render_admin("system_admin", "/admin/system/")
    for href in (
        "/admin/system/users",
        "/admin/system/groups",
        "/admin/system/claims",
        "/admin/system/feedback",
        "/admin/system/audit",
        "/admin/vision-models",
        "/admin/system/runtime-config",
    ):
        assert f'href="{href}"' in html
    assert "/admin/internal/" not in html


def test_admin_nav_internal_role_links():
    html = _render_admin("internal_admin", "/admin/internal/")
    assert 'href="/admin/internal/users"' in html
    assert 'href="/admin/internal/claims"' in html
    assert 'href="/admin/internal/groups"' in html
    assert "/admin/system/" not in html


def test_admin_nav_org_role_carries_group_id():
    group = types.SimpleNamespace(id="g1")
    html = _render_admin("external_admin", "/admin/org/users", group=group)
    assert 'href="/admin/org/users?group_id=g1"' in html
    assert 'href="/admin/org/claims?group_id=g1"' in html
    assert 'href="/admin/org/profile?group_id=g1"' in html


def test_admin_nav_active_state():
    html = _render_admin("system_admin", "/admin/system/users")
    # The Users link is active; find its anchor and confirm the active token.
    import re

    anchors = re.findall(r'<a\s+href="[^"]*".*?</a>', html, re.DOTALL)
    users = next(a for a in anchors if 'href="/admin/system/users"' in a)
    assert "bg-primary-subtle" in users


def test_admin_nav_feedback_badge():
    html = _render_admin("system_admin", "/admin/system/", unread_count=4)
    assert ">4<" in html


def test_app_sidebar_shows_admin_group_under_admin_path():
    html = _render_app_sidebar("/admin/system/", user=_user("system_admin"))
    assert "Admin" in html
    assert 'href="/admin/system/audit"' in html


def test_app_sidebar_hides_admin_group_off_admin_path():
    html = _render_app_sidebar("/dashboard", user=_user("system_admin"))
    assert 'href="/admin/system/audit"' not in html
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && uv run pytest tests/test_admin_shell.py -v`
Expected: FAIL — `_admin_sidebar.html` does not exist (`TemplateNotFound`).

- [ ] **Step 3: Create `src/claimos/templates/_admin_sidebar.html`**

```html
{% macro item(href, label, active, badge=0) %}
<a href="{{ href }}"
   class="flex items-center justify-between gap-3 rounded-md px-3 py-2 font-medium
   {% if active %}bg-primary-subtle text-primary
   {% else %}text-neutral-600 hover:bg-neutral-200 hover:text-neutral-900{% endif %}">
  <span>{{ label }}</span>
  {% if badge %}<span class="inline-flex items-center rounded-full bg-error px-1.5 py-0.5 text-xs text-white">{{ badge }}</span>{% endif %}
</a>
{% endmacro %}

{% set p = request.url.path %}
{% if user and user.system_role == 'system_admin' %}
  {{ item('/admin/system/', 'Overview', p == '/admin/system/') }}
  {{ item('/admin/system/users', 'Users', p == '/admin/system/users') }}
  {{ item('/admin/system/groups', 'Groups', p == '/admin/system/groups') }}
  {{ item('/admin/system/claims', 'Claims', p == '/admin/system/claims') }}
  {{ item('/admin/system/feedback', 'Feedback', p == '/admin/system/feedback', unread_count | default(0)) }}
  {{ item('/admin/system/audit', 'Audit Log', p == '/admin/system/audit') }}
  {{ item('/admin/vision-models', 'Vision Models', p == '/admin/vision-models') }}
  {{ item('/admin/system/runtime-config', 'Runtime Config', p == '/admin/system/runtime-config') }}
{% elif user and user.system_role == 'internal_admin' %}
  {{ item('/admin/internal/', 'Overview', p == '/admin/internal/') }}
  {{ item('/admin/internal/users', 'Users', p == '/admin/internal/users') }}
  {{ item('/admin/internal/claims', 'Claims', p == '/admin/internal/claims') }}
  {{ item('/admin/internal/groups', 'External Groups', p == '/admin/internal/groups') }}
{% elif user and user.system_role == 'external_admin' and group %}
  {% set q = '?group_id=' ~ group.id %}
  {{ item('/admin/org/' ~ q, 'Overview', p == '/admin/org/') }}
  {{ item('/admin/org/users' ~ q, 'Users', p == '/admin/org/users') }}
  {{ item('/admin/org/claims' ~ q, 'Claims', p == '/admin/org/claims') }}
  {{ item('/admin/org/profile' ~ q, 'Profile', p == '/admin/org/profile') }}
{% endif %}
```

- [ ] **Step 4: Add the Admin group to `src/claimos/templates/_app_sidebar.html`**

Insert immediately before the final closing `</nav>` (after the claim-scoped `{% endif %}`):

```html
  {# ── Admin (only under /admin/) ─────────────────────────── #}
  {% if request.url.path.startswith('/admin/') %}
  <p class="px-3 pt-5 pb-1 text-xs font-semibold uppercase tracking-wider text-neutral-400">
    Admin
  </p>
  {% include "_admin_sidebar.html" %}
  {% endif %}
```

- [ ] **Step 5: Update the topbar in `src/claimos/templates/base.html`**

Replace the topbar's left cluster — the current block:

```html
        <div class="flex items-center gap-2 text-sm">
          <a href="/" class="font-semibold text-neutral-900">CLAIMOS</a>
          <span class="text-neutral-300">/</span>
          <span class="font-medium text-neutral-600">{% block topbar_title %}ClaimOS{% endblock %}</span>
        </div>
```

with:

```html
        <div class="flex items-center gap-2 text-sm">
          <a href="/" class="font-semibold text-neutral-900">CLAIMOS</a>
          <span class="text-neutral-300">/</span>
          {% if breadcrumbs %}
            {% for crumb in breadcrumbs %}
              {% if not loop.last %}
              <a href="{{ crumb.url }}" class="text-neutral-500 hover:text-neutral-700">{{ crumb.label }}</a>
              <span class="text-neutral-300">/</span>
              {% else %}
              <span class="font-medium text-neutral-600">{{ crumb.label }}</span>
              {% endif %}
            {% endfor %}
          {% else %}
          <span class="font-medium text-neutral-600">{% block topbar_title %}{{ panel_title | default("ClaimOS") }}{% endblock %}</span>
          {% endif %}
        </div>
```

- [ ] **Step 6: Rebuild CSS**

Run: `source .venv/bin/activate && uv run css`
Expected: `Done in NNms`, no errors.

- [ ] **Step 7: Run the new tests**

Run: `source .venv/bin/activate && uv run pytest tests/test_admin_shell.py -v`
Expected: all 7 PASS.

- [ ] **Step 8: Guard + app-shell regression + format/lint**

Run:
```bash
source .venv/bin/activate && \
python scripts/audit_design_tokens.py && \
uv run pytest tests/test_app_shell.py tests/test_admin_shell.py -q && \
uv run ruff format . && uv run ruff format --check . && uv run ruff check .
```
Expected: guard `clean ✓`; tests green; ruff `All checks passed!`, zero reformatting.

- [ ] **Step 9: Commit**

```bash
git add src/claimos/templates/_admin_sidebar.html src/claimos/templates/_app_sidebar.html \
        src/claimos/templates/base.html tests/test_admin_shell.py
git commit -m "feat: role-aware admin nav group + breadcrumbs-aware topbar

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Migrate System admin pages (+ Vision Models) to the app shell

This and Tasks 3–4 are mechanical template refactors guarded by the existing
admin router tests (which render each page through its real template and assert
200 + content — a broken render would 500 and fail). Plus one positive assertion
that the unified shell is applied.

**Files (modify — 12 templates):**
- `src/claimos/templates/admin/vision_models.html`
- `src/claimos/templates/admin/system/audit.html`
- `src/claimos/templates/admin/system/claims.html`
- `src/claimos/templates/admin/system/dashboard.html`
- `src/claimos/templates/admin/system/feedback.html`
- `src/claimos/templates/admin/system/feedback_detail.html`
- `src/claimos/templates/admin/system/feedback_new.html`
- `src/claimos/templates/admin/system/group_detail.html`
- `src/claimos/templates/admin/system/groups.html`
- `src/claimos/templates/admin/system/runtime_config.html`
- `src/claimos/templates/admin/system/user_detail.html`
- `src/claimos/templates/admin/system/users.html`
- Test: `tests/test_admin_system.py` (add one shell assertion)

**Interfaces:**
- Consumes: `_app_sidebar.html`/`_admin_sidebar.html`/topbar from Task 1.

- [ ] **Step 1: Baseline — existing system tests green**

Run: `source .venv/bin/activate && uv run pytest tests/test_admin_system.py tests/test_admin_vision_models.py tests/test_admin_feedback_router.py tests/test_admin_runtime_config.py -q`
Expected: PASS (baseline before migration).

- [ ] **Step 2: Write the failing shell assertion**

Add to `tests/test_admin_system.py` (it has an `admin_client` fixture that mocks a `system_admin` user):

```python
def test_system_dashboard_uses_unified_shell(admin_client):
    resp = admin_client.get("/admin/system/")
    assert resp.status_code == 200
    # Unified app sidebar (global Claims link) is present...
    assert 'href="/dashboard"' in resp.text
    # ...the Admin group is rendered...
    assert 'href="/admin/system/audit"' in resp.text
    # ...and the old dark admin chrome is gone.
    assert "bg-admin-800" not in resp.text
```

- [ ] **Step 3: Run it to verify it fails**

Run: `source .venv/bin/activate && uv run pytest tests/test_admin_system.py::test_system_dashboard_uses_unified_shell -v`
Expected: FAIL — the page still extends `admin/base.html` (`bg-admin-800` present, no `/dashboard` global link).

- [ ] **Step 4: Migrate each of the 12 templates**

For **each** file listed above, make exactly two edits, leaving `{% block title %}` and `{% block content %}` and all other markup unchanged:

1. Change the first line `{% extends "admin/base.html" %}` → `{% extends "base.html" %}`.
2. Delete the entire `{% block sidebar %} … {% endblock %}` region (the nav-link block; it is always directly after the `title` block).

Example — `admin/system/dashboard.html` before:

```html
{% extends "admin/base.html" %}
{% block title %}System Dashboard{% endblock %}
{% block sidebar %}
<a href="/admin/system/" class="block px-3 py-2 rounded-sm text-sm bg-admin-700 text-white">Dashboard</a>
... (several nav links) ...
{% endblock %}
{% block content %}
...
{% endblock %}
```

after:

```html
{% extends "base.html" %}
{% block title %}System Dashboard{% endblock %}
{% block content %}
...
{% endblock %}
```

- [ ] **Step 5: Rebuild CSS**

Run: `source .venv/bin/activate && uv run css`
Expected: `Done in NNms`, no errors.

- [ ] **Step 6: Run system tests + the new shell assertion**

Run: `source .venv/bin/activate && uv run pytest tests/test_admin_system.py tests/test_admin_vision_models.py tests/test_admin_feedback_router.py tests/test_admin_runtime_config.py -q`
Expected: all PASS, including `test_system_dashboard_uses_unified_shell`. If any page 500s, fix the render (a missing context var) — do not weaken assertions.

- [ ] **Step 7: Guard + format/lint + commit**

```bash
source .venv/bin/activate && python scripts/audit_design_tokens.py && \
uv run ruff format . && uv run ruff format --check . && uv run ruff check .
git add src/claimos/templates/admin/system/ src/claimos/templates/admin/vision_models.html tests/test_admin_system.py
git commit -m "refactor: migrate system + vision admin pages to unified app shell

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Migrate Internal admin pages to the app shell

**Files (modify — 7 templates):**
- `src/claimos/templates/admin/internal/claim_access.html`
- `src/claimos/templates/admin/internal/claims.html`
- `src/claimos/templates/admin/internal/dashboard.html`
- `src/claimos/templates/admin/internal/group_detail.html`
- `src/claimos/templates/admin/internal/groups.html`
- `src/claimos/templates/admin/internal/user_detail.html`
- `src/claimos/templates/admin/internal/users.html`
- Test: `tests/test_admin_internal.py` (add one shell assertion)

- [ ] **Step 1: Baseline — existing internal tests green**

Run: `source .venv/bin/activate && uv run pytest tests/test_admin_internal.py -q`
Expected: PASS.

- [ ] **Step 2: Write the failing shell assertion**

Add to `tests/test_admin_internal.py`, reusing the existing `internal_client` fixture (defined at line ~28; mocks an authenticated `internal_admin` user):

```python
def test_internal_dashboard_uses_unified_shell(internal_client):
    resp = internal_client.get("/admin/internal/")
    assert resp.status_code == 200
    assert 'href="/dashboard"' in resp.text
    assert 'href="/admin/internal/users"' in resp.text
    assert "bg-admin-800" not in resp.text
```

- [ ] **Step 3: Run it to verify it fails**

Run: `source .venv/bin/activate && uv run pytest tests/test_admin_internal.py::test_internal_dashboard_uses_unified_shell -v`
Expected: FAIL — page still on `admin/base.html`.

- [ ] **Step 4: Migrate each of the 7 templates**

For each file: change `{% extends "admin/base.html" %}` → `{% extends "base.html" %}` and delete the `{% block sidebar %} … {% endblock %}` region. Leave `title`/`content` unchanged. (Same transformation as Task 2 Step 4.)

- [ ] **Step 5: Rebuild CSS**

Run: `source .venv/bin/activate && uv run css`
Expected: `Done in NNms`.

- [ ] **Step 6: Run internal tests**

Run: `source .venv/bin/activate && uv run pytest tests/test_admin_internal.py -q`
Expected: all PASS incl. the new shell assertion. Fix any 500 by supplying the missing render context, not by weakening assertions.

- [ ] **Step 7: Guard + format/lint + commit**

```bash
source .venv/bin/activate && python scripts/audit_design_tokens.py && \
uv run ruff format . && uv run ruff format --check . && uv run ruff check .
git add src/claimos/templates/admin/internal/ tests/test_admin_internal.py
git commit -m "refactor: migrate internal admin pages to unified app shell

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Migrate Org admin pages to the app shell

Org pages carry a `group_id` query param and pass `group` in context; the
Task-1 admin nav already renders `?group_id={{ group.id }}` for `external_admin`.

**Files (modify — 7 templates):**
- `src/claimos/templates/admin/org/claim_access.html`
- `src/claimos/templates/admin/org/claims.html`
- `src/claimos/templates/admin/org/dashboard.html`
- `src/claimos/templates/admin/org/group_selector.html`
- `src/claimos/templates/admin/org/profile.html`
- `src/claimos/templates/admin/org/user_detail.html`
- `src/claimos/templates/admin/org/users.html`
- Test: `tests/test_admin_org.py` (add one shell assertion)

- [ ] **Step 1: Baseline — existing org tests green**

Run: `source .venv/bin/activate && uv run pytest tests/test_admin_org.py -q`
Expected: PASS.

- [ ] **Step 2: Write the failing shell assertion**

Add to `tests/test_admin_org.py`, reusing the existing `org_client` fixture (line ~28; mocks an `external_admin` user whose `group_id` is `"eg"`). `GET /admin/org/` resolves that group without a query param (see `test_org_dashboard_accessible`), so the org nav renders `?group_id=eg`:

```python
def test_org_dashboard_uses_unified_shell(org_client):
    resp = org_client.get("/admin/org/")
    assert resp.status_code == 200
    assert 'href="/dashboard"' in resp.text
    assert 'href="/admin/org/users?group_id=eg"' in resp.text
    assert "bg-admin-800" not in resp.text
```

- [ ] **Step 3: Run it to verify it fails**

Run: `source .venv/bin/activate && uv run pytest tests/test_admin_org.py::test_org_dashboard_uses_unified_shell -v`
Expected: FAIL — page still on `admin/base.html`.

- [ ] **Step 4: Migrate each of the 7 templates**

Same transformation as Task 2 Step 4: swap `extends`, delete the `sidebar` block, leave `title`/`content`.

- [ ] **Step 5: Rebuild CSS**

Run: `source .venv/bin/activate && uv run css`
Expected: `Done in NNms`.

- [ ] **Step 6: Run org tests**

Run: `source .venv/bin/activate && uv run pytest tests/test_admin_org.py -q`
Expected: all PASS incl. the new shell assertion.

- [ ] **Step 7: Guard + format/lint + commit**

```bash
source .venv/bin/activate && python scripts/audit_design_tokens.py && \
uv run ruff format . && uv run ruff format --check . && uv run ruff check .
git add src/claimos/templates/admin/org/ tests/test_admin_org.py
git commit -m "refactor: migrate org admin pages to unified app shell

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Delete `admin/base.html`, mark dead tokens, update DESIGN.md, full verify

**Files:**
- Delete: `src/claimos/templates/admin/base.html`
- Modify: `src/claimos/styles/theme.css` (comment)
- Modify: `DESIGN.md`

- [ ] **Step 1: Confirm nothing still extends the admin shell**

Run: `grep -rn 'admin/base.html' src/claimos/templates/`
Expected: **no output** (all 26 pages migrated in Tasks 2–4). If any remain, migrate them (Task 2 Step 4 transformation) before continuing.

- [ ] **Step 2: Delete the admin shell**

```bash
git rm src/claimos/templates/admin/base.html
```

- [ ] **Step 3: Mark `admin-*` tokens dead in `src/claimos/styles/theme.css`**

Change the admin-chrome comment line:

```css
  /* Admin chrome — near-black navy (dark in both modes, matches mockup sidebar) */
```

to:

```css
  /* Admin chrome — DEAD after the unified-shell migration (no template references
     these tokens anymore); retained pending a follow-up purge. */
```

Leave the `--color-admin-*` declarations themselves unchanged (removing them would require touching the token tests; out of scope).

- [ ] **Step 4: Update `DESIGN.md`**

Open `DESIGN.md`, find the passage describing the "dark slate admin chrome" as a distinct surface, and replace it with a note that the admin area now uses the shared app shell (`base.html` topbar + theme-aware left sidebar) with a role-aware Admin sidebar group (`_admin_sidebar.html`), and that the `--color-admin-*` tokens are retained but unused pending removal. Keep the surrounding structure/headings intact; change only that passage.

- [ ] **Step 5: Rebuild CSS + full verification**

Run:
```bash
source .venv/bin/activate && \
uv run css && \
python scripts/audit_design_tokens.py && \
uv run pytest -q && \
uv run ruff format . && uv run ruff format --check . && uv run ruff check .
```
Expected: CSS builds clean; guard `clean ✓`; **full suite green**; ruff clean, zero reformatting.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor: delete admin/base.html; mark admin-* tokens dead; update DESIGN.md

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Manual verification (after all tasks)

```bash
source .venv/bin/activate
uv run css
uv run dev   # http://localhost:8000 (or the printed port)
```

Log in as each admin role (system / internal / external) and open its landing
page. Confirm: same topbar + theme-aware sidebar as the app; global
Dashboard/Claims at the top; an **Admin** group with the role's links and correct
active highlighting; System/Light/Dark toggle makes the admin sidebar light in
light mode / dark in dark mode; org pages keep their `?group_id=` links; deep
pages (e.g. a user detail) show their breadcrumb trail in the topbar.

## Self-review notes

- **Spec coverage:** retire admin/base.html + migrate 26 pages (Tasks 2–5) ✓;
  `_admin_sidebar.html` role-aware nav with macro (Task 1 Step 3) ✓; Admin group
  gated under `/admin/` in `_app_sidebar.html` (Task 1 Step 4) ✓; topbar
  breadcrumbs + `panel_title` default (Task 1 Step 5) ✓; org `group_id` handling
  (Task 1 Step 3 + Task 4) ✓; dead `admin-*` token comment (Task 5 Step 3) ✓;
  DESIGN.md (Task 5 Step 4) ✓; tests (Task 1 Step 1, Tasks 2–4 shell assertions)
  ✓; feedback widget now in admin — inherent to `base.html`, no action needed.
- **No placeholders:** the migration transformation is fully specified once and
  applied over explicit file lists; every new file/edit shows complete code.
- **Type consistency:** the admin nav macro `item(href, label, active, badge=0)`
  is defined and used consistently; `_render_admin`/`_render_app_sidebar` test
  helpers match the partials' expected context (`request`, `user`, `group`,
  `unread_count`, `claim`).
