# Unified `/team` Page + Nav Simplification — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make "Team" a single top-level nav item that opens one `/team` page combining the Members and Claim Access lists as stacked sections (Members first); remove the Members/Claim Access sub-nav items.

**Architecture:** Extract the existing members-list and claims-list table markup into two Jinja partials, add a `GET /team` route rendering both as sections on `team/index.html`, redirect the old `/team/users` and `/team/claims` list routes to `/team`, repoint the invite re-render and the `/admin/org` redirect to `/team`, and collapse the sidebar's Team section into one link.

**Tech Stack:** FastAPI, Jinja2, pytest, ruff, `uv`.

**Spec:** design approved in-conversation (2026-07-18); no separate spec file for this small change.

## Global Constraints

- Repo root `/Users/cmondor/consulting/tor`. Run all Python via `uv run` (a hook blocks bare python).
- Type hints; line length 100. No inline JS handlers. Only existing `@DESIGN.md` tokens — `tests/test_design_token_guard.py` must pass.
- `uv run ruff format .` then `uv run ruff format --check .` (zero reformatted) then `uv run ruff check .` before every commit.
- `/team` routes stay guarded by `require_external_admin` and hard-scoped to `user.group_id`.
- Baseline: full suite 513 pass. Keep it green.

---

### Task 1: Unified `/team` page + single "Team" nav item

**Files:**
- Create: `src/claimos/templates/team/_members_table.html` (members table partial)
- Create: `src/claimos/templates/team/_claims_table.html` (claims table partial)
- Create: `src/claimos/templates/team/index.html` (combined page: Members section, then Claim Access section)
- Modify: `src/claimos/templates/team/users.html` (use the members partial — kept only for any direct render; see step 6)
- Modify: `src/claimos/templates/team/claims.html` (use the claims partial)
- Modify: `src/claimos/routers/team.py` (add `GET /team`; redirect `GET /team/users` + `GET /team/claims` → `/team`; repoint invite re-render to `/team`)
- Modify: `src/claimos/routers/admin/org.py` (redirect target `/team/users` → `/team`)
- Modify: `src/claimos/templates/_app_sidebar.html` (single top-level "Team" link; remove sub-items)
- Modify: `docs/RBAC.md` (Team-nav description: single `/team` entry)
- Test: `tests/test_team_index.py` (create), `tests/test_team_users.py`/`tests/test_team_redirect.py` (adjust)

**Interfaces:**
- Produces: `GET /team` → `team/index.html` with context `{user, members, claims, invite_url (optional)}`.
- Redirects: `GET /team/users` → 302 `/team`; `GET /team/claims` → 302 `/team`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_team_index.py
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import claimos.models_auth  # noqa: F401
import claimos.models_grants  # noqa: F401
from claimos.dependencies import CurrentUser
from claimos.models import Base, Claim
from claimos.models_auth import Group, User


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    s.add_all([
        Group(id="eg", name="Acme Law", kind="external"),
        Group(id="og", name="Other Firm", kind="external"),
        User(id="ea", email="ea@acme.com", display_name="Ext Admin",
             system_role="external_admin", group_id="eg"),
        User(id="m1", email="m1@acme.com", display_name="Member One",
             system_role="external_user", group_id="eg"),
        User(id="out", email="out@other.com", display_name="Outsider",
             system_role="external_user", group_id="og"),
        Claim(id="cA", owner_group_id="eg", policyholder_name="Rossi"),
        Claim(id="cX", owner_group_id="og", policyholder_name="Other"),
    ])
    s.commit()
    yield s
    s.close()


@pytest.fixture
def client(db_session):
    from claimos.db import get_db
    from claimos.main import app
    from claimos.routers.team import require_external_admin

    def override_db():
        yield db_session

    async def mock_user():
        return CurrentUser(id="ea", email="ea@acme.com", system_role="external_admin",
                           group_id="eg", group_kind="external")

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_external_admin] = mock_user
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_team_index_shows_both_sections_scoped_to_firm(client):
    resp = client.get("/team")
    assert resp.status_code == 200
    # Members section (own firm only)
    assert "m1@acme.com" in resp.text
    assert "out@other.com" not in resp.text
    # Claim Access section (own firm only)
    assert "Rossi" in resp.text
    assert "Other" not in resp.text
    # Section headings present, Members before Claim Access
    assert resp.text.index("Members") < resp.text.index("Claim Access")


