# Phase 3: Admin Panels — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build three admin panels (System, Internal, External) for managing users, groups, matters, and access grants through the web UI.

**Architecture:** Three separate router files under `src/cvp/routers/admin/`, each mounted at its own URL prefix. Shared admin base template with sidebar nav. Cascading access: System Admins see all panels, Internal Admins see Internal + External, External Admins see only External (scoped to their group).

**Tech Stack:** FastAPI routers, Jinja2 templates, HTMX, Tailwind CDN

**Spec:** `docs/superpowers/specs/2026-04-25-auth-rbac-design.md` (Section 7)

**Prerequisite:** Phases 1 and 2 must be complete.

---

## File Structure

### New files to create:
- `src/cvp/routers/admin/__init__.py`
- `src/cvp/routers/admin/system.py` — System Admin router (`/admin/system/`)
- `src/cvp/routers/admin/internal.py` — Internal Admin router (`/admin/internal/`)
- `src/cvp/routers/admin/org.py` — External Admin router (`/admin/org/`)
- `src/cvp/templates/admin/base.html` — Shared admin layout with sidebar
- `src/cvp/templates/admin/system/dashboard.html`
- `src/cvp/templates/admin/system/users.html`
- `src/cvp/templates/admin/system/user_detail.html`
- `src/cvp/templates/admin/system/groups.html`
- `src/cvp/templates/admin/system/group_detail.html`
- `src/cvp/templates/admin/system/matters.html`
- `src/cvp/templates/admin/internal/dashboard.html`
- `src/cvp/templates/admin/internal/users.html`
- `src/cvp/templates/admin/internal/user_detail.html`
- `src/cvp/templates/admin/internal/matters.html`
- `src/cvp/templates/admin/internal/matter_access.html`
- `src/cvp/templates/admin/internal/groups.html`
- `src/cvp/templates/admin/internal/group_detail.html`
- `src/cvp/templates/admin/org/dashboard.html`
- `src/cvp/templates/admin/org/users.html`
- `src/cvp/templates/admin/org/user_detail.html`
- `src/cvp/templates/admin/org/matters.html`
- `src/cvp/templates/admin/org/matter_access.html`
- `src/cvp/templates/admin/org/profile.html`
- `src/cvp/templates/admin/_invite_form.html` — Shared invite creation partial
- `tests/test_admin_system.py`
- `tests/test_admin_internal.py`
- `tests/test_admin_org.py`

### Files to modify:
- `src/cvp/main.py` — Mount admin routers
- `src/cvp/templates/base.html` — Add admin panel links based on user role

---

### Task 1: Create admin base template

**Files:**
- Create: `src/cvp/templates/admin/base.html`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p src/cvp/templates/admin/system src/cvp/templates/admin/internal src/cvp/templates/admin/org
```

- [ ] **Step 2: Create admin base template**

Create `src/cvp/templates/admin/base.html`:

```html
<!doctype html>
<html lang="en" class="h-full bg-gray-100">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{% block title %}Admin{% endblock %} — CVP</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://unpkg.com/htmx.org@1.9.12"></script>
  <script>
    document.addEventListener('DOMContentLoaded', function() {
      var csrf = document.cookie.split('; ').find(c => c.startsWith('cvp_csrf='));
      if (csrf) {
        document.body.setAttribute('hx-headers', JSON.stringify({'X-CSRF-Token': csrf.split('=')[1]}));
      }
    });
  </script>
</head>
<body class="h-full">
  <div class="flex h-full">
    <!-- Sidebar -->
    <div class="w-64 bg-{{ panel_color }}-900 text-white flex flex-col">
      <div class="p-4 border-b border-{{ panel_color }}-800">
        <h2 class="text-lg font-semibold">{{ panel_title }}</h2>
        <p class="text-xs text-{{ panel_color }}-300 mt-1">{{ user.email }}</p>
      </div>
      <nav class="flex-1 p-4 space-y-1">
        {% block sidebar %}{% endblock %}
      </nav>
      <div class="p-4 border-t border-{{ panel_color }}-800 space-y-1">
        <a href="/dashboard" class="block text-sm text-{{ panel_color }}-300 hover:text-white">Back to app</a>
        {% if user.system_role == "system_admin" %}
        <a href="/admin/system/" class="block text-sm text-{{ panel_color }}-300 hover:text-white">System Admin</a>
        <a href="/admin/internal/" class="block text-sm text-{{ panel_color }}-300 hover:text-white">Internal Admin</a>
        <a href="/admin/org/" class="block text-sm text-{{ panel_color }}-300 hover:text-white">Org Admin</a>
        {% elif user.system_role == "internal_admin" %}
        <a href="/admin/internal/" class="block text-sm text-{{ panel_color }}-300 hover:text-white">Internal Admin</a>
        <a href="/admin/org/" class="block text-sm text-{{ panel_color }}-300 hover:text-white">Org Admin</a>
        {% endif %}
        <form method="POST" action="/api/auth/logout" class="inline">
          <button type="submit" class="block text-sm text-{{ panel_color }}-300 hover:text-white">Sign out</button>
        </form>
      </div>
    </div>
    <!-- Main content -->
    <div class="flex-1 overflow-auto">
      <div class="p-8">
        {% if breadcrumbs %}
        <nav class="mb-4 text-sm text-gray-500">
          {% for crumb in breadcrumbs %}
          {% if not loop.last %}
          <a href="{{ crumb.url }}" class="hover:text-gray-700">{{ crumb.label }}</a> /
          {% else %}
          <span class="text-gray-900">{{ crumb.label }}</span>
          {% endif %}
          {% endfor %}
        </nav>
        {% endif %}
        {% block content %}{% endblock %}
      </div>
    </div>
  </div>
