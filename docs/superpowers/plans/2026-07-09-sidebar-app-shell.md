# Sidebar App Shell Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the top-nav-only app chrome with a persistent left-sidebar + top-bar layout, add a new empty Dashboard page at `/`, without changing any page's content.

**Architecture:** Promote the existing `admin/base.html` sidebar pattern into the shared `base.html` (top bar → `aside` sidebar → `main`). A new `_app_sidebar.html` partial renders a global nav group always and a claim-scoped group only when a `claim` is in template context. The `/` route serves a new empty `home.html` for authenticated users (splash for anonymous), which requires making the `optional_user` dependency dev-auto-login-aware.

**Tech Stack:** FastAPI, Jinja2, Tailwind CSS v4 (standalone CLI), pytest.

## Global Constraints

- **Layout-only change.** No changes to data model, exports, depreciation, Vision, legal copy, or feature logic.
- **Use existing design-system tokens only** (DESIGN.md). No new colors, fonts, or radii. Sidebar/topbar must use semantic tokens (`bg-neutral-*`, `bg-surface`, `text-neutral-*`, `bg-primary-subtle`, `text-primary`, `border-neutral-200`) — never raw Tailwind color families. `scripts/audit_design_tokens.py` must stay clean.
- **No inline JS event handlers** (`onclick=` etc.). This plan adds no JS at all.
- **Type hints everywhere**; modern syntax (`X | None`). Pydantic/response conventions unchanged.
- **`uv run ruff format .` then `uv run ruff format --check .`** must show zero reformatting before every commit. Line length 100.
- **After any template change, run `uv run css`** to regenerate `src/claimos/static/app.css` (gitignored) so newly-used utility classes are emitted.
- PDF report (`report/pdf.html`) and admin shell (`admin/base.html`) are **not** touched.

---

### Task 1: Backend — dev-auto-login helper, `/` route, and empty Dashboard page

**Files:**
- Modify: `src/claimos/dependencies.py` (extract helper at lines 83–106; call it from `get_current_user` and `optional_user` at line 144)
- Modify: `src/claimos/routers/auth.py` (the `/` route `splash`, lines ~79–83)
- Create: `src/claimos/templates/home.html`
- Test: `tests/test_auth_routes.py` (extend existing file)

**Interfaces:**
- Produces: `_dev_auto_login_user() -> CurrentUser | None` in `dependencies.py`.
- Produces: `optional_user` now returns the dev auto-login user in dev when `AUTO_LOGIN_USER_ID` is set (unchanged in prod).
- Consumes: existing `optional_user`, `CurrentUser`, `templates`, `settings` (all already imported in `auth.py`).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_auth_routes.py` (the file already defines `client`, `seeded_db` with user `admin@test.com` / password `correcthorse12`, and imports `settings`):

```python
def test_root_authenticated_shows_dashboard(client, monkeypatch):
    # Force the cookie path (not dev auto-login) so the test is deterministic.
    monkeypatch.setattr(settings, "auto_login_user_id", "")
    login = client.post(
        "/api/auth/login",
        data={"email": "admin@test.com", "password": "correcthorse12"},
        follow_redirects=False,
    )
    assert login.status_code == 303  # cookie now stored on the TestClient
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Dashboard" in resp.text
    assert "coming soon" in resp.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && uv run pytest tests/test_auth_routes.py::test_root_authenticated_shows_dashboard -v`
Expected: FAIL — `/` currently renders splash (no "Dashboard"/"coming soon" text); `home.html` does not exist.

- [ ] **Step 3: Extract the dev-auto-login helper in `dependencies.py`**

In `src/claimos/dependencies.py`, replace the dev-auto-login block inside `get_current_user` (currently lines ~89–106) so the function begins:

```python
async def get_current_user(request: Request) -> CurrentUser:
    """Extract and validate JWT from request. Raises 401 if invalid.

    In dev environment with AUTO_LOGIN_USER_ID set, bypasses JWT validation
    and returns the configured user directly from the database.
    """
    dev_user = _dev_auto_login_user()
    if dev_user is not None:
        return dev_user

    token, source = _extract_token(request)
    if token is None:
        # ... (unchanged from here down)
```

And add this new module-level function directly above `get_current_user`:

```python
def _dev_auto_login_user() -> "CurrentUser | None":
    """In dev with AUTO_LOGIN_USER_ID set, resolve that user from the DB.

    Returns None outside dev, when unconfigured, or when the user is missing.
    """
    if settings.environment == "dev" and settings.auto_login_user_id:
        from claimos.db import SessionLocal
        from claimos.models_auth import User

        db = SessionLocal()
        try:
            user = db.get(User, settings.auto_login_user_id)
            if user:
                return CurrentUser(
                    id=user.id,
                    email=user.email,
                    system_role=user.system_role,
                    group_id=user.group_id,
                    group_kind=user.group.kind if user.group else None,
                )
        finally:
            db.close()
    return None
