# Regenerate Invite Link — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let system admins and internal admins generate a fresh invite link for any existing user from the user detail page.

**Architecture:** Two new POST endpoints (one per admin panel) generate a fresh invite code, extend expiry 7 days, clear `password_changed_at`, write an audit log, and re-render the user detail template with the new URL in a green banner. Both user detail templates get the banner and a "Regenerate Invite Link" button. No schema changes needed.

**Tech Stack:** FastAPI, SQLAlchemy 2.x, Jinja2, Tailwind via CDN, pytest. Run commands via `uv run`.

---

## File Map

| File | Action |
|---|---|
| `src/cvp/routers/admin/system.py` | Add `system_regenerate_invite` endpoint |
| `src/cvp/routers/admin/internal.py` | Add `internal_regenerate_invite` endpoint + audit imports |
| `src/cvp/templates/admin/system/user_detail.html` | Add invite_url banner + Regenerate button |
| `src/cvp/templates/admin/internal/user_detail.html` | Add invite_url banner + Regenerate button |
| `tests/test_admin_system.py` | Add regenerate-invite tests |
| `tests/test_admin_internal.py` | Add regenerate-invite tests + seeded fixture |

---

### Task 1: System admin regenerate-invite endpoint + template

**Files:**
- Modify: `tests/test_admin_system.py`
- Modify: `src/cvp/routers/admin/system.py`
- Modify: `src/cvp/templates/admin/system/user_detail.html`

- [ ] **Step 1: Write the failing tests**

Append these three tests to `tests/test_admin_system.py`:

```python
def test_system_regenerate_invite_updates_code(seeded_client):
    from datetime import datetime, timezone

    client, db = seeded_client
    # Mark user as already registered so we can confirm password_changed_at is cleared
    user = db.get(User, "existing-user-id")
    user.password_changed_at = datetime.now(tz=timezone.utc)
    db.commit()

    resp = client.post("/admin/system/users/existing-user-id/regenerate-invite")
    assert resp.status_code == 200
    assert "register/" in resp.text

    db.expire_all()
    user = db.get(User, "existing-user-id")
    assert user.invite_code is not None
    assert user.invite_expires_at is not None
    assert user.password_changed_at is None


def test_system_regenerate_invite_unknown_user_returns_404(seeded_client):
    client, _ = seeded_client
    resp = client.post("/admin/system/users/does-not-exist/regenerate-invite")
    assert resp.status_code == 404


def test_system_regenerate_invite_replaces_old_code(seeded_client):
    from cvp.auth import generate_invite_code, hash_token

    client, db = seeded_client
    user = db.get(User, "existing-user-id")
    old_hash = hash_token(generate_invite_code())
    user.invite_code = old_hash
    db.commit()

    resp = client.post("/admin/system/users/existing-user-id/regenerate-invite")
    assert resp.status_code == 200

    db.expire_all()
    user = db.get(User, "existing-user-id")
    assert user.invite_code != old_hash
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
source .venv/bin/activate && uv run pytest tests/test_admin_system.py::test_system_regenerate_invite_updates_code tests/test_admin_system.py::test_system_regenerate_invite_unknown_user_returns_404 tests/test_admin_system.py::test_system_regenerate_invite_replaces_old_code -v
```

Expected: all three FAIL with `404 Not Found` or route-not-found errors.

- [ ] **Step 3: Implement the endpoint**

Add this function to `src/cvp/routers/admin/system.py`, after the `system_reset_mfa` function (around line 222):

```python
@router.post("/users/{user_id}/regenerate-invite", response_class=HTMLResponse)
def system_regenerate_invite(
    user_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")

    raw_code = generate_invite_code()
    now_utc = datetime.datetime.now(tz=datetime.timezone.utc)
    target.invite_code = hash_token(raw_code)
    target.invite_expires_at = now_utc + datetime.timedelta(days=7)
    target.password_changed_at = None
    db.commit()

    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="admin.invite_regenerated",
        resource_type="user",
        resource_id=user_id,
        ip_address=get_client_ip(request),
    )

    invite_url = str(request.base_url).rstrip("/") + f"/register/{raw_code}"
    group = db.get(Group, target.group_id) if target.group_id else None
    return templates.TemplateResponse(
        request=request,
        name="admin/system/user_detail.html",
        context=_ctx(
            user,
            target=target,
            group=group,
            invite_url=invite_url,
            breadcrumbs=[
                {"label": "System Admin", "url": "/admin/system/"},
                {"label": "Users", "url": "/admin/system/users"},
                {"label": target.email, "url": f"/admin/system/users/{user_id}"},
            ],
        ),
    )
```

