# Team Management Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give external admins (Lawyers/Paralegals) a first-class `/team` surface in the main app to manage their firm's users, role grants, per-user overrides, and per-claim access — and move them off the `/admin` area.

**Architecture:** A new `src/claimos/routers/team.py` (prefix `/team`, guarded by `require_external_admin`, hard-scoped to the admin's own `group_id`) renders pages from `src/claimos/templates/team/`. A pure read-helper service `services/effective_permissions.py` resolves the group-wide and per-claim permission matrices; `services/grants.py` gains override add/remove. A left-nav **Team** section is gated to external_admin/system_admin, and external admins are redirected off `/admin/org` (except the profile carve-out).

**Tech Stack:** Python 3.11+, FastAPI, Jinja2, HTMX, SQLAlchemy 2.x, pytest, ruff, `uv`.

**Spec:** `docs/superpowers/specs/2026-07-16-team-management-page-design.md`

## Global Constraints

- Python 3.11+, `uv`. No new dependencies. Run all Python via `uv run` (a hook blocks bare python).
- Type hints everywhere; modern syntax (`X | None`, `list[str]`). Line length 100.
- `uv run ruff format .` then `uv run ruff format --check .` (zero reformatted) then `uv run ruff check .` before every commit.
- **No inline JS event handlers** (`onclick=`/`onchange=`/`onsubmit=`). Use `data-*` attrs + delegated listeners in `src/claimos/static/app.js`, and HTMX for partial swaps.
- All new templates follow `@DESIGN.md` tokens (reuse `admin/org/*.html` patterns: `card`, tables, `bg-primary`/`text-neutral-*`, `rounded-sm`). No new tokens — must pass `tests/test_design_token_guard.py`.
- Routes are **hard-scoped to `user.group_id`** — no group selector. Every write endpoint verifies the target's `group_id`/`owner_group_id == user.group_id` (or claim ownership) BEFORE mutating; a mismatch is 404 (users/claims) or 403.
- `require_external_admin` allows `external_admin` **and** `system_admin` (full edit, own-group-scoped); everyone else 403.
- Currency untouched. UUIDs as strings. Timestamps timezone-aware UTC.
- Object types: `roles.OBJECT_TYPES` = `items, evidence, reports, exports, crops, audit_logs, rooms, item_groups, comments, users`. Claim-role hierarchy: `viewer<editor<contributor<approver<manager` (`dependencies.ROLE_HIERARCHY`).
- Tests in `tests/` mirror `src/claimos/`. TestClient tests override `require_external_admin` and `get_db` (see `tests/test_admin_org_grants.py` for the fixture pattern).

**Baseline:** full suite passes (477 at plan time). Every task keeps it green.

---

### Task 1: `require_external_admin` + `/team` router scaffold + Members list + nav

**Files:**
- Create: `src/claimos/routers/team.py`
- Modify: `src/claimos/main.py` (register router)
- Modify: `src/claimos/templates/_app_sidebar.html` (Team nav section)
- Create: `src/claimos/templates/team/base_team.html` (thin layout note — see step 3), `src/claimos/templates/team/users.html`
- Test: `tests/test_team_users.py`

**Interfaces:**
- Produces:
  - `require_external_admin(user: CurrentUser = Depends(require_active_user)) -> CurrentUser` (in `team.py`)
  - `router` (APIRouter, prefix `/team`)
  - `GET /team/users` → renders `team/users.html`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_team_users.py
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import claimos.models_auth  # noqa: F401
import claimos.models_grants  # noqa: F401
from claimos.dependencies import CurrentUser
from claimos.models import Base
from claimos.models_auth import Group, User


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    s.add_all(
        [
            Group(id="eg", name="Acme Law", kind="external"),
            Group(id="og", name="Other Firm", kind="external"),
            User(id="ea", email="ea@acme.com", display_name="Ext Admin",
                 system_role="external_admin", group_id="eg"),
            User(id="m1", email="m1@acme.com", display_name="Member One",
                 system_role="external_user", group_id="eg"),
            User(id="out", email="out@other.com", display_name="Outsider",
                 system_role="external_user", group_id="og"),
        ]
    )
    s.commit()
    yield s
    s.close()


def _client(db_session, role="external_admin", group_id="eg"):
    from claimos.db import get_db
    from claimos.main import app
    from claimos.routers.team import require_external_admin

    def override_db():
        yield db_session

    async def mock_user():
        return CurrentUser(id="ea", email="ea@acme.com", system_role=role,
                           group_id=group_id, group_kind="external")

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_external_admin] = mock_user
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
def client(db_session):
    yield from _client(db_session)


def test_members_list_shows_own_group_only(client):
    resp = client.get("/team/users")
    assert resp.status_code == 200
    assert "m1@acme.com" in resp.text
    assert "out@other.com" not in resp.text  # different firm