```

- [ ] **Step 4: Make `optional_user` dev-auto-login-aware**

In `src/claimos/dependencies.py`, update `optional_user` (line ~144):

```python
async def optional_user(request: Request) -> "CurrentUser | None":
    """Return the current user if authenticated, None otherwise.

    Honors dev auto-login (same as get_current_user). Used for public
    endpoints (like / and /crops/) that work with or without auth.
    """
    dev_user = _dev_auto_login_user()
    if dev_user is not None:
        return dev_user

    token, source = _extract_token(request)
    if token is None:
        return None
    return _decode_and_build_user(token, settings.jwt_secret)
```

- [ ] **Step 5: Create `src/claimos/templates/home.html`**

```html
{% extends "base.html" %}

{% block title %}Dashboard{% endblock %}
{% block topbar_title %}Dashboard{% endblock %}

{% block content %}
<div class="max-w-2xl">
  <h1 class="text-2xl font-semibold text-neutral-900">Dashboard</h1>
  <p class="mt-2 text-sm text-neutral-500">Your dashboard is coming soon.</p>
</div>
{% endblock %}
```

- [ ] **Step 6: Rewrite the `/` route in `auth.py`**

Replace the existing `splash` handler (lines ~79–83) with:

```python
@router.get("/", response_class=HTMLResponse, response_model=None)
def root(
    request: Request,
    user: CurrentUser | None = Depends(optional_user),
) -> HTMLResponse:
    """Root: authenticated users get the dashboard, anonymous users the splash."""
    if user is not None:
        return templates.TemplateResponse(
            request=request, name="home.html", context={"user": user}
        )
    return templates.TemplateResponse(request=request, name="splash.html")
```

(`CurrentUser` and `optional_user` are already imported in `auth.py`; `RedirectResponse` may now be unused — leave other imports as-is unless ruff flags it, in which case remove only the now-unused name.)

- [ ] **Step 7: Rebuild CSS (home.html introduces no new classes, but keep the app.css current)**

Run: `source .venv/bin/activate && uv run css`
Expected: `Done in NNms`, no errors.

- [ ] **Step 8: Run the new test + the existing splash test**

Run: `source .venv/bin/activate && uv run pytest tests/test_auth_routes.py::test_root_authenticated_shows_dashboard tests/test_auth_routes.py::test_splash_page -v`
Expected: both PASS. (`test_splash_page` still passes: anonymous `/` → splash with "Sign In".)

- [ ] **Step 9: Format, lint, commit**

```bash
source .venv/bin/activate && uv run ruff format . && uv run ruff format --check . && uv run ruff check .
git add src/claimos/dependencies.py src/claimos/routers/auth.py src/claimos/templates/home.html tests/test_auth_routes.py
git commit -m "feat: dashboard at / for authed users; optional_user honors dev auto-login

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: The sidebar app shell — restructure `base.html` + `_app_sidebar.html`

**Files:**
- Modify: `src/claimos/templates/base.html` (the `<body>` block)
- Create: `src/claimos/templates/_app_sidebar.html`
- Modify: `src/claimos/templates/dashboard.html` (add `topbar_title` block)
- Modify: `src/claimos/templates/claim_detail.html` (add `topbar_title` block)
- Modify: `src/claimos/templates/claim_new.html` (add `topbar_title` block)
- Modify: `src/claimos/templates/profile.html` (add `topbar_title` block)
- Test: `tests/test_app_shell.py` (new)