All imports used (`generate_invite_code`, `hash_token`, `BackgroundTasks`, `write_audit_log`, `get_client_ip`, `Group`) are already present at the top of `system.py`.

- [ ] **Step 4: Run tests to confirm they pass**

```bash
source .venv/bin/activate && uv run pytest tests/test_admin_system.py::test_system_regenerate_invite_updates_code tests/test_admin_system.py::test_system_regenerate_invite_unknown_user_returns_404 tests/test_admin_system.py::test_system_regenerate_invite_replaces_old_code -v
```

Expected: all three PASS.

- [ ] **Step 5: Update the system user detail template**

Replace the content of `src/cvp/templates/admin/system/user_detail.html` with:

```html
{% extends "admin/base.html" %}
{% block title %}User: {{ target.email }}{% endblock %}
{% block sidebar %}
<a href="/admin/system/" class="block px-3 py-2 rounded text-sm text-slate-300 hover:bg-slate-700 hover:text-white">Dashboard</a>
<a href="/admin/system/users" class="block px-3 py-2 rounded text-sm bg-slate-700 text-white">Users</a>
<a href="/admin/system/groups" class="block px-3 py-2 rounded text-sm text-slate-300 hover:bg-slate-700 hover:text-white">Groups</a>
<a href="/admin/system/matters" class="block px-3 py-2 rounded text-sm text-slate-300 hover:bg-slate-700 hover:text-white">Matters</a>
<a href="/admin/system/audit" class="block px-3 py-2 rounded text-sm text-slate-300 hover:bg-slate-700 hover:text-white">Audit Log</a>
<a href="/admin/vision-models" class="block px-3 py-2 rounded text-sm text-slate-300 hover:bg-slate-700 hover:text-white">Vision Models</a>
{% endblock %}
{% block content %}
<h1 class="text-2xl font-bold text-gray-900 mb-6">{{ target.email }}</h1>
{% if invite_url %}
<div class="mb-6 p-4 bg-green-50 border border-green-200 rounded-lg">
  <p class="text-sm font-medium text-green-800">New invite link (valid 7 days):</p>
  <p class="mt-1 text-sm text-green-700 font-mono break-all">{{ invite_url }}</p>
</div>
{% endif %}
<div class="bg-white shadow rounded-lg p-6 mb-6">
  <dl class="grid grid-cols-2 gap-4">
    <div><dt class="text-sm text-gray-500">Display Name</dt><dd class="text-sm font-medium text-gray-900">{{ target.display_name }}</dd></div>
    <div><dt class="text-sm text-gray-500">Role</dt><dd class="text-sm font-medium text-gray-900">{{ target.system_role }}</dd></div>
    <div><dt class="text-sm text-gray-500">Status</dt><dd class="text-sm font-medium">{% if target.is_active %}<span class="text-green-700">Active</span>{% else %}<span class="text-red-600">Inactive</span>{% endif %}</dd></div>
    <div><dt class="text-sm text-gray-500">Group</dt><dd class="text-sm font-medium text-gray-900">{% if group %}{{ group.name }}{% else %}—{% endif %}</dd></div>
    <div><dt class="text-sm text-gray-500">MFA</dt><dd class="text-sm font-medium text-gray-900">{% if target.mfa_enabled %}Enabled{% else %}Disabled{% endif %}</dd></div>
  </dl>
</div>
<div class="flex gap-3">
  {% if target.is_active %}
  <form method="POST" action="/admin/system/users/{{ target.id }}/deactivate">
    <button type="submit" class="bg-red-600 text-white px-4 py-2 rounded text-sm hover:bg-red-700">Deactivate</button>
  </form>
  {% else %}
  <form method="POST" action="/admin/system/users/{{ target.id }}/activate">
    <button type="submit" class="bg-green-600 text-white px-4 py-2 rounded text-sm hover:bg-green-700">Activate</button>
  </form>
  {% endif %}
  {% if target.mfa_enabled %}
  <form method="POST" action="/admin/system/users/{{ target.id }}/reset-mfa">
    <button type="submit" class="bg-amber-600 text-white px-4 py-2 rounded text-sm hover:bg-amber-700">Reset MFA</button>
  </form>
  {% endif %}
  <form method="POST" action="/admin/system/users/{{ target.id }}/regenerate-invite">
    <button type="submit" class="bg-indigo-600 text-white px-4 py-2 rounded text-sm hover:bg-indigo-700">Regenerate Invite Link</button>
  </form>
</div>
{% endblock %}
```

- [ ] **Step 6: Run the full system admin test suite**

```bash
source .venv/bin/activate && uv run pytest tests/test_admin_system.py -v
```

Expected: all tests PASS.

- [ ] **Step 7: Commit**