def test_old_list_routes_redirect_to_team(client):
    r1 = client.get("/team/users", follow_redirects=False)
    assert r1.status_code in (302, 307) and r1.headers["location"] == "/team"
    r2 = client.get("/team/claims", follow_redirects=False)
    assert r2.status_code in (302, 307) and r2.headers["location"] == "/team"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_team_index.py -v`
Expected: FAIL — `GET /team` 404 (route missing) / redirects not in place.

- [ ] **Step 3: Create the two table partials**

`src/claimos/templates/team/_members_table.html` — the members table extracted verbatim from `team/users.html` lines 16–43 (the `<div class="card">…</div>` block containing the members `<table>`). No `{% extends %}`/`{% block %}` — just the fragment.

`src/claimos/templates/team/_claims_table.html` — the claims table extracted verbatim from `team/claims.html` lines 8–31 (the `<div class="card">…</div>` block). Fragment only.

- [ ] **Step 4: Create `team/index.html`**

```jinja
{% extends "base.html" %}
{% block title %}Team{% endblock %}
{% block content %}
<div class="flex items-center justify-between mb-6">
  <h1 class="text-2xl font-bold text-neutral-900">Team</h1>
  <a href="/team/users/invite" class="bg-success text-white px-4 py-2 rounded-sm text-sm hover:bg-success-emphasis">Invite member</a>
</div>

{% if invite_url %}
<div class="mb-6 p-4 bg-success-surface border border-success-border rounded-lg">
  <p class="text-sm font-medium text-success-strong">Invite link created:</p>
  <p class="mt-1 text-sm text-success font-mono break-all">{{ invite_url }}</p>
</div>
{% endif %}

<section class="mb-10">
  <h2 class="text-lg font-semibold text-neutral-900 mb-3">Members</h2>
  {% include "team/_members_table.html" %}
</section>

<section>
  <h2 class="text-lg font-semibold text-neutral-900 mb-3">Claim Access</h2>
  {% include "team/_claims_table.html" %}