**Interfaces:**
- Consumes: `home.html` (Task 1) and the four existing pages, all of which `extends "base.html"`.
- Consumes template context already present: `request` (always), `user` (always, on authed app pages), `claim` (only on `claim_detail.html`).
- Produces: `_app_sidebar.html` partial reading `request.url.path` and optional `claim.id`; a `{% block topbar_title %}` in `base.html` (default `"ClaimOS"`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_app_shell.py`. These render the sidebar partial directly through the shared Jinja environment (no HTTP/DB needed), plus one integration check that the shell renders on a real authed page:

```python
"""Tests for the sidebar app shell and its nav partial."""

import types

from claimos.templating import templates


def _render_sidebar(path: str, claim=None) -> str:
    tmpl = templates.env.get_template("_app_sidebar.html")
    request = types.SimpleNamespace(url=types.SimpleNamespace(path=path))
    return tmpl.render(request=request, claim=claim)


def test_sidebar_global_group_always_present():
    html = _render_sidebar("/dashboard")
    assert 'href="/"' in html  # Dashboard
    assert 'href="/dashboard"' in html  # Claims
    assert "Claims" in html


def test_sidebar_hides_claim_group_without_claim():
    html = _render_sidebar("/dashboard")
    assert "Rooms & Groups" not in html
    assert "Evidence" not in html


def test_sidebar_shows_claim_group_with_claim():
    claim = types.SimpleNamespace(id="m1")
    html = _render_sidebar("/claims/m1", claim=claim)
    assert "Claim Detail" in html
    assert 'href="/claims/m1#rooms"' in html
    assert 'href="/claims/m1#evidence"' in html
    assert 'href="/claims/m1#items"' in html
    assert 'href="/claims/m1#preview"' in html
    assert 'href="/claims/m1#export"' in html


def test_sidebar_active_state_on_dashboard():
    html = _render_sidebar("/")
    # The Dashboard link (href="/") carries the active tokens.
    assert "bg-primary-subtle" in html
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && uv run pytest tests/test_app_shell.py -v`
Expected: FAIL — `_app_sidebar.html` does not exist (`TemplateNotFound`).

- [ ] **Step 3: Create `src/claimos/templates/_app_sidebar.html`**

```html
<nav class="px-3 py-4 space-y-1 text-sm">
  {# ── Global ─────────────────────────────────────────────── #}
  <a href="/"
     class="flex items-center gap-3 rounded-md px-3 py-2 font-medium
     {% if request.url.path == '/' %}bg-primary-subtle text-primary
     {% else %}text-neutral-600 hover:bg-neutral-200 hover:text-neutral-900{% endif %}">
    Dashboard
  </a>
  <a href="/dashboard"
     class="flex items-center gap-3 rounded-md px-3 py-2 font-medium
     {% if request.url.path == '/dashboard' %}bg-primary-subtle text-primary
     {% else %}text-neutral-600 hover:bg-neutral-200 hover:text-neutral-900{% endif %}">
    Claims
  </a>

  {# ── Claim-scoped (only when a claim is in context) ─────── #}
  {% if claim %}
  <p class="px-3 pt-5 pb-1 text-xs font-semibold uppercase tracking-wider text-neutral-400">
    Intelligence
  </p>
  <a href="/claims/{{ claim.id }}"
     class="flex items-center gap-3 rounded-md px-3 py-2 font-medium
     {% if request.url.path == '/claims/' ~ claim.id %}bg-primary-subtle text-primary
     {% else %}text-neutral-600 hover:bg-neutral-200 hover:text-neutral-900{% endif %}">
    Claim Detail
  </a>
  {% for label, frag in [
      ('Rooms & Groups', 'rooms'),
      ('Evidence', 'evidence'),
      ('Items', 'items'),
      ('Preview', 'preview'),
      ('Export', 'export'),
  ] %}
  <a href="/claims/{{ claim.id }}#{{ frag }}"
     class="flex items-center gap-3 rounded-md px-3 py-2 text-neutral-600
            hover:bg-neutral-200 hover:text-neutral-900">
    {{ label }}
  </a>
  {% endfor %}
  {% endif %}
</nav>
```

- [ ] **Step 4: Restructure the `<body>` of `src/claimos/templates/base.html`**

Replace the current `<body>…</body>` (the `<nav>` top bar, `<main>`, feedback include, and modal-root div) with:

```html
<body class="h-full">
  <div class="min-h-full flex flex-col">
    {# ── Top bar ──────────────────────────────────────────── #}
    <header class="bg-surface border-b border-neutral-200">
      <div class="flex h-14 items-center justify-between px-4 sm:px-6">
        <div class="flex items-center gap-2 text-sm">
          <a href="/" class="font-semibold text-neutral-900">CLAIMOS</a>
          <span class="text-neutral-300">/</span>
          <span class="font-medium text-neutral-600">{% block topbar_title %}ClaimOS{% endblock %}</span>
        </div>
        <div class="flex items-center gap-4">
          {% include "_theme_toggle.html" %}
          <a href="/claims/new" class="btn-primary rounded-md px-3 py-1.5 text-sm">New claim</a>
          {% if user %}
          <a href="/profile" class="text-sm text-neutral-600 hover:text-neutral-900">{{ user.display_name or user.email }}</a>
          {% if user.system_role == "system_admin" %}
          <a href="/admin/system/" class="btn-secondary text-sm">Admin</a>
          {% elif user.system_role == "internal_admin" %}
          <a href="/admin/internal/" class="btn-secondary text-sm">Admin</a>
          {% elif user.system_role == "external_admin" %}
          <a href="/admin/org/" class="btn-secondary text-sm">Admin</a>
          {% endif %}
          <form method="POST" action="/api/auth/logout" class="inline">
            <button type="submit" class="btn-secondary text-sm">Sign out</button>
          </form>
          {% endif %}
        </div>
      </div>
    </header>

    {# ── Sidebar + content ────────────────────────────────── #}
    <div class="flex flex-1">
      <aside class="w-56 flex-shrink-0 bg-neutral-100 border-r border-neutral-200">
        {% include "_app_sidebar.html" %}
      </aside>
      <main class="flex-1 px-4 sm:px-6 lg:px-8 py-8">
        {% block content %}{% endblock %}
      </main>
    </div>
  </div>

  {% if user %}
  {% include "_feedback_widget.html" %}
  {% endif %}
  <div id="crop-editor-modal-root"></div>
</body>
```

(The feedback guard simplifies to `{% if user %}`: `base.html` is only extended by authed app pages — splash/login/register don't extend it — so the old path exclusions were dead. The authed Dashboard at `/` now correctly gets the widget.)

- [ ] **Step 5: Add `topbar_title` blocks to the four content pages**

In `src/claimos/templates/dashboard.html`, directly after the existing `{% block title %}…{% endblock %}` line, add:

```html
{% block topbar_title %}Claims{% endblock %}
```

In `src/claimos/templates/claim_detail.html`, after its `{% block title %}…{% endblock %}` line, add:

```html
{% block topbar_title %}{{ claim.policyholder_name or "Claim" }}{% endblock %}
```

In `src/claimos/templates/claim_new.html`, after its `{% block title %}…{% endblock %}` line, add:

```html
{% block topbar_title %}New Claim{% endblock %}
```

In `src/claimos/templates/profile.html`, after its `{% block title %}…{% endblock %}` line, add:

```html
{% block topbar_title %}Profile{% endblock %}
```

- [ ] **Step 6: Rebuild CSS so new utility classes are emitted**

Run: `source .venv/bin/activate && uv run css`
Expected: `Done in NNms`, no errors. (Emits `w-56`, `flex-shrink-0`, `tracking-wider`, `bg-primary-subtle`, `hover:bg-neutral-200`, etc. now used by the new templates.)

- [ ] **Step 7: Run the sidebar tests**

Run: `source .venv/bin/activate && uv run pytest tests/test_app_shell.py -v`
Expected: all PASS.

- [ ] **Step 8: Guard + full suite + format/lint**

Run:
```bash
source .venv/bin/activate && \
python scripts/audit_design_tokens.py && \
uv run pytest -q && \
uv run ruff format . && uv run ruff format --check . && uv run ruff check .
```
Expected: token guard `clean ✓`; full suite green; ruff `All checks passed!` and zero reformatting. If any pre-existing test asserted on the old top-nav wordmark markup and now fails, update that assertion to the new topbar (the affordances — New claim / profile / Admin / Sign out — all still exist).

- [ ] **Step 9: Commit**

```bash
git add src/claimos/templates/base.html src/claimos/templates/_app_sidebar.html \
        src/claimos/templates/dashboard.html src/claimos/templates/claim_detail.html \
        src/claimos/templates/claim_new.html src/claimos/templates/profile.html \
        tests/test_app_shell.py
git commit -m "feat: sidebar app shell (topbar + left nav) replacing top-nav chrome

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Manual verification (after both tasks)

```bash
source .venv/bin/activate
uv run css
uv run dev   # http://localhost:8000 (or the port it prints)
```

Confirm:
- `/` (logged in) shows the empty **Dashboard** page inside the new shell.
- Left sidebar: **Dashboard** → `/`, **Claims** → `/dashboard`. On a claim page (`/claims/{id}`) the **Intelligence** group appears with Claim Detail + Rooms & Groups / Evidence / Items / Preview / Export; clicking them switches the in-page tab (existing hash JS) — the in-page tab bar is retained.
- The claim-scoped group is **absent** on `/`, `/dashboard`, `/claims/new`, `/profile`.
- Toggle **System / Light / Dark**: the sidebar is light in light mode, dark in dark mode; content unchanged.
- Top bar breadcrumb reads `CLAIMOS / <page>`; New claim / profile / Admin / Sign out all work.

## Self-review notes

- **Spec coverage:** shell restructure (Task 2 Step 4) ✓; theme-aware sidebar tokens (Task 2 Step 3) ✓; global + claim-scoped groups with empty-state hide (Task 2 Step 3) ✓; server-side active state (Task 2 Step 3) ✓; retained in-page tab bar (claim_detail content untouched) ✓; top bar with real affordances, search/bell/badge omitted (Task 2 Step 4) ✓; new Dashboard at `/` via optional_user + `_dev_auto_login_user` helper (Task 1) ✓; `/dashboard` unchanged ✓; tests (Task 1 Step 1, Task 2 Step 1) ✓.
- **No placeholders:** every code step shows complete content.
- **Type consistency:** `_dev_auto_login_user() -> CurrentUser | None` used identically in both call sites; `optional_user`/`root` signatures match imports already present in `auth.py`.