```bash
git add tests/test_admin_system.py src/cvp/routers/admin/system.py src/cvp/templates/admin/system/user_detail.html
git commit -m "feat: add regenerate invite link to system admin user detail"
```

---

### Task 2: Internal admin regenerate-invite endpoint + template

**Files:**
- Modify: `tests/test_admin_internal.py`
- Modify: `src/cvp/routers/admin/internal.py`
- Modify: `src/cvp/templates/admin/internal/user_detail.html`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_admin_internal.py`. First add a seeded fixture with a user in the admin's group and a user in a different group, then add three tests:

```python
@pytest.fixture
def seeded_internal_client(db_session):
    from cvp.db import get_db
    from cvp.main import app
    from cvp.models_auth import User

    ig = Group(id="ig", name="Internal", kind="internal")
    other_group = Group(id="og", name="Other", kind="external")
    db_session.add(ig)
    db_session.add(other_group)

    target_user = User(
        id="target-user-id",
        email="target@test.com",
        display_name="Target",
        system_role="internal_user",
        group_id="ig",
        is_active=True,
    )
    outsider = User(
        id="outsider-id",
        email="outsider@test.com",
        display_name="Outsider",
        system_role="external_user",
        group_id="og",
        is_active=True,
    )
    db_session.add(target_user)
    db_session.add(outsider)
    db_session.commit()

    def override_get_db():
        yield db_session

    async def mock_internal_admin():
        from cvp.dependencies import CurrentUser

        return CurrentUser(
            id="ia",
            email="ia@test.com",
            system_role="internal_admin",
            group_id="ig",
            group_kind="internal",
        )

    from cvp.dependencies import require_active_user
    from cvp.routers.admin.internal import _require_internal_or_above

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_active_user] = mock_internal_admin
    app.dependency_overrides[_require_internal_or_above] = mock_internal_admin
    with TestClient(app) as c:
        yield c, db_session
    app.dependency_overrides.clear()


def test_internal_regenerate_invite_updates_code(seeded_internal_client):
    from datetime import datetime, timezone
    from cvp.models_auth import User

    client, db = seeded_internal_client
    user = db.get(User, "target-user-id")
    user.password_changed_at = datetime.now(tz=timezone.utc)
    db.commit()

    resp = client.post("/admin/internal/users/target-user-id/regenerate-invite")
    assert resp.status_code == 200
    assert "register/" in resp.text

    db.expire_all()
    user = db.get(User, "target-user-id")
    assert user.invite_code is not None
    assert user.invite_expires_at is not None
    assert user.password_changed_at is None


def test_internal_regenerate_invite_unknown_user_returns_404(seeded_internal_client):
    client, _ = seeded_internal_client
    resp = client.post("/admin/internal/users/does-not-exist/regenerate-invite")
    assert resp.status_code == 404


def test_internal_regenerate_invite_outside_group_returns_404(seeded_internal_client):
    client, _ = seeded_internal_client
    resp = client.post("/admin/internal/users/outsider-id/regenerate-invite")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
source .venv/bin/activate && uv run pytest tests/test_admin_internal.py::test_internal_regenerate_invite_updates_code tests/test_admin_internal.py::test_internal_regenerate_invite_unknown_user_returns_404 tests/test_admin_internal.py::test_internal_regenerate_invite_outside_group_returns_404 -v
```

Expected: all three FAIL with route-not-found errors.

- [ ] **Step 3: Add audit imports to internal.py**

In `src/cvp/routers/admin/internal.py`, update the FastAPI import line from:

```python
from fastapi import APIRouter, Depends, Form, HTTPException
```

to:

```python
from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException
```

And add the audit import after the existing imports (after the `from cvp.models_auth import Group, User` line):

```python
from cvp.services.audit import get_client_ip, write_audit_log
```

- [ ] **Step 4: Implement the endpoint**

Add this function to `src/cvp/routers/admin/internal.py`, after the `internal_deactivate_user` function (around line 139):

```python
@router.post("/users/{user_id}/regenerate-invite", response_class=HTMLResponse)
def internal_regenerate_invite(
    user_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(_require_internal_or_above),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    target = db.get(User, user_id)
    if target is None or target.group_id != user.group_id:
        raise HTTPException(status_code=404, detail="User not found")

    raw_code = generate_invite_code()
    now_utc = datetime.datetime.now(tz=datetime.timezone.utc)
    target.invite_code = hash_token(raw_code)
    target.invite_expires_at = now_utc + datetime.timedelta(days=7)
    target.password_changed_at = None
    db.commit()

    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="admin.invite_regenerated",
        resource_type="user",
        resource_id=user_id,
        ip_address=get_client_ip(request),
    )

    invite_url = str(request.base_url).rstrip("/") + f"/register/{raw_code}"
    return templates.TemplateResponse(
        request=request,
        name="admin/internal/user_detail.html",
        context=_ctx(
            user,
            target=target,
            invite_url=invite_url,
            breadcrumbs=[
                {"label": "Internal Admin", "url": "/admin/internal/"},
                {"label": "Users", "url": "/admin/internal/users"},
                {"label": target.email, "url": f"/admin/internal/users/{user_id}"},
            ],
        ),
    )