</section>
{% endblock %}
```

- [ ] **Step 5: Refactor `team/users.html` and `team/claims.html` to include the partials**

Replace the inlined `<div class="card">…</div>` table block in each with `{% include "team/_members_table.html" %}` / `{% include "team/_claims_table.html" %}` respectively, so there is a single source of the table markup. (These standalone pages become redirect targets in step 6, but keeping them partial-based avoids drift if they're ever rendered directly.)

- [ ] **Step 6: Add `GET /team`, redirect the list routes, repoint invite**

In `src/claimos/routers/team.py`:

Add the combined route (place it so the literal `/team` — i.e. `@router.get("")` on the `/team`-prefixed router — resolves; the router prefix is `/team`, so use `@router.get("")` or `@router.get("/")`. Use `@router.get("")` to match `/team` with no trailing slash, and also add `@router.get("/")` if needed for trailing-slash. Prefer `@router.get("")`):

```python
@router.get("", response_class=HTMLResponse)
def team_index(
    request: Request,
    user: CurrentUser = Depends(require_external_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    members = db.query(User).filter(User.group_id == user.group_id).order_by(User.email).all()
    claims = db.query(Claim).filter(Claim.owner_group_id == user.group_id).order_by(Claim.id).all()
    return templates.TemplateResponse(
        request=request,
        name="team/index.html",
        context={"user": user, "members": members, "claims": claims},
    )
```

Change `team_users` (`GET /users`) and `team_claims` (`GET /claims`) bodies to redirect:

```python
@router.get("/users")
def team_users(user: CurrentUser = Depends(require_external_admin)) -> RedirectResponse:
    return RedirectResponse(url="/team", status_code=302)


@router.get("/claims")
def team_claims(user: CurrentUser = Depends(require_external_admin)) -> RedirectResponse:
    return RedirectResponse(url="/team", status_code=302)
```

Keep `GET /users/invite`, `GET /users/{user_id}`, `GET /claims/{claim_id}/access`, and all POST routes unchanged. IMPORTANT: `/users/invite` and `/users/{user_id}` must still be declared BEFORE the now-redirecting `/users` — verify the invite/detail routes are unaffected (they have more specific paths, so order among them is already correct; the bare `/users` redirect does not shadow `/users/invite` or `/users/{user_id}`).

Repoint the invite re-render (end of `team_invite`) from `team/users.html` to the combined page:

```python
    return templates.TemplateResponse(
        request=request,
        name="team/index.html",
        context={
            "user": user,
            "members": members,
            "claims": db.query(Claim)
            .filter(Claim.owner_group_id == user.group_id)
            .order_by(Claim.id)
            .all(),
            "invite_url": invite_url,
        },
    )
```

(Drop the now-unused `group` local if it is no longer referenced.)

- [ ] **Step 7: Repoint the `/admin/org` redirect**

In `src/claimos/routers/admin/org.py`, change the redirect `Location` from `/team/users` to `/team`:

```python
        raise HTTPException(status_code=302, headers={"Location": "/team"})
```

- [ ] **Step 8: Collapse the sidebar Team section to one top-level link**

In `src/claimos/templates/_app_sidebar.html`, replace the entire Team block (the `{% if user is defined and user.system_role in ["external_admin", "system_admin"] %}` section header + Members + Claim Access links) with a single top-level link placed right after the "Claims" link (before the claim-scoped `{% if claim %}` block), so Team sits alongside Dashboard and Claims:

```jinja
  {% if user is defined and user.system_role in ["external_admin", "system_admin"] %}
  <a href="/team"
     class="flex items-center gap-3 rounded-md px-3 py-2 font-medium
     {% if request.url.path.startswith('/team') %}bg-primary-subtle text-primary
     {% else %}text-neutral-600 hover:bg-neutral-200 hover:text-neutral-900{% endif %}">
    Team
  </a>
  {% endif %}
```

Remove the old Team `<p>…Team…</p>` section header and the two sub-links. Do not add inline JS.

- [ ] **Step 9: Update the redirect + any nav-content tests**

- `tests/test_team_redirect.py`: the two redirect tests assert `Location == "/team/users"` — change the expected target to `/team`.
- Search the team test files for direct `GET /team/users` or `GET /team/claims` list-page assertions that now expect a redirect rather than 200, and update them. Specifically:
  - `tests/test_team_users.py::test_members_list_shows_own_group_only` (and the forbidden-path test) hit `GET /team/users`. Repoint these to `GET /team` (the members content now lives there) OR assert the redirect + follow it. Keep the assertion substantive (own-firm member present, cross-firm absent). Note each change in the report.
  - `tests/test_team_claims.py::test_claims_list_shows_own_firm_claims_only` hits `GET /team/claims` — repoint to `GET /team` (claims content now there) or assert redirect. Keep the cross-firm-exclusion assertion.
  - The invite test (`tests/test_team_invite.py`) asserts the members list re-renders with the invite URL after POST; the response is now `team/index.html` — confirm the invite-URL assertion still passes (the combined page shows `invite_url`), adjust the asserted text if it keyed on a `users.html`-only string.

- [ ] **Step 10: Update `docs/RBAC.md`**

In the Team-surface subsection, change the nav description from "nav: Members, Claim Access" (two entries) to a single top-level **Team** entry opening `/team`, which shows Members and Claim Access as sections (Members first). Note the `/admin/org` redirect now targets `/team`.

- [ ] **Step 11: Run tests + guard + full suite**

Run: `uv run pytest tests/test_team_index.py tests/test_team_users.py tests/test_team_claims.py tests/test_team_invite.py tests/test_team_redirect.py tests/test_design_token_guard.py tests/test_app_shell.py -v`
Expected: PASS. Then `uv run pytest -q` → full suite green (513 baseline + new `test_team_index.py` tests, minus none).

- [ ] **Step 12: Format, lint, commit**

```bash
uv run ruff format . && uv run ruff format --check . && uv run ruff check .
git add src/claimos/templates/team/ src/claimos/routers/team.py src/claimos/routers/admin/org.py src/claimos/templates/_app_sidebar.html docs/RBAC.md tests/test_team_index.py tests/test_team_users.py tests/test_team_claims.py tests/test_team_invite.py tests/test_team_redirect.py
git commit -m "feat: unified /team page (Members + Claim Access sections); single Team nav item"
```

---

## Self-Review

**Spec coverage:** single top-level "Team" nav item → step 8; combined `/team` page with Members-first then Claim Access → steps 4/6; remove sub-nav → step 8; redirect old list routes → step 6; invite URL visible on combined page → steps 4/6; `/admin/org` redirect repoint → step 7; tests + docs → steps 9/10. All covered.

**Placeholder scan:** No TBD/"handle X"/"similar to". Partials are extracted verbatim from named line ranges; the combined template and routes are given in full.

**Type consistency:** `team_index` context keys (`user`, `members`, `claims`, optional `invite_url`) match what `team/index.html` and its partials consume (`members`, `claims`, `invite_url`). Redirect routes return `RedirectResponse` (import already present in `team.py`).