def test_members_list_forbidden_for_non_admin(db_session):
    # A plain external_user must not reach /team — require_external_admin rejects.
    from claimos.db import get_db
    from claimos.main import app

    def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app, raise_server_exceptions=False)
    # No override of require_external_admin here; unauthenticated → 401/redirect.
    resp = client.get("/team/users")
    assert resp.status_code in (401, 403)
    app.dependency_overrides.clear()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_team_users.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'claimos.routers.team'`

- [ ] **Step 3: Create the router + templates**

`src/claimos/routers/team.py`:

```python
"""Firm-facing Team management surface for external admins (RBAC v2)."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from claimos.db import get_db
from claimos.dependencies import CurrentUser, require_active_user
from claimos.models_auth import Group, User
from claimos.templating import templates

router = APIRouter(prefix="/team")


async def require_external_admin(
    user: CurrentUser = Depends(require_active_user),
) -> CurrentUser:
    """Allow external_admin and system_admin; everyone else 403."""
    if user.system_role not in ("external_admin", "system_admin"):
        raise HTTPException(status_code=403, detail="Team access requires firm admin")
    return user


@router.get("/users", response_class=HTMLResponse)
def team_users(
    request: Request,
    user: CurrentUser = Depends(require_external_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    group = db.get(Group, user.group_id) if user.group_id else None
    members = db.query(User).filter(User.group_id == user.group_id).order_by(User.email).all()
    return templates.TemplateResponse(
        request=request,
        name="team/users.html",
        context={"user": user, "group": group, "members": members},
    )
```

`src/claimos/templates/team/users.html` — extend `base.html` (so it gets the app shell + sidebar), render a `card` with a table of members (display name, email, system_role, active/inactive) each row linking to `/team/users/{{ m.id }}`, plus an "Invite member" button linking to `/team/users/invite`. Mirror the markup of `admin/org/users.html` (same token classes), but the page title is "Team — Members". (No `breadcrumbs`/`panel_*` context needed; base.html only requires `user`.)

> Note: there is no separate `base_team.html` — `team/*.html` extend `base.html` directly. Delete the `base_team.html` create-entry from the Files list if you scaffolded it; it is not needed.

- [ ] **Step 4: Register the router**

In `src/claimos/main.py`, alongside the other `app.include_router(...)` calls (after `app.include_router(admin_org.router)` is fine), add:

```python
from claimos.routers import team  # noqa: E402  (match existing import style)
app.include_router(team.router)
```

Match the existing import grouping/style in `main.py`.

- [ ] **Step 5: Add the Team nav section**

In `src/claimos/templates/_app_sidebar.html`, before the Admin block (`{% if request.url.path.startswith('/admin/') %}`), add:

```jinja
{# ── Team (external / system admins) ─────────────────────── #}
{% if user is defined and user.system_role in ["external_admin", "system_admin"] %}
<p class="px-3 pt-5 pb-1 text-xs font-semibold uppercase tracking-wider text-neutral-400">
  Team
</p>
<a href="/team/users"
   class="flex items-center gap-3 rounded-md px-3 py-2 font-medium
   {% if request.url.path.startswith('/team/users') %}bg-primary-subtle text-primary
   {% else %}text-neutral-600 hover:bg-neutral-200 hover:text-neutral-900{% endif %}">
  Members
</a>
<a href="/team/claims"
   class="flex items-center gap-3 rounded-md px-3 py-2 font-medium
   {% if request.url.path.startswith('/team/claims') %}bg-primary-subtle text-primary
   {% else %}text-neutral-600 hover:bg-neutral-200 hover:text-neutral-900{% endif %}">
  Claim Access
</a>
{% endif %}
```

- [ ] **Step 6: Run tests + design-token guard**

Run: `uv run pytest tests/test_team_users.py tests/test_design_token_guard.py tests/test_app_shell.py -v`
Expected: PASS. Then `uv run pytest -q` stays green.

- [ ] **Step 7: Format, lint, commit**

```bash
uv run ruff format . && uv run ruff format --check . && uv run ruff check .
git add src/claimos/routers/team.py src/claimos/main.py src/claimos/templates/team/ src/claimos/templates/_app_sidebar.html tests/test_team_users.py
git commit -m "feat: /team members list + require_external_admin + Team nav"
```

---

### Task 2: `effective_permissions` service

**Files:**
- Create: `src/claimos/services/effective_permissions.py`
- Test: `tests/test_effective_permissions.py`

**Interfaces:**
- Consumes: `roles.OBJECT_TYPES`, `roles.role_for_object`, `dependencies.ROLE_HIERARCHY`, `dependencies._external_effective_role`, `dependencies.CurrentUser`, `models_grants.RoleGrant/RoleGrantOverride`
- Produces:
  - `group_effective_matrix(db, user_id: str, group_id: str) -> dict[str, str | None]`
  - `claim_effective_matrix(db, user: CurrentUser, claim_id: str) -> dict[str, str | None]`
  - `claim_members_access(db, group_id: str, claim_id: str) -> list[tuple[User, dict[str, str | None]]]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_effective_permissions.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from claimos.dependencies import CurrentUser
from claimos.models import Base, Claim
from claimos.models_auth import Group, User
from claimos.services.effective_permissions import (
    claim_effective_matrix,
    claim_members_access,
    group_effective_matrix,
)
from claimos.services.grants import create_grant


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    s.add_all([
        Group(id="eg", name="Firm", kind="external"),
        User(id="ph", email="p@f.com", display_name="P", system_role="external_user", group_id="eg"),
        User(id="adm", email="a@f.com", display_name="A", system_role="external_admin", group_id="eg"),
        Claim(id="cA", owner_group_id="eg"),
        Claim(id="cB", owner_group_id="eg"),
    ])
    s.commit()
    yield s
    s.close()


def _cu(uid):
    return CurrentUser(id=uid, email="x@f.com", system_role="external_user",
                       group_id="eg", group_kind="external")


def test_group_matrix_from_group_scoped_grant_and_override(db):
    create_grant(db, user_id="ph", user_role="photographer", scope="group",
                 claim_ids=[], overrides={"items": "contributor"}, granted_by_id="adm")
    matrix = group_effective_matrix(db, "ph", "eg")
    assert matrix["evidence"] == "contributor"
    assert matrix["items"] == "contributor"   # override raised from viewer
    assert matrix["exports"] is None          # not in photographer profile


def test_group_matrix_excludes_claim_scoped_grants(db):
    create_grant(db, user_id="ph", user_role="valuator", scope="claims",
                 claim_ids=["cA"], overrides={}, granted_by_id="adm")
    matrix = group_effective_matrix(db, "ph", "eg")
    assert matrix["items"] is None  # claim-scoped grant does not affect the group matrix


def test_claim_matrix_includes_claim_scoped(db):
    create_grant(db, user_id="ph", user_role="valuator", scope="claims",
                 claim_ids=["cA"], overrides={}, granted_by_id="adm")
    m_a = claim_effective_matrix(db, _cu("ph"), "cA")
    m_b = claim_effective_matrix(db, _cu("ph"), "cB")
    assert m_a["items"] == "contributor"
    assert m_b["items"] is None  # not granted on cB


def test_claim_members_access_lists_only_members_with_access(db):
    create_grant(db, user_id="ph", user_role="photographer", scope="group",
                 claim_ids=[], overrides={}, granted_by_id="adm")
    rows = claim_members_access(db, "eg", "cA")
    ids = {u.id for u, _m in rows}
    assert "ph" in ids
    # adm (external_admin) owns the claim → has access too
    assert "adm" in ids
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_effective_permissions.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'claimos.services.effective_permissions'`

- [ ] **Step 3: Implement the service**

```python
# src/claimos/services/effective_permissions.py
"""Read-only helpers that resolve a user's effective RBAC v2 permissions.

group_effective_matrix  -> group-wide baseline (group-scoped grants + overrides)
claim_effective_matrix  -> full resolution for one claim (delegates to the resolver)
claim_members_access    -> every firm member with any access on a claim
"""

from sqlalchemy.orm import Session

from claimos.dependencies import ROLE_HIERARCHY, CurrentUser, _external_effective_role
from claimos.models_auth import User
from claimos.models_grants import RoleGrant, RoleGrantOverride
from claimos.roles import OBJECT_TYPES, role_for_object


def group_effective_matrix(db: Session, user_id: str, group_id: str) -> dict[str, str | None]:
    """Max role per object type over the user's GROUP-scoped grants + overrides."""
    grants = (
        db.query(RoleGrant)
        .filter(
            RoleGrant.user_id == user_id,
            RoleGrant.group_id == group_id,
            RoleGrant.scope == "group",
        )
        .all()
    )
    matrix: dict[str, str | None] = {obj: None for obj in OBJECT_TYPES}
    for grant in grants:
        overrides = {
            o.object_type: o.role
            for o in db.query(RoleGrantOverride).filter(RoleGrantOverride.grant_id == grant.id)
        }
        for obj in OBJECT_TYPES:
            role = role_for_object(grant.user_role, obj)
            ov = overrides.get(obj)
            if ov is not None and (
                role is None or ROLE_HIERARCHY.get(ov, -1) > ROLE_HIERARCHY.get(role, -1)
            ):
                role = ov
            if role is None:
                continue
            current = matrix[obj]
            if current is None or ROLE_HIERARCHY.get(role, -1) > ROLE_HIERARCHY.get(current, -1):
                matrix[obj] = role
    return matrix