```

- [ ] **Step 5: Run tests to confirm they pass**

```bash
source .venv/bin/activate && uv run pytest tests/test_admin_internal.py::test_internal_regenerate_invite_updates_code tests/test_admin_internal.py::test_internal_regenerate_invite_unknown_user_returns_404 tests/test_admin_internal.py::test_internal_regenerate_invite_outside_group_returns_404 -v
```

Expected: all three PASS.

- [ ] **Step 6: Update the internal user detail template**

Replace the content of `src/cvp/templates/admin/internal/user_detail.html` with:

```html
{% extends "admin/base.html" %}
{% block title %}User: {{ target.email }}{% endblock %}
{% block sidebar %}
<a href="/admin/internal/" class="block px-3 py-2 rounded text-sm text-slate-300 hover:bg-slate-700 hover:text-white">Dashboard</a>
<a href="/admin/internal/users" class="block px-3 py-2 rounded text-sm bg-slate-700 text-white">Users</a>
<a href="/admin/internal/matters" class="block px-3 py-2 rounded text-sm text-slate-300 hover:bg-slate-700 hover:text-white">Matters</a>
<a href="/admin/internal/groups" class="block px-3 py-2 rounded text-sm text-slate-300 hover:bg-slate-700 hover:text-white">External Groups</a>
{% endblock %}
{% block content %}
<h1 class="text-2xl font-bold text-gray-900 mb-6">{{ target.email }}</h1>
{% if invite_url %}
<div class="mb-6 p-4 bg-green-50 border border-green-200 rounded-lg">
  <p class="text-sm font-medium text-green-800">New invite link (valid 7 days):</p>
  <p class="mt-1 text-sm text-green-700 font-mono break-all">{{ invite_url }}</p>
</div>
{% endif %}
<div class="bg-white shadow rounded-lg p-6 mb-6">
  <dl class="grid grid-cols-2 gap-4">
    <div><dt class="text-sm text-gray-500">Display Name</dt><dd class="text-sm font-medium text-gray-900">{{ target.display_name }}</dd></div>
    <div><dt class="text-sm text-gray-500">Role</dt><dd class="text-sm font-medium text-gray-900">{{ target.system_role }}</dd></div>
    <div><dt class="text-sm text-gray-500">Status</dt><dd class="text-sm font-medium">{% if target.is_active %}<span class="text-green-700">Active</span>{% else %}<span class="text-red-600">Inactive</span>{% endif %}</dd></div>
    <div><dt class="text-sm text-gray-500">MFA</dt><dd class="text-sm font-medium text-gray-900">{% if target.mfa_enabled %}Enabled{% else %}Disabled{% endif %}</dd></div>
  </dl>
</div>
<div class="flex gap-3">
  {% if target.is_active %}
  <form method="POST" action="/admin/internal/users/{{ target.id }}/deactivate">
    <button type="submit" class="bg-red-600 text-white px-4 py-2 rounded text-sm hover:bg-red-700">Deactivate</button>
  </form>
  {% else %}
  <form method="POST" action="/admin/internal/users/{{ target.id }}/activate">
    <button type="submit" class="bg-green-600 text-white px-4 py-2 rounded text-sm hover:bg-green-700">Activate</button>
  </form>
  {% endif %}
  <form method="POST" action="/admin/internal/users/{{ target.id }}/regenerate-invite">
    <button type="submit" class="bg-indigo-600 text-white px-4 py-2 rounded text-sm hover:bg-indigo-700">Regenerate Invite Link</button>
  </form>
</div>
{% endblock %}
```

- [ ] **Step 7: Run the full internal admin test suite**

```bash
source .venv/bin/activate && uv run pytest tests/test_admin_internal.py -v
```

Expected: all tests PASS.

- [ ] **Step 8: Run the full test suite and lint**

```bash
source .venv/bin/activate && uv run pytest -v && uv run ruff check . && uv run ruff format . && uv run ruff format --check .
```

Expected: all tests PASS, zero lint errors, zero files would be reformatted.

- [ ] **Step 9: Commit**

```bash
git add tests/test_admin_internal.py src/cvp/routers/admin/internal.py src/cvp/templates/admin/internal/user_detail.html
git commit -m "feat: add regenerate invite link to internal admin user detail"
```