</body>
</html>
```

- [ ] **Step 3: Commit**

```bash
git add src/cvp/templates/admin/
git commit -m "feat: admin base template with sidebar nav"
```

---

### Task 2: Create System Admin router and pages

**Files:**
- Create: `src/cvp/routers/admin/__init__.py`
- Create: `src/cvp/routers/admin/system.py`
- Create: Templates in `src/cvp/templates/admin/system/`
- Test: `tests/test_admin_system.py`

- [ ] **Step 1: Create __init__.py**

Create empty `src/cvp/routers/admin/__init__.py`.

- [ ] **Step 2: Write the failing test**

Create `tests/test_admin_system.py`:

```python
"""Tests for System Admin panel."""

import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient

from cvp.dependencies import require_system_admin, CurrentUser


@pytest.fixture
def admin_client():
    from cvp.main import app

    async def mock_admin():
        return CurrentUser(
            id="sa", email="sa@test.com", system_role="system_admin",
            group_id="ig", group_kind="internal",
        )

    app.dependency_overrides[require_system_admin] = mock_admin
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_system_dashboard_accessible(admin_client):
    resp = admin_client.get("/admin/system/")
    assert resp.status_code == 200


def test_system_users_page(admin_client):
    resp = admin_client.get("/admin/system/users")
    assert resp.status_code == 200
```

- [ ] **Step 3: Create system admin router**

Create `src/cvp/routers/admin/system.py` with routes for:
- `GET /admin/system/` — dashboard
- `GET /admin/system/users` — user list
- `GET /admin/system/users/{user_id}` — user detail
- `POST /admin/system/users/invite` — create invite
- `POST /admin/system/users/{user_id}/deactivate` — deactivate user
- `POST /admin/system/users/{user_id}/activate` — activate user
- `POST /admin/system/users/{user_id}/reset-mfa` — reset MFA
- `GET /admin/system/groups` — group list
- `POST /admin/system/groups` — create group
- `GET /admin/system/groups/{group_id}` — group detail
- `POST /admin/system/groups/{group_id}/deactivate` — deactivate group
- `GET /admin/system/matters` — all matters list

All routes guarded by `Depends(require_system_admin)`.

Each route renders its corresponding template from `src/cvp/templates/admin/system/`.

The router sets `panel_color="slate"` and `panel_title="System Administration"` in all template contexts.

- [ ] **Step 4: Create system admin templates**

Create dashboard, users list, user detail, groups list, group detail, and matters list templates. Each extends `admin/base.html` and provides `sidebar` and `content` blocks.

The sidebar should contain links to: Dashboard, Users, Groups, Matters.

The invite creation form should collect: email, display_name, system_role (dropdown), group_id (dropdown). It POSTs to `/admin/system/users/invite` and displays the generated invite URL on success.

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_admin_system.py -v`

- [ ] **Step 6: Commit**

```bash
git add src/cvp/routers/admin/ src/cvp/templates/admin/system/ tests/test_admin_system.py
git commit -m "feat: System Admin panel — dashboard, users, groups, matters"
```

---

### Task 3: Create Internal Admin router and pages

**Files:**
- Create: `src/cvp/routers/admin/internal.py`
- Create: Templates in `src/cvp/templates/admin/internal/`
- Test: `tests/test_admin_internal.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_admin_internal.py` with fixture that overrides `require_active_user` to return an internal_admin user. Test that `/admin/internal/` returns 200.

- [ ] **Step 2: Create internal admin router**