def claim_effective_matrix(db: Session, user: CurrentUser, claim_id: str) -> dict[str, str | None]:
    """Full per-claim resolution (group + claim-scoped grants + overrides)."""
    return {obj: _external_effective_role(db, user, claim_id, obj) for obj in OBJECT_TYPES}


def claim_members_access(
    db: Session, group_id: str, claim_id: str
) -> list[tuple[User, dict[str, str | None]]]:
    """Every firm member with any resolved access on the claim, with their matrix."""
    members = db.query(User).filter(User.group_id == group_id).order_by(User.email).all()
    rows: list[tuple[User, dict[str, str | None]]] = []
    for member in members:
        cu = CurrentUser(
            id=member.id,
            email=member.email,
            system_role=member.system_role,
            group_id=member.group_id,
            group_kind="external",
        )
        matrix = claim_effective_matrix(db, cu, claim_id)
        if any(v is not None for v in matrix.values()):
            rows.append((member, matrix))
    return rows
```

> Note on `claim_members_access`: `_external_effective_role` returns `None` for an `external_admin` who owns the claim (it doesn't grant via grants), but `_check_claim_access` short-circuits owners to manager. To include owner-admins in the members view, after building `matrix`, if it is all-`None` and `member.system_role == "external_admin"` and the claim's `owner_group_id == group_id`, set every object to `"manager"`. Add that owner short-circuit so the test's `adm` assertion passes.

- [ ] **Step 4: Add the owner short-circuit**

Extend the loop in `claim_members_access` before the `if any(...)` check:

```python
        if all(v is None for v in matrix.values()) and member.system_role == "external_admin":
            from claimos.models import Claim

            claim = db.get(Claim, claim_id)
            if claim is not None and claim.owner_group_id == group_id:
                matrix = {obj: "manager" for obj in matrix}
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_effective_permissions.py -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Format, lint, commit**

```bash
uv run ruff format . && uv run ruff format --check . && uv run ruff check .
git add src/claimos/services/effective_permissions.py tests/test_effective_permissions.py
git commit -m "feat: effective_permissions service (group/claim matrices + members)"
```

---

### Task 3: Member detail page (read)

**Files:**
- Modify: `src/claimos/routers/team.py` (`GET /team/users/{user_id}`)
- Create: `src/claimos/templates/team/user_detail.html`
- Test: `tests/test_team_users.py` (extend)

**Interfaces:**
- Consumes: `effective_permissions.group_effective_matrix`, `grants.list_grants`, `roles.USER_ROLES/OBJECT_TYPES`
- Produces: `GET /team/users/{user_id}` → `team/user_detail.html`; context keys `target`, `grants`, `effective` (dict object→role), `claim_grants` (list), `user_roles`, `object_types`, `group_claims`, `role_levels` (list of hierarchy keys)

- [ ] **Step 1: Write the failing test** (append to `tests/test_team_users.py`)

```python
def test_member_detail_shows_grants_and_effective_matrix(client, db_session):
    from claimos.services.grants import create_grant
    create_grant(db_session, user_id="m1", user_role="photographer", scope="group",
                 claim_ids=[], overrides={}, granted_by_id="ea")
    resp = client.get("/team/users/m1")
    assert resp.status_code == 200
    assert "photographer" in resp.text          # grant listed
    assert "Evidence" in resp.text or "evidence" in resp.text  # effective matrix row


def test_member_detail_cross_group_is_404(client):
    resp = client.get("/team/users/out")  # different firm
    assert resp.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_team_users.py -k member_detail -v`
Expected: FAIL (404 route missing → actually 404 for both; the grants-visible assertion fails).

- [ ] **Step 3: Implement the route** (add to `team.py`)

```python
from claimos.models import Claim
from claimos.roles import OBJECT_TYPES, USER_ROLES
from claimos.dependencies import ROLE_HIERARCHY
from claimos.services.effective_permissions import group_effective_matrix
from claimos.services.grants import list_grants


@router.get("/users/{user_id}", response_class=HTMLResponse)
def team_user_detail(
    user_id: str,
    request: Request,
    user: CurrentUser = Depends(require_external_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    target = db.get(User, user_id)
    if target is None or target.group_id != user.group_id:
        raise HTTPException(status_code=404, detail="Member not found")
    grants = list_grants(db, target.id)
    claim_grants = [g for g in grants if g.scope == "claims"]
    effective = group_effective_matrix(db, target.id, user.group_id)
    group_claims = (
        db.query(Claim).filter(Claim.owner_group_id == user.group_id).order_by(Claim.id).all()
    )
    return templates.TemplateResponse(
        request=request,
        name="team/user_detail.html",
        context={
            "user": user,
            "target": target,
            "grants": grants,
            "claim_grants": claim_grants,
            "effective": effective,
            "object_types": OBJECT_TYPES,
            "user_roles": USER_ROLES,
            "role_levels": list(ROLE_HIERARCHY.keys()),
            "group_claims": group_claims,
        },
    )
```

- [ ] **Step 4: Create `team/user_detail.html`**

Extend `base.html`. Sections (reuse `admin/org/user_detail.html` token classes):
1. Identity card (name/email/system_role/status).
2. **Roles & Access** card: table of `grants` (role, scope, claims). Leave the per-grant override editor and the assign form as **placeholders wired in Task 7–8** — for now render the grants table read-only (role, scope, claims) with no forms. Do NOT add an assign form yet.
3. **Group-wide effective permissions** card: a table with a row per `object_types` entry and the resolved role from `effective[obj]` (render `—` when `None`). Use a small helper label (Title-case the object type).
4. **Claim-specific grants** list: iterate `claim_grants`, show role + the linked claim ids.

Keep markup token-clean (no new tokens). Page title "Team — {{ target.email }}".

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_team_users.py -v`
Expected: PASS. Full suite `uv run pytest -q` green.

- [ ] **Step 6: Format, lint, commit**

```bash
uv run ruff format . && uv run ruff format --check . && uv run ruff check .
git add src/claimos/routers/team.py src/claimos/templates/team/user_detail.html tests/test_team_users.py
git commit -m "feat: /team member detail — grants + group-wide effective matrix (read)"
```

---

### Task 4: Member lifecycle (activate / deactivate) on `/team`

**Files:**
- Modify: `src/claimos/routers/team.py`
- Modify: `src/claimos/templates/team/user_detail.html` (activate/deactivate buttons)
- Test: `tests/test_team_users.py` (extend)

**Interfaces:**
- Produces: `POST /team/users/{user_id}/deactivate`, `POST /team/users/{user_id}/activate` → redirect back to `/team/users/{id}`

- [ ] **Step 1: Write the failing test**

```python
def test_deactivate_and_activate_member(client, db_session):
    r = client.post("/team/users/m1/deactivate", follow_redirects=False)
    assert r.status_code in (302, 303)
    db_session.expire_all()
    from claimos.models_auth import User
    assert db_session.get(User, "m1").is_active is False
    client.post("/team/users/m1/activate", follow_redirects=False)
    db_session.expire_all()
    assert db_session.get(User, "m1").is_active is True


def test_cannot_deactivate_cross_group_member(client):
    r = client.post("/team/users/out/deactivate", follow_redirects=False)
    assert r.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_team_users.py -k deactivate -v`
Expected: FAIL (routes missing → 404 for m1 too).

- [ ] **Step 3: Implement**

```python
from fastapi.responses import RedirectResponse


def _load_own_member(db: Session, user: CurrentUser, user_id: str) -> User:
    target = db.get(User, user_id)
    if target is None or target.group_id != user.group_id:
        raise HTTPException(status_code=404, detail="Member not found")
    return target


@router.post("/users/{user_id}/deactivate")
def team_deactivate(
    user_id: str,
    user: CurrentUser = Depends(require_external_admin),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    target = _load_own_member(db, user, user_id)
    target.is_active = False
    db.commit()
    return RedirectResponse(url=f"/team/users/{user_id}", status_code=303)


@router.post("/users/{user_id}/activate")
def team_activate(
    user_id: str,
    user: CurrentUser = Depends(require_external_admin),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    target = _load_own_member(db, user, user_id)
    target.is_active = True
    db.commit()
    return RedirectResponse(url=f"/team/users/{user_id}", status_code=303)
```

Add the activate/deactivate `<form method="POST">` buttons to the identity card in `user_detail.html` (mirror `admin/org/user_detail.html` lines 27–37; plain form POST, no JS). Use the shared `_load_own_member` helper in later tasks too.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_team_users.py -v` → PASS; `uv run pytest -q` green.

- [ ] **Step 5: Format, lint, commit**

```bash
uv run ruff format . && uv run ruff format --check . && uv run ruff check .
git add src/claimos/routers/team.py src/claimos/templates/team/user_detail.html tests/test_team_users.py
git commit -m "feat: /team member activate/deactivate"
```

---

### Task 5: Redirect external admins off `/admin/org` (profile carve-out)

**Files:**
- Modify: `src/claimos/routers/admin/org.py` (router-level redirect dependency)
- Test: `tests/test_admin_org.py` (extend) or `tests/test_team_redirect.py` (create)

**Interfaces:**
- Produces: any `/admin/org/*` request by an `external_admin` → 302 to `/team/users`, **except** paths starting `/admin/org/profile`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_team_redirect.py
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import claimos.models_auth  # noqa: F401
import claimos.models_grants  # noqa: F401
from claimos.dependencies import CurrentUser, require_active_user
from claimos.models import Base
from claimos.models_auth import Group, User


@pytest.fixture
def client():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    s.add_all([Group(id="eg", name="Firm", kind="external"),
               User(id="ea", email="ea@f.com", display_name="EA",
                    system_role="external_admin", group_id="eg")])
    s.commit()
    from claimos.db import get_db
    from claimos.main import app

    def override_db():
        yield s

    async def mock_ea():
        return CurrentUser(id="ea", email="ea@f.com", system_role="external_admin",
                           group_id="eg", group_kind="external")

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_active_user] = mock_ea
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()
    s.close()


def test_external_admin_redirected_off_admin_org(client):
    r = client.get("/admin/org/", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/team/users"


def test_profile_carveout_not_redirected(client):
    r = client.get("/admin/org/profile", follow_redirects=False)
    assert r.status_code != 302  # profile stays reachable (200 or its own handling)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_team_redirect.py -v`
Expected: FAIL (currently 200, no redirect).

- [ ] **Step 3: Implement the redirect dependency**

In `src/claimos/routers/admin/org.py`, add near the top-level helpers:

```python
async def _redirect_external_admin(
    request: Request,
    user: CurrentUser = Depends(require_active_user),
) -> None:
    """External admins manage their firm at /team; bounce them out of /admin/org,
    except the firm-profile editor which stays here until /team/settings lands."""
    if user.system_role == "external_admin" and not request.url.path.startswith(
        "/admin/org/profile"
    ):
        raise HTTPException(status_code=302, headers={"Location": "/team/users"})
```

Attach it to the router so it runs for every `/admin/org/*` route. Change the router construction:

```python
router = APIRouter(prefix="/admin/org", dependencies=[Depends(_redirect_external_admin)])
```

Ensure `Request` and `require_active_user` are imported in `org.py` (they already are).

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_team_redirect.py tests/test_admin_org.py tests/test_admin_org_grants.py -v`
Expected: PASS. Existing org tests that log in as external_admin and expect 200 must be checked — if any now redirect, update them to use an `internal_admin`/`system_admin` actor (the panel's real audience) or assert the redirect. Note each change in your report. Then `uv run pytest -q` green.

- [ ] **Step 5: Format, lint, commit**

```bash
uv run ruff format . && uv run ruff format --check . && uv run ruff check .
git add src/claimos/routers/admin/org.py tests/test_team_redirect.py
git commit -m "feat: redirect external admins off /admin/org to /team (profile carve-out)"
```

---

### Task 6: `add_override` / `remove_override` in grants service

**Files:**
- Modify: `src/claimos/services/grants.py`
- Test: `tests/test_grants_service.py` (extend)

**Interfaces:**
- Consumes: `roles.OBJECT_TYPES`, `dependencies.ROLE_HIERARCHY`, `models_grants.RoleGrant/RoleGrantOverride`, `access_cache.invalidate_user`
- Produces:
  - `add_override(db, grant_id: str, object_type: str, role: str) -> RoleGrantOverride`
  - `remove_override(db, grant_id: str, object_type: str) -> None`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_grants_service.py
def test_add_and_remove_override(db):
    g = create_grant(db, user_id="ph", user_role="photographer", scope="group",
                     claim_ids=[], overrides={}, granted_by_id="adm")
    from claimos.services.grants import add_override, remove_override
    from claimos.models_grants import RoleGrantOverride

    ov = add_override(db, g.id, "items", "contributor")
    assert ov.object_type == "items" and ov.role == "contributor"
    # upsert: same object updates, not duplicates
    add_override(db, g.id, "items", "approver")
    rows = db.query(RoleGrantOverride).filter(RoleGrantOverride.grant_id == g.id).all()
    assert len(rows) == 1 and rows[0].role == "approver"

    remove_override(db, g.id, "items")
    assert db.query(RoleGrantOverride).filter(RoleGrantOverride.grant_id == g.id).count() == 0


def test_override_validation(db):
    g = create_grant(db, user_id="ph", user_role="photographer", scope="group",
                     claim_ids=[], overrides={}, granted_by_id="adm")
    from claimos.services.grants import GrantValidationError, add_override
    import pytest
    with pytest.raises(GrantValidationError):
        add_override(db, g.id, "not_an_object", "contributor")
    with pytest.raises(GrantValidationError):
        add_override(db, g.id, "items", "not_a_role")
    with pytest.raises(GrantValidationError):
        add_override(db, "missing-grant", "items", "contributor")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_grants_service.py -k override -v`
Expected: FAIL — `ImportError: cannot import name 'add_override'`

- [ ] **Step 3: Implement**

Add to `src/claimos/services/grants.py` (imports at top: `from claimos.roles import OBJECT_TYPES` already or add; `from claimos.dependencies import ROLE_HIERARCHY`):

```python
def add_override(db: Session, grant_id: str, object_type: str, role: str) -> RoleGrantOverride:
    if object_type not in OBJECT_TYPES:
        raise GrantValidationError(f"Unknown object type: {object_type}")
    if role not in ROLE_HIERARCHY:
        raise GrantValidationError(f"Unknown role: {role}")
    grant = db.get(RoleGrant, grant_id)
    if grant is None:
        raise GrantValidationError("Grant not found")
    existing = (
        db.query(RoleGrantOverride)
        .filter(RoleGrantOverride.grant_id == grant_id, RoleGrantOverride.object_type == object_type)
        .first()
    )
    if existing is not None:
        existing.role = role
        override = existing
    else:
        override = RoleGrantOverride(grant_id=grant_id, object_type=object_type, role=role)
        db.add(override)
    db.commit()
    db.refresh(override)
    invalidate_user(grant.user_id)
    return override


def remove_override(db: Session, grant_id: str, object_type: str) -> None:
    grant = db.get(RoleGrant, grant_id)
    if grant is None:
        return
    row = (
        db.query(RoleGrantOverride)
        .filter(RoleGrantOverride.grant_id == grant_id, RoleGrantOverride.object_type == object_type)
        .first()
    )
    if row is not None:
        db.delete(row)
        db.commit()
        invalidate_user(grant.user_id)
```

> Import note: `from claimos.dependencies import ROLE_HIERARCHY` at the top of `grants.py` is safe (no import cycle — `dependencies` does not import `grants`). If a cycle ever appears, import it inside the function instead.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_grants_service.py -v` → PASS; `uv run pytest -q` green.

- [ ] **Step 5: Format, lint, commit**

```bash
uv run ruff format . && uv run ruff format --check . && uv run ruff check .
git add src/claimos/services/grants.py tests/test_grants_service.py
git commit -m "feat: grants add_override/remove_override with validation"
```

---

### Task 7: Assign-role + revoke on `/team` (with conditional claim picker)

**Files:**
- Modify: `src/claimos/routers/team.py`
- Modify: `src/claimos/templates/team/user_detail.html` (assign form + revoke buttons)
- Modify: `src/claimos/static/app.js` (delegated `change` listener to toggle claim picker)
- Test: `tests/test_team_grants.py` (create)

**Interfaces:**
- Consumes: `grants.create_grant`, `grants.revoke_grant`, `grants.GrantValidationError`
- Produces:
  - `POST /team/users/{user_id}/grants` (form: `user_role`, `scope`, `claim_ids` list) → redirect to member detail; `GrantValidationError` → 400
  - `POST /team/grants/{grant_id}/revoke` → redirect to member detail (tenant-checked)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_team_grants.py — reuse the client/db fixtures shape from tests/test_team_users.py
# (copy the db_session + client fixtures, seeding eg/og, ea/m1/out, plus two claims cA/cB owned by eg)

def test_assign_group_scoped_role(client, db_session):
    r = client.post("/team/users/m1/grants",
                    data={"user_role": "photographer", "scope": "group"},
                    follow_redirects=False)
    assert r.status_code in (302, 303)
    from claimos.services.grants import list_grants
    grants = list_grants(db_session, "m1")
    assert len(grants) == 1 and grants[0].user_role == "photographer"


def test_assign_cross_group_member_is_404(client):
    r = client.post("/team/users/out/grants",
                    data={"user_role": "photographer", "scope": "group"},
                    follow_redirects=False)
    assert r.status_code == 404


def test_claimant_requires_single_claim_returns_400(client):
    r = client.post("/team/users/m1/grants",
                    data={"user_role": "claimant", "scope": "group"},
                    follow_redirects=False)
    assert r.status_code == 400


def test_revoke_grant(client, db_session):
    from claimos.services.grants import create_grant, list_grants
    g = create_grant(db_session, user_id="m1", user_role="valuator", scope="group",
                     claim_ids=[], overrides={}, granted_by_id="ea")
    r = client.post(f"/team/grants/{g.id}/revoke", follow_redirects=False)
    assert r.status_code in (302, 303)
    assert list_grants(db_session, "m1") == []


def test_revoke_cross_group_grant_is_403(client, db_session):
    from claimos.services.grants import create_grant
    g = create_grant(db_session, user_id="out", user_role="valuator", scope="group",
                     claim_ids=[], overrides={}, granted_by_id="out")
    r = client.post(f"/team/grants/{g.id}/revoke", follow_redirects=False)
    assert r.status_code == 403
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_team_grants.py -v`
Expected: FAIL (routes missing).

- [ ] **Step 3: Implement the endpoints** (add to `team.py`)

```python
from fastapi import Form
from claimos.models_grants import RoleGrant
from claimos.services.grants import GrantValidationError, create_grant, revoke_grant


@router.post("/users/{user_id}/grants")
def team_assign_grant(
    user_id: str,
    user_role: str = Form(...),
    scope: str = Form("group"),
    claim_ids: list[str] = Form(default=[]),
    user: CurrentUser = Depends(require_external_admin),
    db: Session = Depends(get_db),
):
    target = _load_own_member(db, user, user_id)
    # claim_ids must belong to the firm (defense in depth).
    if scope == "claims":
        owned = {
            c.id
            for c in db.query(Claim).filter(
                Claim.owner_group_id == user.group_id, Claim.id.in_(claim_ids)
            )
        }
        if set(claim_ids) - owned:
            raise HTTPException(status_code=400, detail="Claim not in your firm")
    try:
        create_grant(db, user_id=target.id, user_role=user_role, scope=scope,
                     claim_ids=claim_ids, overrides={}, granted_by_id=user.id)
    except GrantValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(url=f"/team/users/{user_id}", status_code=303)


@router.post("/grants/{grant_id}/revoke")
def team_revoke_grant(
    grant_id: str,
    user: CurrentUser = Depends(require_external_admin),
    db: Session = Depends(get_db),
):
    grant = db.get(RoleGrant, grant_id)
    if grant is None:
        raise HTTPException(status_code=404, detail="Grant not found")
    if grant.group_id != user.group_id:
        raise HTTPException(status_code=403, detail="Grant not in your firm")
    target_user_id = grant.user_id
    revoke_grant(db, grant_id)
    return RedirectResponse(url=f"/team/users/{target_user_id}", status_code=303)
```

- [ ] **Step 4: Assign form + revoke buttons in `user_detail.html`**

In the Roles & Access card: add a revoke `<form method="POST" action="/team/grants/{{ grant.id }}/revoke">` button per grant row, and below the table an **Assign a role** `<form method="POST" action="/team/users/{{ target.id }}/grants">` with:
- `<select name="user_role">` from `user_roles`.
- `<select name="scope" data-role="scope-select">` with `group` / `claims`.
- a claim multiselect wrapper `<div data-role="claim-picker" hidden><select name="claim_ids" multiple>…group_claims…</select></div>`.

- [ ] **Step 5: app.js — toggle the claim picker (no inline JS)**

In `src/claimos/static/app.js`, add a delegated `change` listener:

```javascript
document.addEventListener('change', function (e) {
  const sel = e.target.closest('[data-role="scope-select"]');
  if (!sel) return;
  const picker = sel.closest('form').querySelector('[data-role="claim-picker"]');
  if (picker) picker.hidden = sel.value !== 'claims';
});
```

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/test_team_grants.py tests/test_design_token_guard.py -v` → PASS; `uv run pytest -q` green.

- [ ] **Step 7: Format, lint, commit**

```bash
uv run ruff format . && uv run ruff format --check . && uv run ruff check .
git add src/claimos/routers/team.py src/claimos/templates/team/user_detail.html src/claimos/static/app.js tests/test_team_grants.py
git commit -m "feat: /team assign-role + revoke with conditional claim picker"
```

---

### Task 8: Per-grant override editor (endpoints + UI)

**Files:**
- Modify: `src/claimos/routers/team.py`
- Modify: `src/claimos/templates/team/user_detail.html` (override editor per grant)
- Test: `tests/test_team_grants.py` (extend)

**Interfaces:**
- Consumes: `grants.add_override`, `grants.remove_override`
- Produces:
  - `POST /team/grants/{grant_id}/overrides` (form: `object_type`, `role`) → redirect to member detail
  - `POST /team/grants/{grant_id}/overrides/{object_type}/remove` → redirect to member detail
  - Both tenant-checked (`grant.group_id == user.group_id`).

- [ ] **Step 1: Write the failing test**

```python
def test_add_and_remove_override_via_endpoint(client, db_session):
    from claimos.services.grants import create_grant
    g = create_grant(db_session, user_id="m1", user_role="photographer", scope="group",
                     claim_ids=[], overrides={}, granted_by_id="ea")
    r = client.post(f"/team/grants/{g.id}/overrides",
                    data={"object_type": "items", "role": "contributor"},
                    follow_redirects=False)
    assert r.status_code in (302, 303)
    from claimos.services.effective_permissions import group_effective_matrix
    assert group_effective_matrix(db_session, "m1", "eg")["items"] == "contributor"

    r2 = client.post(f"/team/grants/{g.id}/overrides/items/remove", follow_redirects=False)
    assert r2.status_code in (302, 303)
    assert group_effective_matrix(db_session, "m1", "eg")["items"] == "viewer"


def test_override_on_cross_group_grant_is_403(client, db_session):
    from claimos.services.grants import create_grant
    g = create_grant(db_session, user_id="out", user_role="photographer", scope="group",
                     claim_ids=[], overrides={}, granted_by_id="out")
    r = client.post(f"/team/grants/{g.id}/overrides",
                    data={"object_type": "items", "role": "contributor"},
                    follow_redirects=False)
    assert r.status_code == 403
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_team_grants.py -k override -v`
Expected: FAIL (routes missing).

- [ ] **Step 3: Implement** (add to `team.py`)

```python
from claimos.services.grants import add_override, remove_override


def _load_own_grant(db: Session, user: CurrentUser, grant_id: str) -> RoleGrant:
    grant = db.get(RoleGrant, grant_id)
    if grant is None:
        raise HTTPException(status_code=404, detail="Grant not found")
    if grant.group_id != user.group_id:
        raise HTTPException(status_code=403, detail="Grant not in your firm")
    return grant


@router.post("/grants/{grant_id}/overrides")
def team_add_override(
    grant_id: str,
    object_type: str = Form(...),
    role: str = Form(...),
    user: CurrentUser = Depends(require_external_admin),
    db: Session = Depends(get_db),
):
    grant = _load_own_grant(db, user, grant_id)
    try:
        add_override(db, grant_id, object_type, role)
    except GrantValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(url=f"/team/users/{grant.user_id}", status_code=303)


@router.post("/grants/{grant_id}/overrides/{object_type}/remove")
def team_remove_override(
    grant_id: str,
    object_type: str,
    user: CurrentUser = Depends(require_external_admin),
    db: Session = Depends(get_db),
):
    grant = _load_own_grant(db, user, grant_id)
    remove_override(db, grant_id, object_type)
    return RedirectResponse(url=f"/team/users/{grant.user_id}", status_code=303)
```

- [ ] **Step 4: Override editor UI in `user_detail.html`**

Under each grant row, render an expandable override area:
- List current overrides (`grant.overrides`): each object_type → role with a Remove `<form method="POST" action="/team/grants/{{ grant.id }}/overrides/{{ o.object_type }}/remove">`.
- An **Add override** `<form method="POST" action="/team/grants/{{ grant.id }}/overrides">` with `<select name="object_type">` from `object_types` and `<select name="role">` from `role_levels`.
- Render a small hint next to the form: "Overrides only raise a role above the assigned role's level." (Matches the allow-with-hint decision; no server enforcement of "must be higher".)

Plain form POSTs (no JS needed here; the page reloads on submit).

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_team_grants.py -v` → PASS; `uv run pytest -q` green.

- [ ] **Step 6: Format, lint, commit**

```bash
uv run ruff format . && uv run ruff format --check . && uv run ruff check .
git add src/claimos/routers/team.py src/claimos/templates/team/user_detail.html tests/test_team_grants.py
git commit -m "feat: /team per-grant override editor (add/remove)"
```

---

### Task 9: Invite member with role

**Files:**
- Modify: `src/claimos/routers/team.py`
- Create: `src/claimos/templates/team/invite.html`
- Test: `tests/test_team_invite.py` (create)

**Interfaces:**
- Consumes: `auth.generate_invite_code`, `auth.hash_token`, `roles.USER_ROLES`, `grants.create_grant`
- Produces:
  - `GET /team/users/invite` → `team/invite.html`
  - `POST /team/users/invite` (form: `email`, `display_name`, `user_role`, `scope`, `claim_ids`) → creates user (system_role from role) + initial grant; renders invite URL

- [ ] **Step 1: Write the failing test**

```python
# tests/test_team_invite.py — reuse the client/db fixtures from tests/test_team_users.py (eg/og, ea)
def test_invite_sets_system_role_and_creates_grant(client, db_session):
    r = client.post("/team/users/invite", data={
        "email": "new@acme.com", "display_name": "New Hire",
        "user_role": "photographer", "scope": "group",
    })
    assert r.status_code == 200
    from claimos.models_auth import User
    from claimos.services.grants import list_grants
    u = db_session.query(User).filter(User.email == "new@acme.com").first()
    assert u is not None and u.system_role == "external_user" and u.group_id == "eg"
    assert list_grants(db_session, u.id)[0].user_role == "photographer"


def test_invite_lawyer_is_external_admin(client, db_session):
    client.post("/team/users/invite", data={
        "email": "boss@acme.com", "display_name": "Boss",
        "user_role": "lawyer", "scope": "group",
    })
    from claimos.models_auth import User
    u = db_session.query(User).filter(User.email == "boss@acme.com").first()
    assert u.system_role == "external_admin"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_team_invite.py -v`
Expected: FAIL (route missing).

- [ ] **Step 3: Implement**

```python
import datetime
import uuid

from claimos.auth import generate_invite_code, hash_token
from claimos.roles import get_user_role


@router.get("/users/invite", response_class=HTMLResponse)
def team_invite_form(
    request: Request,
    user: CurrentUser = Depends(require_external_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    group_claims = (
        db.query(Claim).filter(Claim.owner_group_id == user.group_id).order_by(Claim.id).all()
    )
    return templates.TemplateResponse(
        request=request,
        name="team/invite.html",
        context={"user": user, "user_roles": USER_ROLES, "group_claims": group_claims},
    )


@router.post("/users/invite", response_class=HTMLResponse)
def team_invite(
    request: Request,
    email: str = Form(...),
    display_name: str = Form(...),
    user_role: str = Form(...),
    scope: str = Form("group"),
    claim_ids: list[str] = Form(default=[]),
    user: CurrentUser = Depends(require_external_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    role = get_user_role(user_role)
    if role is None:
        raise HTTPException(status_code=400, detail="Unknown user role")
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=400, detail="Email already registered")

    raw_code = generate_invite_code()
    expires_at = datetime.datetime.now(tz=datetime.timezone.utc) + datetime.timedelta(days=7)
    new_user = User(
        id=str(uuid.uuid4()),
        email=email,
        display_name=display_name,
        system_role=role.system_role,
        group_id=user.group_id,
        invite_code=hash_token(raw_code),
        invite_expires_at=expires_at,
    )
    db.add(new_user)
    db.commit()

    try:
        create_grant(db, user_id=new_user.id, user_role=user_role, scope=scope,
                     claim_ids=claim_ids, overrides={}, granted_by_id=user.id)
    except GrantValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    invite_url = str(request.base_url).rstrip("/") + f"/register/{raw_code}"
    members = db.query(User).filter(User.group_id == user.group_id).order_by(User.email).all()
    group = db.get(Group, user.group_id)
    return templates.TemplateResponse(
        request=request,
        name="team/users.html",
        context={"user": user, "group": group, "members": members, "invite_url": invite_url},
    )
```

`team/invite.html`: a form (email, display name, `user_role` select, scope select + conditional claim picker reusing the `data-role="scope-select"`/`data-role="claim-picker"` pattern from Task 7). `team/users.html` shows `invite_url` when present (mirror `admin/org/users.html`).

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_team_invite.py -v` → PASS; `uv run pytest -q` green.

- [ ] **Step 5: Format, lint, commit**

```bash
uv run ruff format . && uv run ruff format --check . && uv run ruff check .
git add src/claimos/routers/team.py src/claimos/templates/team/invite.html src/claimos/templates/team/users.html tests/test_team_invite.py
git commit -m "feat: /team invite member with role (sets system_role + initial grant)"
```

---

### Task 10: Claim access list — `GET /team/claims`

**Files:**
- Modify: `src/claimos/routers/team.py`
- Create: `src/claimos/templates/team/claims.html`
- Test: `tests/test_team_claims.py` (create)

**Interfaces:**
- Produces: `GET /team/claims` → list of the firm's claims (`owner_group_id == user.group_id`), each linking to `/team/claims/{id}/access`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_team_claims.py — reuse client/db fixtures (seed eg/og, ea; claims cA owned eg, cX owned og)
def test_claims_list_shows_own_firm_claims_only(client, db_session):
    from claimos.models import Claim
    db_session.add_all([Claim(id="cA", owner_group_id="eg", policyholder_name="Rossi"),
                        Claim(id="cX", owner_group_id="og", policyholder_name="Other")])
    db_session.commit()
    resp = client.get("/team/claims")
    assert resp.status_code == 200
    assert "Rossi" in resp.text
    assert "Other" not in resp.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_team_claims.py -v`
Expected: FAIL (route missing).

- [ ] **Step 3: Implement**

```python
@router.get("/claims", response_class=HTMLResponse)
def team_claims(
    request: Request,
    user: CurrentUser = Depends(require_external_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    claims = (
        db.query(Claim).filter(Claim.owner_group_id == user.group_id).order_by(Claim.id).all()
    )
    return templates.TemplateResponse(
        request=request,
        name="team/claims.html",
        context={"user": user, "claims": claims},
    )
```

`team/claims.html`: a `card` with a table (policyholder_name, claim label/status) each row linking to `/team/claims/{{ c.id }}/access`.

- [ ] **Step 4: Run tests + commit**

Run: `uv run pytest tests/test_team_claims.py -v` → PASS; `uv run pytest -q` green.

```bash
uv run ruff format . && uv run ruff format --check . && uv run ruff check .
git add src/claimos/routers/team.py src/claimos/templates/team/claims.html tests/test_team_claims.py
git commit -m "feat: /team claims list"
```

---

### Task 11: Per-claim access view — `GET /team/claims/{claim_id}/access`

**Files:**
- Modify: `src/claimos/routers/team.py`
- Create: `src/claimos/templates/team/claim_access.html`
- Test: `tests/test_team_claims.py` (extend)

**Interfaces:**
- Consumes: `effective_permissions.claim_members_access`
- Produces: `GET /team/claims/{claim_id}/access` → per-member resolved matrix for that claim; tenant-checked (`claim.owner_group_id == user.group_id`)

- [ ] **Step 1: Write the failing test**

```python
def test_claim_access_view_shows_resolved_roles(client, db_session):
    from claimos.models import Claim
    from claimos.models_auth import User
    from claimos.services.grants import create_grant
    db_session.add(Claim(id="cA", owner_group_id="eg", policyholder_name="Rossi"))
    db_session.add(User(id="ph", email="ph@acme.com", display_name="Photog",
                        system_role="external_user", group_id="eg"))
    db_session.commit()
    create_grant(db_session, user_id="ph", user_role="photographer", scope="group",
                 claim_ids=[], overrides={}, granted_by_id="ea")
    resp = client.get("/team/claims/cA/access")
    assert resp.status_code == 200
    assert "ph@acme.com" in resp.text
    assert "contributor" in resp.text  # photographer → contributor on evidence


def test_claim_access_cross_group_is_404(client, db_session):
    from claimos.models import Claim
    db_session.add(Claim(id="cX", owner_group_id="og", policyholder_name="Other"))
    db_session.commit()
    assert client.get("/team/claims/cX/access").status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_team_claims.py -k access -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

```python
from claimos.services.effective_permissions import claim_members_access


@router.get("/claims/{claim_id}/access", response_class=HTMLResponse)
def team_claim_access(
    claim_id: str,
    request: Request,
    user: CurrentUser = Depends(require_external_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    claim = db.get(Claim, claim_id)
    if claim is None or claim.owner_group_id != user.group_id:
        raise HTTPException(status_code=404, detail="Claim not found")
    rows = claim_members_access(db, user.group_id, claim_id)
    members = db.query(User).filter(User.group_id == user.group_id).order_by(User.email).all()
    return templates.TemplateResponse(
        request=request,
        name="team/claim_access.html",
        context={
            "user": user,
            "claim": claim,
            "rows": rows,
            "object_types": OBJECT_TYPES,
            "members": members,
            "user_roles": USER_ROLES,
        },
    )
```

`team/claim_access.html`: a matrix table — a column per `object_types`, a row per `(member, matrix)` in `rows` showing each object's resolved role (`—` for None), member email links to `/team/users/{{ member.id }}`. Below, a **Grant claim access** form (Task 12 wires the POST) — render the form now pointing at `/team/claims/{{ claim.id }}/grant` with a member select (`members`) + role select (`user_roles`).

- [ ] **Step 4: Run tests + commit**

Run: `uv run pytest tests/test_team_claims.py -v` → PASS; `uv run pytest -q` green.

```bash
uv run ruff format . && uv run ruff format --check . && uv run ruff check .
git add src/claimos/routers/team.py src/claimos/templates/team/claim_access.html tests/test_team_claims.py
git commit -m "feat: /team per-claim access view (resolved per-member matrix)"
```

---

### Task 12: Grant claim access from the per-claim view

**Files:**
- Modify: `src/claimos/routers/team.py`
- Test: `tests/test_team_claims.py` (extend)

**Interfaces:**
- Consumes: `grants.create_grant`
- Produces: `POST /team/claims/{claim_id}/grant` (form: `user_id`, `user_role`) → creates a **claims-scoped** grant narrowed to this claim; tenant-checked; redirect to the access view

- [ ] **Step 1: Write the failing test**

```python
def test_grant_claim_access_creates_claim_scoped_grant(client, db_session):
    from claimos.models import Claim
    from claimos.models_auth import User
    db_session.add(Claim(id="cA", owner_group_id="eg", policyholder_name="Rossi"))
    db_session.add(User(id="val", email="val@acme.com", display_name="Val",
                        system_role="external_user", group_id="eg"))
    db_session.commit()
    r = client.post("/team/claims/cA/grant",
                    data={"user_id": "val", "user_role": "valuator"},
                    follow_redirects=False)
    assert r.status_code in (302, 303)
    from claimos.services.grants import list_grants
    g = list_grants(db_session, "val")[0]
    assert g.scope == "claims" and [c.claim_id for c in g.claims] == ["cA"]


def test_grant_claim_access_rejects_cross_group_member(client, db_session):
    from claimos.models import Claim
    db_session.add(Claim(id="cA", owner_group_id="eg", policyholder_name="Rossi"))
    db_session.commit()
    r = client.post("/team/claims/cA/grant",
                    data={"user_id": "out", "user_role": "valuator"},
                    follow_redirects=False)
    assert r.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_team_claims.py -k grant_claim -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

```python
@router.post("/claims/{claim_id}/grant")
def team_grant_claim_access(
    claim_id: str,
    user_id: str = Form(...),
    user_role: str = Form(...),
    user: CurrentUser = Depends(require_external_admin),
    db: Session = Depends(get_db),
):
    claim = db.get(Claim, claim_id)
    if claim is None or claim.owner_group_id != user.group_id:
        raise HTTPException(status_code=404, detail="Claim not found")
    target = _load_own_member(db, user, user_id)
    try:
        create_grant(db, user_id=target.id, user_role=user_role, scope="claims",
                     claim_ids=[claim_id], overrides={}, granted_by_id=user.id)
    except GrantValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(url=f"/team/claims/{claim_id}/access", status_code=303)
```

- [ ] **Step 4: Run tests + commit**

Run: `uv run pytest tests/test_team_claims.py -v` → PASS; `uv run pytest -q` green.

```bash
uv run ruff format . && uv run ruff format --check . && uv run ruff check .
git add src/claimos/routers/team.py tests/test_team_claims.py
git commit -m "feat: /team grant claim-scoped access from per-claim view"
```

---

### Task 13: Docs — RBAC.md + BACKLOG.md

**Files:**
- Modify: `docs/RBAC.md`
- Modify: `docs/BACKLOG.md`

- [ ] **Step 1: Update `docs/RBAC.md`**

Add a "Team surface (external admins)" subsection under Admin Panels: external admins manage their firm at `/team` (Members, Claim Access) — role assignment, per-user overrides, group-wide effective matrix, per-claim resolved access, invite-with-role. Note they are redirected off `/admin/org` (except the `/admin/org/profile` carve-out), and that internal/system admins keep `/admin/org`. Note `system_admin` may also use `/team` (own-group-scoped).

- [ ] **Step 2: Update `docs/BACKLOG.md`**

Mark the "firm-facing Users page" item done (delivered by `/team`). Add follow-ups: **`/team/settings` firm-profile editor** (replaces the interim `/admin/org/profile` carve-out); unify internal/system admin cross-firm management onto a `/team`-style surface.

- [ ] **Step 3: Commit**

```bash
git add docs/RBAC.md docs/BACKLOG.md
git commit -m "docs: Team surface — RBAC.md + BACKLOG.md"
```

---

## Self-Review

**Spec coverage:**
- §2 surface/router/nav/redirect → Tasks 1, 5. §3.1 members list → Task 1. §3.2 member detail (grants + override editor + group effective matrix + claim-scoped list) → Tasks 3, 7, 8 (+ Task 2 service). §3.3 invite-with-role → Task 9. §3.4 claims list → Task 10. §3.5 per-claim view → Task 11 (+ grant → Task 12). §3.6 firm settings → intentionally deferred (backlog; interim `/admin/org/profile` carve-out in Task 5). §4 endpoints → Tasks 1,3,4,7,8,9,10,11,12. §4 services → Tasks 2, 6. §5 interactivity (conditional picker, no inline JS) → Task 7. §6 design tokens → guard test in Tasks 1,7. §7 testing → each task. §8 phases → Tasks map to phases 1(1–5),2(6–8),3(9),4(10–12),5(13+redirect in 5). §9 docs → Task 13.
- No gap: §3.6 is explicitly out of scope per the approved spec.

**Placeholder scan:** No "TBD"/"handle errors"/"similar to Task N". Template steps name the exact patterns to mirror (`admin/org/*.html`) and give concrete structure; the two forms rendered before their POST exists (assign form in Task 3→wired Task 7; grant form in Task 11→wired Task 12) are explicitly noted as "wired in Task N."

**Type consistency:** `require_external_admin`, `_load_own_member(db, user, user_id)`, `_load_own_grant(db, user, grant_id)` are defined once (Tasks 1/4/8) and reused. `group_effective_matrix(db, user_id, group_id)`, `claim_effective_matrix(db, user, claim_id)`, `claim_members_access(db, group_id, claim_id)` (Task 2) match their consumers (Tasks 3, 11). `add_override(db, grant_id, object_type, role)` / `remove_override(db, grant_id, object_type)` (Task 6) match Task 8. `create_grant(db, *, user_id, user_role, scope, claim_ids, overrides, granted_by_id)` used consistently (Tasks 7, 9, 12).