Create `src/cvp/routers/admin/internal.py` with routes for:
- `GET /admin/internal/` — dashboard
- `GET /admin/internal/users` — Internal Users list
- `GET /admin/internal/users/{user_id}` — user detail
- `POST /admin/internal/users/invite` — create Internal User invite
- `GET /admin/internal/matters` — matters the Internal group owns or has access to
- `GET /admin/internal/matters/{matter_id}/access` — manage access for a matter
- `GET /admin/internal/groups` — External groups list
- `POST /admin/internal/groups` — create External group
- `GET /admin/internal/groups/{group_id}` — External group detail
- `POST /admin/internal/groups/{group_id}/invite-admin` — create External Admin invite

Guard: require `system_role in ("system_admin", "internal_admin")`. Use a custom dependency.

The router sets `panel_color="indigo"` and `panel_title="Internal Administration"`.

- [ ] **Step 3: Create internal admin templates**

Create templates extending `admin/base.html`. The matter access page should show a list of users with access and a form to grant new access (user search/dropdown + role dropdown).

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_admin_internal.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/cvp/routers/admin/internal.py src/cvp/templates/admin/internal/ tests/test_admin_internal.py
git commit -m "feat: Internal Admin panel — users, matters, external groups"
```

---

### Task 4: Create External Admin (Org) router and pages

**Files:**
- Create: `src/cvp/routers/admin/org.py`
- Create: Templates in `src/cvp/templates/admin/org/`
- Test: `tests/test_admin_org.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_admin_org.py` with fixture that overrides auth to return an external_admin user. Test `/admin/org/` returns 200.

- [ ] **Step 2: Create org admin router**

Create `src/cvp/routers/admin/org.py` with routes for:
- `GET /admin/org/` — dashboard (with group selector for System/Internal admins)
- `GET /admin/org/users` — group's users
- `GET /admin/org/users/{user_id}` — user detail
- `POST /admin/org/users/invite` — create External User invite
- `GET /admin/org/matters` — group's matters (owned + shared)
- `GET /admin/org/matters/{matter_id}/access` — manage per-user access for group members
- `GET /admin/org/profile` — group profile
- `POST /admin/org/profile` — update group profile

Guard: require `system_role in ("system_admin", "internal_admin", "external_admin")`.

**Group scoping logic:**
- External Admin: always scoped to their own `group_id`
- Internal Admin: query param `?group_id=X` selects which External group (filtered to groups sharing matters with Internal group)
- System Admin: query param `?group_id=X` selects any External group

If System/Internal admin visits without `?group_id`, show a group selector page.

The router sets `panel_color="emerald"` and `panel_title="Organization Administration"`.

- [ ] **Step 3: Create org admin templates**

Create templates. The group selector page should list available External groups as clickable cards.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_admin_org.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/cvp/routers/admin/org.py src/cvp/templates/admin/org/ tests/test_admin_org.py
git commit -m "feat: External Admin (Org) panel — users, matters, profile"
```

---

### Task 5: Mount admin routers and add nav links

**Files:**
- Modify: `src/cvp/main.py`
- Modify: `src/cvp/templates/base.html`

- [ ] **Step 1: Mount admin routers in main.py**

```python
from cvp.routers.admin import system as admin_system, internal as admin_internal, org as admin_org

app.include_router(admin_system.router)
app.include_router(admin_internal.router)
app.include_router(admin_org.router)
```

- [ ] **Step 2: Add admin links to base.html nav**

In the nav bar, after the user info, add admin panel links based on `user.system_role`:

```html
{% if user %}
  {% if user.system_role == "system_admin" %}
  <a href="/admin/system/" class="text-sm text-gray-500 hover:text-gray-700">Admin</a>
  {% elif user.system_role == "internal_admin" %}
  <a href="/admin/internal/" class="text-sm text-gray-500 hover:text-gray-700">Admin</a>
  {% elif user.system_role == "external_admin" %}
  <a href="/admin/org/" class="text-sm text-gray-500 hover:text-gray-700">Admin</a>
  {% endif %}
{% endif %}
```

- [ ] **Step 3: Run full tests**

Run: `uv run pytest -v`

- [ ] **Step 4: Commit**

```bash
git add src/cvp/main.py src/cvp/templates/base.html
git commit -m "feat: mount admin routers, add admin nav links"
```

---

### Task 6: Final verification

- [ ] **Step 1: Run full test suite and linter**

```bash
uv run pytest -v
uv run ruff check . && uv run ruff format --check .
```

- [ ] **Step 2: Manual smoke test**

1. Log in as System Admin — verify all three admin panels accessible
2. Create an External group from Internal Admin panel
3. Create an External Admin via invite
4. Log in as External Admin — verify only Org panel accessible
5. Verify External Admin can't see other groups' data
6. Create an Internal User invite from Internal Admin panel
7. Verify cascading access works (System Admin can access all panels)

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "chore: phase 3 complete — admin panels"
```
