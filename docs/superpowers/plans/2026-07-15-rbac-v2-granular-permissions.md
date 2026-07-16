# RBAC v2 — Granular Object-Level Permissions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single-role-per-claim model with object-level permissions driven by named User Roles, group-scoped and claim-narrowable, with per-user overrides — for external (firm) users only.

**Architecture:** A fixed code registry (`roles.py`) maps each User Role to a `system_role` + `object_type → claim_role` profile. Three new tables (`role_grants`, `role_grant_claims`, `role_grant_overrides`) store per-user grants. The `require_claim_role` dependency gains an `object_type` argument; the resolver computes the effective claim role for an `(external user, claim, object_type)` and compares it against the route's minimum. Internal users keep the legacy `claim_access` path unchanged.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.x, Alembic, pytest, ruff. SQLite (local/tests) + Postgres (prod).

## Global Constraints

- Python 3.11+, `uv` package manager. No new dependencies.
- Currency untouched here, but never introduce `float` currency.
- UUIDs as strings; timestamps as timezone-aware UTC.
- Type hints everywhere; modern syntax (`X | None`, `list[str]`).
- Pure functions in registry/resolver where possible; DB access only in the resolver/service layers.
- Run `uv run ruff format .` then `uv run ruff format --check .` (zero files reformatted) and `uv run ruff check .` before every commit. Line length 100.
- No inline JS event handlers in templates (`onclick=` etc.) — CSP blocks them. Use `data-*` + delegated listeners in `src/claimos/static/app.js`.
- Migrations live in `migrations/versions/`. Generate with `uv run alembic revision --autogenerate -m "..."` and hand-verify.
- Tests live in `tests/` mirroring `src/claimos/`. New model modules MUST be imported in `tests/conftest.py` so `Base.metadata.create_all` sees them.
- Claim-role hierarchy is `viewer < editor < contributor < approver < manager`.
- Scope is external users only. Internal (`system_admin`, `internal_admin`, `internal_user`, `specialist`) behavior is unchanged.

---

### Task 1: User Role registry (`roles.py`)

**Files:**
- Create: `src/claimos/roles.py`
- Test: `tests/test_roles.py`

**Interfaces:**
- Produces:
  - `OBJECT_TYPES: tuple[str, ...]`
  - `@dataclass(frozen=True) class UserRole` with fields `key: str`, `system_role: str`, `profile: dict[str, str]`, `single_claim_only: bool`
  - `USER_ROLES: dict[str, UserRole]`
  - `get_user_role(key: str) -> UserRole | None`
  - `role_for_object(role_key: str, object_type: str) -> str | None`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_roles.py
from claimos.roles import (
    OBJECT_TYPES,
    USER_ROLES,
    get_user_role,
    role_for_object,
)


def test_object_types_are_canonical():
    assert OBJECT_TYPES == (
        "items", "evidence", "reports", "exports", "crops",
        "audit_logs", "rooms", "item_groups", "comments", "users",
    )


def test_lawyer_and_paralegal_are_manager_on_everything():
    for key in ("lawyer", "paralegal"):
        role = get_user_role(key)
        assert role is not None
        assert role.system_role == "external_admin"
        assert all(role.profile[obj] == "manager" for obj in OBJECT_TYPES)


def test_adjuster_is_approver_on_its_objects():
    role = get_user_role("adjuster")
    assert role.system_role == "external_user"
    expected = {
        "users", "items", "evidence", "reports", "exports",
        "crops", "audit_logs", "rooms", "item_groups",
    }
    assert set(role.profile) == expected
    assert all(v == "approver" for v in role.profile.values())


def test_photographer_split_levels():
    assert role_for_object("photographer", "evidence") == "contributor"
    assert role_for_object("photographer", "comments") == "contributor"
    assert role_for_object("photographer", "rooms") == "contributor"
    assert role_for_object("photographer", "item_groups") == "contributor"
    assert role_for_object("photographer", "items") == "viewer"
    assert role_for_object("photographer", "exports") is None  # not in profile


def test_claimant_is_single_claim_and_viewer():
    role = get_user_role("claimant")
    assert role.single_claim_only is True
    assert set(role.profile) == {"items", "evidence", "reports", "audit_logs"}
    assert all(v == "viewer" for v in role.profile.values())


def test_valuator_profile():
    role = get_user_role("valuator")
    assert set(role.profile) == {"items", "comments", "crops", "audit_logs"}
    assert all(v == "contributor" for v in role.profile.values())


def test_role_for_object_unknown_role():
    assert role_for_object("nope", "items") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_roles.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'claimos.roles'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/claimos/roles.py
"""Fixed, code-defined User Role registry for external (firm) users.

A User Role bundles a default system role with a map of object_type -> claim role.
External-only for now; internal users are governed by the legacy claim_access model.
Product-defined and fixed (like depreciation.py) — not admin-editable.
"""

from dataclasses import dataclass

OBJECT_TYPES: tuple[str, ...] = (
    "items",
    "evidence",
    "reports",
    "exports",
    "crops",
    "audit_logs",
    "rooms",
    "item_groups",
    "comments",
    "users",
)


@dataclass(frozen=True)
class UserRole:
    key: str
    system_role: str
    profile: dict[str, str]  # object_type -> claim role
    single_claim_only: bool = False


def _all_objects(role: str) -> dict[str, str]:
    return {obj: role for obj in OBJECT_TYPES}


USER_ROLES: dict[str, UserRole] = {
    "lawyer": UserRole("lawyer", "external_admin", _all_objects("manager")),
    "paralegal": UserRole("paralegal", "external_admin", _all_objects("manager")),
    "adjuster": UserRole(
        "adjuster",
        "external_user",
        {
            "users": "approver",
            "items": "approver",
            "evidence": "approver",
            "reports": "approver",
            "exports": "approver",
            "crops": "approver",
            "audit_logs": "approver",
            "rooms": "approver",
            "item_groups": "approver",
        },
    ),
    "claimant": UserRole(
        "claimant",
        "external_user",
        {
            "items": "viewer",
            "evidence": "viewer",
            "reports": "viewer",
            "audit_logs": "viewer",
        },
        single_claim_only=True,
    ),
    "photographer": UserRole(
        "photographer",
        "external_user",
        {
            "evidence": "contributor",
            "comments": "contributor",
            "rooms": "contributor",
            "item_groups": "contributor",
            "items": "viewer",
        },
    ),
    "valuator": UserRole(
        "valuator",
        "external_user",
        {
            "items": "contributor",
            "comments": "contributor",
            "crops": "contributor",
            "audit_logs": "contributor",
        },
    ),
}


def get_user_role(key: str) -> UserRole | None:
    return USER_ROLES.get(key)


def role_for_object(role_key: str, object_type: str) -> str | None:
    role = USER_ROLES.get(role_key)
    if role is None:
        return None
    return role.profile.get(object_type)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_roles.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Format, lint, commit**

```bash
uv run ruff format . && uv run ruff format --check . && uv run ruff check .
git add src/claimos/roles.py tests/test_roles.py
git commit -m "feat: add fixed User Role registry (roles.py)"
```

---

### Task 2: Grant ORM models + migration

**Files:**
- Create: `src/claimos/models_grants.py`
- Modify: `tests/conftest.py` (add import so tables are created)
- Create: `migrations/versions/<rev>_rbac_v2_grants.py` (via autogenerate)
- Test: `tests/test_models_grants.py`

**Interfaces:**
- Produces (all `Base` subclasses in `claimos.models_grants`):
  - `RoleGrant`: `id: str`, `user_id: str`, `group_id: str`, `user_role: str`, `scope: str` (`"group"|"claims"`), `granted_by_id: str`, `created_at`, `updated_at`; relationships `claims: list[RoleGrantClaim]`, `overrides: list[RoleGrantOverride]`
  - `RoleGrantClaim`: `id: str`, `grant_id: str`, `claim_id: str`
  - `RoleGrantOverride`: `id: str`, `grant_id: str`, `object_type: str`, `role: str`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models_grants.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from claimos.models import Base
from claimos.models_grants import RoleGrant, RoleGrantClaim, RoleGrantOverride


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_grant_with_claims_and_overrides_persist():
    db = _session()
    grant = RoleGrant(
        id="grant1",
        user_id="u1",
        group_id="g1",
        user_role="photographer",
        scope="claims",
        granted_by_id="admin1",
    )
    db.add(grant)
    db.add(RoleGrantClaim(id="rgc1", grant_id="grant1", claim_id="claimA"))
    db.add(RoleGrantOverride(id="rgo1", grant_id="grant1", object_type="items", role="contributor"))
    db.commit()

    loaded = db.get(RoleGrant, "grant1")
    assert loaded.scope == "claims"
    assert loaded.user_role == "photographer"
    assert [c.claim_id for c in loaded.claims] == ["claimA"]
    assert loaded.overrides[0].object_type == "items"
    assert loaded.overrides[0].role == "contributor"


def test_group_scoped_grant_has_no_claim_rows():
    db = _session()
    grant = RoleGrant(
        id="grant2",
        user_id="u2",
        group_id="g1",
        user_role="adjuster",
        scope="group",
        granted_by_id="admin1",
    )
    db.add(grant)
    db.commit()
    assert db.get(RoleGrant, "grant2").claims == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_models_grants.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'claimos.models_grants'`

- [ ] **Step 3: Write the models**

```python
# src/claimos/models_grants.py
"""ORM models for RBAC v2 group-scoped role grants (external users)."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from claimos.models import Base, _new_uuid


class RoleGrant(Base):
    """A User Role assigned to a user within a group, group-wide or claim-narrowed."""

    __tablename__ = "role_grants"
    __table_args__ = (
        UniqueConstraint("user_id", "group_id", "user_role", "scope", name="uq_role_grant"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    group_id: Mapped[str] = mapped_column(
        String, ForeignKey("groups.id"), nullable=False, index=True
    )
    user_role: Mapped[str] = mapped_column(String, nullable=False)  # roles.py key
    scope: Mapped[str] = mapped_column(String, nullable=False)  # "group" | "claims"
    granted_by_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    claims: Mapped[list["RoleGrantClaim"]] = relationship(
        "RoleGrantClaim", back_populates="grant", cascade="all, delete-orphan"
    )
    overrides: Mapped[list["RoleGrantOverride"]] = relationship(
        "RoleGrantOverride", back_populates="grant", cascade="all, delete-orphan"
    )


class RoleGrantClaim(Base):
    """Narrows a claims-scoped grant to a specific claim."""

    __tablename__ = "role_grant_claims"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    grant_id: Mapped[str] = mapped_column(
        String, ForeignKey("role_grants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    claim_id: Mapped[str] = mapped_column(
        String, ForeignKey("claims.id"), nullable=False, index=True
    )

    grant: Mapped["RoleGrant"] = relationship("RoleGrant", back_populates="claims")


class RoleGrantOverride(Base):
    """Per-object bump on top of a grant's User Role profile."""

    __tablename__ = "role_grant_overrides"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    grant_id: Mapped[str] = mapped_column(
        String, ForeignKey("role_grants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    object_type: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)

    grant: Mapped["RoleGrant"] = relationship("RoleGrant", back_populates="overrides")
```

- [ ] **Step 4: Register models in conftest**

In `tests/conftest.py`, add alongside the other model imports (after `import claimos.models_feedback  # noqa: F401`):

```python
import claimos.models_grants  # noqa: F401
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_models_grants.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Generate the migration**

Run: `uv run alembic revision --autogenerate -m "rbac v2 grants"`
Then open the generated file in `migrations/versions/` and verify it `create_table`s `role_grants`, `role_grant_claims`, `role_grant_overrides` with the `uq_role_grant` unique constraint and the two FK indexes. Remove any unrelated autogenerated drift (there should be none). Confirm `downgrade()` drops the three tables in reverse order.

- [ ] **Step 7: Apply and verify migration round-trips**

Run: `uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head`
Expected: no errors; tables present after final upgrade.

- [ ] **Step 8: Format, lint, commit**

```bash
uv run ruff format . && uv run ruff format --check . && uv run ruff check .
git add src/claimos/models_grants.py tests/test_models_grants.py tests/conftest.py migrations/versions/
git commit -m "feat: add role_grants tables + migration"
```

---

### Task 3: Grants service (create / validate / list / revoke)

**Files:**
- Create: `src/claimos/services/grants.py`
- Test: `tests/test_grants_service.py`

**Interfaces:**
- Consumes: `roles.get_user_role`, `models_grants.RoleGrant/RoleGrantClaim/RoleGrantOverride`, `models_auth.User`, `models.Claim`, `services.access_cache.invalidate_user`
- Produces:
  - `class GrantValidationError(ValueError)`
  - `create_grant(db, *, user_id, user_role, scope, claim_ids, overrides, granted_by_id) -> RoleGrant`
    - `claim_ids: list[str]` (required non-empty when `scope="claims"`), `overrides: dict[str, str]` (object_type→role)
  - `list_grants(db, user_id) -> list[RoleGrant]`
  - `revoke_grant(db, grant_id) -> None`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_grants_service.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from claimos.models import Base, Claim
from claimos.models_auth import Group, User
from claimos.services.grants import GrantValidationError, create_grant, list_grants, revoke_grant


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    s.add_all(
        [
            Group(id="eg", name="Firm", kind="external"),
            Group(id="ig", name="Int", kind="internal"),
            User(id="ph", email="p@f.com", display_name="P", password_hash="x",
                 system_role="external_user", group_id="eg"),
            User(id="adm", email="a@f.com", display_name="A", password_hash="x",
                 system_role="external_admin", group_id="eg"),
            Claim(id="cA", owner_group_id="eg"),
            Claim(id="cB", owner_group_id="eg"),
        ]
    )
    s.commit()
    yield s
    s.close()


def test_create_group_scoped_grant(db):
    g = create_grant(db, user_id="ph", user_role="photographer", scope="group",
                     claim_ids=[], overrides={}, granted_by_id="adm")
    assert g.scope == "group"
    assert g.claims == []
    assert g.group_id == "eg"  # derived from grantee's group


def test_create_claims_scoped_grant_with_override(db):
    g = create_grant(db, user_id="ph", user_role="photographer", scope="claims",
                     claim_ids=["cA"], overrides={"items": "contributor"}, granted_by_id="adm")
    assert {c.claim_id for c in g.claims} == {"cA"}
    assert {(o.object_type, o.role) for o in g.overrides} == {("items", "contributor")}


def test_claims_scope_requires_at_least_one_claim(db):
    with pytest.raises(GrantValidationError):
        create_grant(db, user_id="ph", user_role="photographer", scope="claims",
                     claim_ids=[], overrides={}, granted_by_id="adm")


def test_claimant_must_be_single_claim(db):
    with pytest.raises(GrantValidationError):
        create_grant(db, user_id="ph", user_role="claimant", scope="group",
                     claim_ids=[], overrides={}, granted_by_id="adm")
    with pytest.raises(GrantValidationError):
        create_grant(db, user_id="ph", user_role="claimant", scope="claims",
                     claim_ids=["cA", "cB"], overrides={}, granted_by_id="adm")
    ok = create_grant(db, user_id="ph", user_role="claimant", scope="claims",
                      claim_ids=["cA"], overrides={}, granted_by_id="adm")
    assert ok.user_role == "claimant"


def test_unknown_role_rejected(db):
    with pytest.raises(GrantValidationError):
        create_grant(db, user_id="ph", user_role="wizard", scope="group",
                     claim_ids=[], overrides={}, granted_by_id="adm")


def test_list_and_revoke(db):
    g = create_grant(db, user_id="ph", user_role="valuator", scope="group",
                     claim_ids=[], overrides={}, granted_by_id="adm")
    assert [x.id for x in list_grants(db, "ph")] == [g.id]
    revoke_grant(db, g.id)
    assert list_grants(db, "ph") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_grants_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'claimos.services.grants'`

- [ ] **Step 3: Write the service**

```python
# src/claimos/services/grants.py
"""Create/validate/list/revoke RBAC v2 role grants for external users."""

from sqlalchemy.orm import Session

from claimos.models_auth import User
from claimos.models_grants import RoleGrant, RoleGrantClaim, RoleGrantOverride
from claimos.roles import get_user_role
from claimos.services.access_cache import invalidate_user


class GrantValidationError(ValueError):
    """Raised when a grant request violates a structural rule."""


def create_grant(
    db: Session,
    *,
    user_id: str,
    user_role: str,
    scope: str,
    claim_ids: list[str],
    overrides: dict[str, str],
    granted_by_id: str,
) -> RoleGrant:
    role = get_user_role(user_role)
    if role is None:
        raise GrantValidationError(f"Unknown user role: {user_role}")
    if scope not in ("group", "claims"):
        raise GrantValidationError(f"Invalid scope: {scope}")

    grantee = db.get(User, user_id)
    if grantee is None:
        raise GrantValidationError("Grantee not found")
    if grantee.group_id is None:
        raise GrantValidationError("Grantee has no group")

    if role.single_claim_only:
        if scope != "claims" or len(claim_ids) != 1:
            raise GrantValidationError(f"{user_role} must be scoped to exactly one claim")
    if scope == "claims" and not claim_ids:
        raise GrantValidationError("claims scope requires at least one claim")

    grant = RoleGrant(
        user_id=user_id,
        group_id=grantee.group_id,
        user_role=user_role,
        scope=scope,
        granted_by_id=granted_by_id,
    )
    db.add(grant)
    db.flush()

    if scope == "claims":
        for cid in claim_ids:
            db.add(RoleGrantClaim(grant_id=grant.id, claim_id=cid))
    for object_type, ov_role in overrides.items():
        db.add(RoleGrantOverride(grant_id=grant.id, object_type=object_type, role=ov_role))

    db.commit()
    db.refresh(grant)
    invalidate_user(user_id)
    return grant


def list_grants(db: Session, user_id: str) -> list[RoleGrant]:
    return db.query(RoleGrant).filter(RoleGrant.user_id == user_id).all()


def revoke_grant(db: Session, grant_id: str) -> None:
    grant = db.get(RoleGrant, grant_id)
    if grant is None:
        return
    user_id = grant.user_id
    db.delete(grant)
    db.commit()
    invalidate_user(user_id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_grants_service.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Format, lint, commit**

```bash
uv run ruff format . && uv run ruff format --check . && uv run ruff check .
git add src/claimos/services/grants.py tests/test_grants_service.py
git commit -m "feat: add grants service (create/validate/list/revoke)"
```

---

### Task 4: Object-aware resolver + dependency wiring

**Files:**
- Modify: `src/claimos/dependencies.py` (`ROLE_HIERARCHY`, add `_external_effective_role`, extend `_check_claim_access`, extend `require_claim_role`)
- Modify: `src/claimos/services/access_cache.py` (add `object_type` to key + signatures)
- Test: `tests/test_resolver.py`

**Interfaces:**
- Consumes: `roles.role_for_object`, `models_grants.*`, `models.Claim`, `models_access.ClaimAccess`
- Produces:
  - `ROLE_HIERARCHY = {"viewer":0,"editor":1,"contributor":2,"approver":3,"manager":4}`
  - `_external_effective_role(db, user, claim_id, object_type) -> str | None`
  - `_check_claim_access(db, user, claim_id, minimum_role, object_type=None) -> bool`
  - `require_claim_role(minimum_role: str, object_type: str | None = None)` factory
  - `access_cache.check_claim_access_cached(db, user, claim_id, minimum_role, object_type=None) -> bool`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_resolver.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from claimos.dependencies import CurrentUser, _check_claim_access, _external_effective_role
from claimos.models import Base, Claim
from claimos.models_auth import Group, User
from claimos.services.grants import create_grant


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    s.add_all(
        [
            Group(id="eg", name="Firm", kind="external"),
            User(id="ph", email="p@f.com", display_name="P", password_hash="x",
                 system_role="external_user", group_id="eg"),
            User(id="adm", email="a@f.com", display_name="A", password_hash="x",
                 system_role="external_admin", group_id="eg"),
            Claim(id="cA", owner_group_id="eg"),
            Claim(id="cB", owner_group_id="eg"),
        ]
    )
    s.commit()
    yield s
    s.close()


def _cu(uid, role="external_user"):
    return CurrentUser(id=uid, email="x@f.com", system_role=role,
                       group_id="eg", group_kind="external")


def test_group_scope_covers_all_group_claims(db):
    create_grant(db, user_id="ph", user_role="photographer", scope="group",
                 claim_ids=[], overrides={}, granted_by_id="adm")
    assert _external_effective_role(db, _cu("ph"), "cA", "evidence") == "contributor"
    assert _external_effective_role(db, _cu("ph"), "cB", "evidence") == "contributor"
    assert _external_effective_role(db, _cu("ph"), "cA", "items") == "viewer"
    assert _external_effective_role(db, _cu("ph"), "cA", "exports") is None


def test_claims_scope_only_covers_listed_claim(db):
    create_grant(db, user_id="ph", user_role="photographer", scope="claims",
                 claim_ids=["cA"], overrides={}, granted_by_id="adm")
    assert _external_effective_role(db, _cu("ph"), "cA", "evidence") == "contributor"
    assert _external_effective_role(db, _cu("ph"), "cB", "evidence") is None


def test_override_raises_object_level(db):
    create_grant(db, user_id="ph", user_role="photographer", scope="group",
                 claim_ids=[], overrides={"items": "contributor"}, granted_by_id="adm")
    assert _external_effective_role(db, _cu("ph"), "cA", "items") == "contributor"


def test_max_across_multiple_grants(db):
    create_grant(db, user_id="ph", user_role="photographer", scope="group",
                 claim_ids=[], overrides={}, granted_by_id="adm")
    create_grant(db, user_id="ph", user_role="valuator", scope="group",
                 claim_ids=[], overrides={}, granted_by_id="adm")
    # photographer=viewer on items, valuator=contributor on items -> contributor
    assert _external_effective_role(db, _cu("ph"), "cA", "items") == "contributor"


def test_check_claim_access_uses_object_type_for_external(db):
    create_grant(db, user_id="ph", user_role="photographer", scope="group",
                 claim_ids=[], overrides={}, granted_by_id="adm")
    # contributor on evidence clears a contributor minimum
    assert _check_claim_access(db, _cu("ph"), "cA", "contributor", "evidence") is True
    # viewer on items does NOT clear an editor minimum
    assert _check_claim_access(db, _cu("ph"), "cA", "editor", "items") is False


def test_external_admin_owns_claim_is_manager(db):
    # No grant needed; external_admin whose group owns the claim => manager-level.
    assert _check_claim_access(db, _cu("adm", "external_admin"), "cA", "manager", "items") is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_resolver.py -v`
Expected: FAIL with `ImportError: cannot import name '_external_effective_role'`

- [ ] **Step 3: Update `ROLE_HIERARCHY` and add the resolver**

In `src/claimos/dependencies.py`, replace the `ROLE_HIERARCHY` dict (currently at ~line 186) with:

```python
ROLE_HIERARCHY: dict[str, int] = {
    "viewer": 0,
    "editor": 1,
    "contributor": 2,
    "approver": 3,
    "manager": 4,
}
```

Add this function directly above `_check_claim_access`:

```python
def _external_effective_role(
    db: Session,
    user: "CurrentUser",
    claim_id: str,
    object_type: str,
) -> str | None:
    """Highest claim role an external user has for a given object type on a claim.

    Considers every role_grant whose scope covers the claim, applies per-object
    overrides, and returns the max in ROLE_HIERARCHY (or None => no access).
    """
    from claimos.models_grants import RoleGrant, RoleGrantClaim, RoleGrantOverride
    from claimos.roles import role_for_object

    claim = db.get(Claim, claim_id)
    if claim is None:
        return None

    grants = (
        db.query(RoleGrant)
        .filter(RoleGrant.user_id == user.id, RoleGrant.group_id == user.group_id)
        .all()
    )
    best_rank = -1
    best_role: str | None = None
    for grant in grants:
        if grant.scope == "group":
            if claim.owner_group_id != grant.group_id:
                continue
        else:  # "claims"
            linked = (
                db.query(RoleGrantClaim)
                .filter(RoleGrantClaim.grant_id == grant.id, RoleGrantClaim.claim_id == claim_id)
                .first()
            )
            if linked is None:
                continue

        role = role_for_object(grant.user_role, object_type)
        override = (
            db.query(RoleGrantOverride)
            .filter(
                RoleGrantOverride.grant_id == grant.id,
                RoleGrantOverride.object_type == object_type,
            )
            .first()
        )
        if override is not None:
            if role is None or ROLE_HIERARCHY.get(override.role, -1) > ROLE_HIERARCHY.get(role, -1):
                role = override.role
        if role is None:
            continue
        rank = ROLE_HIERARCHY.get(role, -1)
        if rank > best_rank:
            best_rank = rank
            best_role = role
    return best_role
```

- [ ] **Step 4: Extend `_check_claim_access` with `object_type`**

Replace the body of `_check_claim_access` so its signature becomes
`(db, user, claim_id, minimum_role, object_type=None)` and external users with an
`object_type` route resolve via grants:

```python
def _check_claim_access(
    db: Session,
    user: CurrentUser,
    claim_id: str,
    minimum_role: str,
    object_type: str | None = None,
) -> bool:
    """Check if user has at least minimum_role on a claim (object-aware for external)."""
    if user.system_role == "system_admin":
        return True

    claim = db.get(Claim, claim_id)
    if claim is None:
        return False

    if claim.owner_group_id == user.group_id and user.system_role in (
        "internal_admin",
        "external_admin",
    ):
        return True

    # External users on object-tagged routes resolve via role_grants.
    if object_type is not None and user.group_kind == "external":
        eff = _external_effective_role(db, user, claim_id, object_type)
        if eff is None:
            return False
        return ROLE_HIERARCHY.get(eff, -1) >= ROLE_HIERARCHY.get(minimum_role, 999)

    # Legacy path: internal users, or untagged routes.
    access = (
        db.query(ClaimAccess)
        .filter(ClaimAccess.user_id == user.id, ClaimAccess.claim_id == claim_id)
        .first()
    )
    if access is None:
        return False
    return ROLE_HIERARCHY.get(access.role, -1) >= ROLE_HIERARCHY.get(minimum_role, 999)
```

- [ ] **Step 5: Thread `object_type` through `require_claim_role`**

Change the factory signature to `def require_claim_role(minimum_role: str, object_type: str | None = None):`
and update the final access check inside its inner `dependency` to pass `object_type`:

```python
        from claimos.services.access_cache import check_claim_access_cached

        if not check_claim_access_cached(db, user, claim_id, minimum_role, object_type):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
```

- [ ] **Step 6: Make the cache object-aware**

In `src/claimos/services/access_cache.py`:
- Change the module cache type comment and key to a 4-tuple.
- Update `_check_claim_access` wrapper and `check_claim_access_cached` to accept `object_type`.

```python
# key -> (loaded_at, allowed); key is (user_id, claim_id, minimum_role, object_type)
_cache: dict[tuple[str, str, str, str | None], tuple[float, bool]] = {}


def _check_claim_access(
    db: Session,
    user: "CurrentUser",
    claim_id: str,
    minimum_role: str,
    object_type: str | None = None,
) -> bool:
    return _deps._check_claim_access(db, user, claim_id, minimum_role, object_type)


def check_claim_access_cached(
    db: Session,
    user: "CurrentUser",
    claim_id: str,
    minimum_role: str,
    object_type: str | None = None,
) -> bool:
    if user.system_role == "system_admin":
        return True

    key = (user.id, claim_id, minimum_role, object_type)
    entry = _cache.get(key)
    if entry is not None:
        loaded_at, allowed = entry
        if (_now() - loaded_at) < _TTL_SECONDS:
            return allowed

    allowed = _check_claim_access(db, user, claim_id, minimum_role, object_type)
    _cache[key] = (_now(), allowed)
    if len(_cache) > _MAX_ENTRIES:
        _evict_oldest()
    return allowed
```

Update `invalidate_claim` / `invalidate_user` index references (`key[1]` for claim, `key[0]` for user) — they stay correct since claim_id is still index 1 and user_id index 0.

- [ ] **Step 7: Run resolver tests + full suite for regressions**

Run: `uv run pytest tests/test_resolver.py tests/test_rbac.py tests/test_access_cache.py tests/test_dependencies.py -v`
Expected: PASS. If `test_access_cache.py` calls the cache with 3 args, the new default `object_type=None` keeps it green.

- [ ] **Step 8: Format, lint, commit**

```bash
uv run ruff format . && uv run ruff format --check . && uv run ruff check .
git add src/claimos/dependencies.py src/claimos/services/access_cache.py tests/test_resolver.py
git commit -m "feat: object-aware claim-access resolver + approver in hierarchy"
```

---

### Task 5: Item approval split + tag items/crops/evidence routes

**Files:**
- Modify: `src/claimos/routers/items.py` (remove `confirmed` write from PATCH; add confirm/unconfirm endpoints; tag routes)
- Modify: `src/claimos/routers/crops.py` (tag routes `"crops"`)
- Modify: `src/claimos/routers/evidence.py` (tag routes `"evidence"`)
- Modify: `src/claimos/routers/serp.py` (tag `"items"` — serp searches belong to items)
- Modify: `src/claimos/routers/vision.py` (tag `"evidence"` — vision runs act on evidence)
- Modify: `src/claimos/static/app.js` (wire the confirm toggle via delegated listener)
- Modify: item edit template that renders the confirm control (`src/claimos/templates/` — locate the confirm checkbox in the item edit partial)
- Test: `tests/test_item_approval.py`

**Interfaces:**
- Consumes: `require_claim_role(minimum_role, object_type)` from Task 4
- Produces: `POST /api/items/{item_id}/confirm` and `POST /api/items/{item_id}/unconfirm`, both `Depends(require_claim_role("approver", "items"))`, returning the refreshed item row HTML (same `_item_row_html` used elsewhere).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_item_approval.py
"""Approver gate on item confirmation. Uses the shared app test client pattern."""

from claimos.dependencies import _check_claim_access
from claimos.models import Base, Claim, Category, Item
from claimos.models_auth import Group, User
from claimos.services.grants import create_grant
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from claimos.dependencies import CurrentUser


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    s.add_all([
        Group(id="eg", name="F", kind="external"),
        User(id="val", email="v@f.com", display_name="V", password_hash="x",
             system_role="external_user", group_id="eg"),
        User(id="adm", email="a@f.com", display_name="A", password_hash="x",
             system_role="external_admin", group_id="eg"),
        Claim(id="cA", owner_group_id="eg"),
    ])
    s.commit()
    return s


def _cu(uid):
    return CurrentUser(id=uid, email="x@f.com", system_role="external_user",
                       group_id="eg", group_kind="external")


def test_valuator_cannot_approve_but_can_edit():
    db = _db()
    create_grant(db, user_id="val", user_role="valuator", scope="group",
                 claim_ids=[], overrides={}, granted_by_id="adm")
    # contributor on items clears editor, but not approver
    assert _check_claim_access(db, _cu("val"), "cA", "editor", "items") is True
    assert _check_claim_access(db, _cu("val"), "cA", "approver", "items") is False


def test_valuator_with_items_approver_override_can_approve():
    db = _db()
    create_grant(db, user_id="val", user_role="valuator", scope="group",
                 claim_ids=[], overrides={"items": "approver"}, granted_by_id="adm")
    assert _check_claim_access(db, _cu("val"), "cA", "approver", "items") is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_item_approval.py -v`
Expected: FAIL — `test_valuator_cannot_approve_but_can_edit` fails only if the approval endpoints/logic aren't wired; the two resolver-level assertions should already pass from Task 4. (If both pass immediately, proceed — they lock in the gate; the route work below is still required for Step 3.)

- [ ] **Step 3: Add confirm/unconfirm endpoints; stop writing `confirmed` in PATCH**

In `src/claimos/routers/items.py`:

1. In `update_item` (the `PATCH /api/items/{item_id}`), remove the `confirmed: bool = Form(False)` parameter and any line that assigns `item.confirmed = confirmed` / sets `confirmed_by_id` / `confirmed_at`. Leave all other field writes intact.

2. Add two endpoints (place near the other item routes; reuse the existing `_item_row_html` helper and `SessionLocal`):

```python
@router.post("/api/items/{item_id}/confirm", response_class=HTMLResponse)
def confirm_item(
    request: Request,
    item_id: str,
    user: CurrentUser = Depends(require_claim_role("approver", "items")),
) -> HTMLResponse:
    return _set_item_confirmed(item_id, True, user)


@router.post("/api/items/{item_id}/unconfirm", response_class=HTMLResponse)
def unconfirm_item(
    request: Request,
    item_id: str,
    user: CurrentUser = Depends(require_claim_role("approver", "items")),
) -> HTMLResponse:
    return _set_item_confirmed(item_id, False, user)


def _set_item_confirmed(item_id: str, value: bool, user: CurrentUser) -> HTMLResponse:
    from datetime import datetime, timezone

    db = SessionLocal()
    try:
        item = db.query(Item).options(selectinload(Item.crops)).filter(Item.id == item_id).first()
        if item is None:
            raise HTTPException(status_code=404)
        item.confirmed = value
        item.confirmed_by_id = user.id if value else None
        item.confirmed_at = datetime.now(timezone.utc) if value else None
        db.commit()
        db.refresh(item)
        categories, rooms, item_groups = _get_context(item.claim_id, db)
        html = _item_row_html(item, categories, rooms, item_groups)
    finally:
        db.close()
    return HTMLResponse(html)
```

- [ ] **Step 4: Tag object types on the existing routes**

Mechanical edits — add the second positional arg to each `require_claim_role(...)`:

- `items.py`: every `require_claim_role("viewer"|"editor"|"contributor"|"manager")` → append `, "items"`.
- `crops.py`: every `require_claim_role("contributor")` → `, "crops"`.
- `evidence.py`: every `require_claim_role(...)` → `, "evidence"`.
- `serp.py`: every `require_claim_role("editor")` → `, "items"`.
- `vision.py`: every `require_claim_role("contributor")` → `, "evidence"`.

- [ ] **Step 5: Rewire the confirm control in the template + app.js**

Locate the confirm checkbox in the item edit partial (search templates for `confirmed`). Replace the inline-submitted checkbox with a button carrying `data-action="confirm-item"` / `data-action="unconfirm-item"` and `data-item-id="{{ item.id }}"`, rendered **only when** the current user may approve (pass an `can_approve` flag into the row context; compute it in the route via `_check_claim_access(db, user, item.claim_id, "approver", "items")`). In `src/claimos/static/app.js`, extend the existing delegated click listener (see the pattern around lines 225–275) to POST to `/api/items/{id}/confirm` or `/unconfirm` via `htmx.ajax` / fetch and swap the returned row. No inline `onclick`.

- [ ] **Step 6: Run the approval + regression tests**

Run: `uv run pytest tests/test_item_approval.py tests/test_items_template.py tests/test_crops_router.py tests/test_evidence_upload.py tests/test_vision_router.py -v`
Expected: PASS. Fix any test that asserted the old editor-can-confirm behavior by updating it to the approver gate.

- [ ] **Step 7: Format, lint, commit**

```bash
uv run ruff format . && uv run ruff format --check . && uv run ruff check .
git add src/claimos/routers/items.py src/claimos/routers/crops.py src/claimos/routers/evidence.py src/claimos/routers/serp.py src/claimos/routers/vision.py src/claimos/static/app.js src/claimos/templates/ tests/test_item_approval.py
git commit -m "feat: approver-gated item confirmation + tag item/evidence/crop routes"
```

---

### Task 6: Tag remaining routers + apply ladder deltas

**Files:**
- Modify: `src/claimos/routers/rooms.py` (create/edit → `contributor`; delete stays `manager`; tag `"rooms"`)
- Modify: `src/claimos/routers/item_groups.py` (create/edit → `contributor`; delete stays `manager`; tag `"item_groups"`)
- Modify: `src/claimos/routers/exports.py` (generate/download → `contributor`; tag `"exports"` — but see reports note)
- Modify: `src/claimos/routers/comments.py` (tag `"comments"`)
- Modify: `src/claimos/routers/claims.py` (report view/generate routes → tag `"reports"`; claim read routes → tag `"items"` for the claim workspace view, or leave untagged if internal-only)
- Modify: `src/claimos/routers/sharing.py` (tag `"users"`; grant/revoke stay `manager`, list → `contributor`)
- Test: `tests/test_ladder_enforcement.py`

**Interfaces:**
- Consumes: `require_claim_role(minimum_role, object_type)`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ladder_enforcement.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from claimos.dependencies import CurrentUser, _check_claim_access
from claimos.models import Base, Claim
from claimos.models_auth import Group, User
from claimos.services.grants import create_grant


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    s.add_all([
        Group(id="eg", name="F", kind="external"),
        User(id="ph", email="p@f.com", display_name="P", password_hash="x",
             system_role="external_user", group_id="eg"),
        User(id="adj", email="j@f.com", display_name="J", password_hash="x",
             system_role="external_user", group_id="eg"),
        User(id="adm", email="a@f.com", display_name="A", password_hash="x",
             system_role="external_admin", group_id="eg"),
        Claim(id="cA", owner_group_id="eg"),
    ])
    s.commit()
    yield s
    s.close()


def _cu(uid):
    return CurrentUser(id=uid, email="x@f.com", system_role="external_user",
                       group_id="eg", group_kind="external")


def test_photographer_can_create_rooms_and_item_groups(db):
    create_grant(db, user_id="ph", user_role="photographer", scope="group",
                 claim_ids=[], overrides={}, granted_by_id="adm")
    assert _check_claim_access(db, _cu("ph"), "cA", "contributor", "rooms") is True
    assert _check_claim_access(db, _cu("ph"), "cA", "contributor", "item_groups") is True
    # ...but cannot export (not in profile) or delete rooms (needs manager)
    assert _check_claim_access(db, _cu("ph"), "cA", "contributor", "exports") is False
    assert _check_claim_access(db, _cu("ph"), "cA", "manager", "rooms") is False


def test_adjuster_can_export_and_view_users_but_not_manage_users(db):
    create_grant(db, user_id="adj", user_role="adjuster", scope="group",
                 claim_ids=[], overrides={}, granted_by_id="adm")
    assert _check_claim_access(db, _cu("adj"), "cA", "contributor", "exports") is True
    assert _check_claim_access(db, _cu("adj"), "cA", "contributor", "users") is True
    assert _check_claim_access(db, _cu("adj"), "cA", "manager", "users") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ladder_enforcement.py -v`
Expected: These are resolver-level assertions and should PASS from Task 4's logic (the profiles already encode the levels). If they pass, they lock in the ladder; proceed to wire the routes so real HTTP requests honor them.

- [ ] **Step 3: Apply the route edits**

- `rooms.py`: the create and edit endpoints change `require_claim_role("manager")` → `require_claim_role("contributor", "rooms")`; the delete endpoint → `require_claim_role("manager", "rooms")`; any view → `require_claim_role("viewer", "rooms")`.
- `item_groups.py`: create/edit `require_claim_role("manager"|"editor")` → `require_claim_role("contributor", "item_groups")`; delete → `require_claim_role("manager", "item_groups")`.
- `exports.py`: each `require_claim_role("manager")` for generate/download → `require_claim_role("contributor", "exports")`. (If a route is specifically a PDF *report*, tag it `"reports"` instead — see Step 4.)
- `comments.py`: `require_claim_role("viewer")` → `require_claim_role("viewer", "comments")`.
- `sharing.py`: `list_access` → `require_claim_role("contributor", "users")`; `grant_access`/`revoke_access` stay at manager → `require_claim_role("manager", "users")`.
- `claims.py`: claim workspace read (`require_claim_role("viewer")`) → `require_claim_role("viewer", "items")`; claim settings/manager routes → `require_claim_role("manager", "items")`. Leave any purely-internal claim CRUD untagged (internal users use the legacy path).

- [ ] **Step 4: Classify reports vs exports**

Inspect `exports.py` routes. Tag CSV/XLSX (Xactimate) export routes as `"exports"`. Tag the PDF report generation/preview route(s) as `"reports"` with minimum `contributor` (generate) / `viewer` (preview). This lets a Claimant (`viewer` on reports) preview but not export, and an Adjuster (`approver`) do both.

- [ ] **Step 5: Run enforcement + router regression tests**

Run: `uv run pytest tests/test_ladder_enforcement.py tests/test_item_groups_router.py tests/test_comments.py tests/test_sharing.py tests/test_csv_export.py -v`
Expected: PASS. Update any router test that assumed the old manager minimum on rooms/item_groups/exports.

- [ ] **Step 6: Format, lint, commit**

```bash
uv run ruff format . && uv run ruff format --check . && uv run ruff check .
git add src/claimos/routers/ tests/test_ladder_enforcement.py
git commit -m "feat: tag remaining routers with object types + ladder deltas"
```

---

### Task 7: Migrate existing external `claim_access` → `role_grants`

**Files:**
- Create: `migrations/versions/<rev>_migrate_external_claim_access.py` (data migration; depends on Task 2 migration)
- Modify: `src/claimos/roles.py` (add a synthetic `"_custom"` profile helper for "same role on all objects")
- Test: `tests/test_claim_access_migration.py`

**Interfaces:**
- Consumes: `models_access.ClaimAccess`, `models_auth.User`, `models_grants.*`, `roles`
- Produces: after migration, each external `claim_access` row becomes a `role_grants` row (`scope="claims"`, one `role_grant_claims`) whose per-object resolution equals the old single role on every object type; the old external `claim_access` rows are deleted. Internal rows untouched.

- [ ] **Step 1: Add the uniform-role helper to `roles.py`**

Extend `role_for_object` to honor a synthetic role key `"_uniform:<role>"` meaning "that role on every object type":

```python
def role_for_object(role_key: str, object_type: str) -> str | None:
    if role_key.startswith("_uniform:"):
        return role_key.split(":", 1)[1]
    role = USER_ROLES.get(role_key)
    if role is None:
        return None
    return role.profile.get(object_type)
```

Add a unit test in `tests/test_roles.py`:

```python
def test_uniform_synthetic_role():
    from claimos.roles import role_for_object
    assert role_for_object("_uniform:contributor", "items") == "contributor"
    assert role_for_object("_uniform:contributor", "exports") == "contributor"
```

Run: `uv run pytest tests/test_roles.py -v` → PASS.

- [ ] **Step 2: Write the migration parity test**

```python
# tests/test_claim_access_migration.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from claimos.migrate_claim_access import migrate_external_claim_access
from claimos.models import Base, Claim
from claimos.models_access import ClaimAccess
from claimos.models_auth import Group, User
from claimos.models_grants import RoleGrant
from claimos.dependencies import CurrentUser, _check_claim_access


def test_external_grant_parity_after_migration():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    db.add_all([
        Group(id="eg", name="F", kind="external"),
        Group(id="ig", name="I", kind="internal"),
        User(id="eu", email="e@f.com", display_name="E", password_hash="x",
             system_role="external_user", group_id="eg"),
        User(id="iu", email="i@i.com", display_name="I", password_hash="x",
             system_role="internal_user", group_id="ig"),
        Claim(id="cA", owner_group_id="eg"),
        ClaimAccess(id="a1", user_id="eu", claim_id="cA", role="contributor", granted_by_id="x"),
        ClaimAccess(id="a2", user_id="iu", claim_id="cA", role="viewer", granted_by_id="x"),
    ])
    db.commit()

    migrate_external_claim_access(db)

    # External row converted to a grant; internal row untouched.
    assert db.query(RoleGrant).filter(RoleGrant.user_id == "eu").count() == 1
    assert db.query(ClaimAccess).filter(ClaimAccess.user_id == "eu").count() == 0
    assert db.query(ClaimAccess).filter(ClaimAccess.user_id == "iu").count() == 1

    eu = CurrentUser(id="eu", email="e@f.com", system_role="external_user",
                     group_id="eg", group_kind="external")
    # Parity: old contributor role still clears contributor on any object.
    assert _check_claim_access(db, eu, "cA", "contributor", "evidence") is True
    assert _check_claim_access(db, eu, "cA", "manager", "evidence") is False
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_claim_access_migration.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'claimos.migrate_claim_access'`

- [ ] **Step 4: Write the reusable migration function**

```python
# src/claimos/migrate_claim_access.py
"""Convert external users' single-role claim_access rows into RBAC v2 grants."""

from sqlalchemy.orm import Session

from claimos.models_access import ClaimAccess
from claimos.models_auth import User
from claimos.models_grants import RoleGrant, RoleGrantClaim


def migrate_external_claim_access(db: Session) -> int:
    """Idempotent-ish: converts and deletes external claim_access rows. Returns count."""
    rows = db.query(ClaimAccess).all()
    migrated = 0
    for row in rows:
        user = db.get(User, row.user_id)
        if user is None or user.group_id is None:
            continue
        group = user.group
        if group is None or group.kind != "external":
            continue  # leave internal rows alone
        grant = RoleGrant(
            user_id=row.user_id,
            group_id=user.group_id,
            user_role=f"_uniform:{row.role}",
            scope="claims",
            granted_by_id=row.granted_by_id,
        )
        db.add(grant)
        db.flush()
        db.add(RoleGrantClaim(grant_id=grant.id, claim_id=row.claim_id))
        db.delete(row)
        migrated += 1
    db.commit()
    return migrated
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_claim_access_migration.py -v`
Expected: PASS.

- [ ] **Step 6: Wrap it in an Alembic data migration**

Create a new revision (`uv run alembic revision -m "migrate external claim_access"`) whose `upgrade()` opens a session and calls `migrate_external_claim_access`:

```python
def upgrade() -> None:
    from sqlalchemy.orm import Session
    from claimos.migrate_claim_access import migrate_external_claim_access

    bind = op.get_bind()
    session = Session(bind=bind)
    migrate_external_claim_access(session)


def downgrade() -> None:
    # One-way data migration; external grants are not reverted to claim_access.
    pass
```

Set `down_revision` to the Task 2 grants revision.

- [ ] **Step 7: Run full suite**

Run: `uv run pytest -q`
Expected: PASS across the suite.

- [ ] **Step 8: Format, lint, commit**

```bash
uv run ruff format . && uv run ruff format --check . && uv run ruff check .
git add src/claimos/migrate_claim_access.py src/claimos/roles.py tests/test_claim_access_migration.py tests/test_roles.py migrations/versions/
git commit -m "feat: migrate external claim_access to role grants"
```

---

### Task 8: Minimal `/admin/org` grant management

**Files:**
- Modify: `src/claimos/routers/admin/org.py` (add grant assign/list/revoke endpoints)
- Modify/Create: org panel template partial for grants (follow existing `templates/admin/org/` patterns)
- Modify: `src/claimos/static/app.js` if any interactivity is needed (delegated listeners only)
- Test: `tests/test_admin_org_grants.py`

**Interfaces:**
- Consumes: `services.grants.create_grant/list_grants/revoke_grant`, `roles.USER_ROLES`, `roles.OBJECT_TYPES`
- Produces:
  - `POST /admin/org/users/{user_id}/grants` (form: `user_role`, `scope`, `claim_ids` (multi), `override_<object_type>` optional) — guarded by the existing `_require_org_admin_or_above`, with a tenant check that the target user is in the admin's group.
  - `POST /admin/org/grants/{grant_id}/revoke`
  - A grants section on the org user detail page listing current grants.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_admin_org_grants.py
"""Org-admin grant management endpoints. Follows tests/test_admin_org.py client setup."""

from claimos.services.grants import list_grants
# Reuse the app/client + external_admin login helpers from tests/test_admin_org.py.
# This test asserts an external_admin can assign a Photographer group-scoped grant
# to a member of their own group, and that a cross-group target is rejected (403).


def test_org_admin_assigns_group_scoped_photographer(org_client, seed_org):
    # seed_org provides: external_admin session + a member user "member1" in the same group
    resp = org_client.post(
        "/admin/org/users/member1/grants",
        data={"user_role": "photographer", "scope": "group"},
    )
    assert resp.status_code in (200, 303)
    grants = list_grants(seed_org.db, "member1")
    assert len(grants) == 1
    assert grants[0].user_role == "photographer"
    assert grants[0].scope == "group"


def test_org_admin_cannot_grant_cross_group(org_client, seed_org):
    resp = org_client.post(
        "/admin/org/users/outsider/grants",
        data={"user_role": "photographer", "scope": "group"},
    )
    assert resp.status_code == 403
```

> Implementer note: mirror the fixtures in `tests/test_admin_org.py` (it already builds an external_admin client and org members). Add `member1` and an `outsider` (different group) to that seed, exposed via a small `seed_org`/`org_client` fixture pair in this test file or `conftest.py`.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_admin_org_grants.py -v`
Expected: FAIL (404 on the new route / missing fixtures).

- [ ] **Step 3: Add the endpoints to `org.py`**

```python
from fastapi import Form
from claimos.roles import OBJECT_TYPES, USER_ROLES
from claimos.services.grants import GrantValidationError, create_grant, list_grants, revoke_grant


@router.post("/users/{user_id}/grants")
def assign_grant(
    user_id: str,
    user_role: str = Form(...),
    scope: str = Form("group"),
    claim_ids: list[str] = Form(default=[]),
    user: CurrentUser = Depends(_require_org_admin_or_above),
    db: Session = Depends(get_db),
):
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user.system_role == "external_admin" and target.group_id != user.group_id:
        raise HTTPException(status_code=403, detail="Cannot grant outside your group")
    try:
        create_grant(
            db,
            user_id=user_id,
            user_role=user_role,
            scope=scope,
            claim_ids=claim_ids,
            overrides={},  # override editor added with the Users-page slice
            granted_by_id=user.id,
        )
    except GrantValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return HTMLResponse("", status_code=200)  # or redirect/refresh partial


@router.post("/grants/{grant_id}/revoke")
def revoke(
    grant_id: str,
    user: CurrentUser = Depends(_require_org_admin_or_above),
    db: Session = Depends(get_db),
):
    grant = db.get(__import__("claimos.models_grants", fromlist=["RoleGrant"]).RoleGrant, grant_id)
    if grant is None:
        raise HTTPException(status_code=404)
    if user.system_role == "external_admin" and grant.group_id != user.group_id:
        raise HTTPException(status_code=403)
    revoke_grant(db, grant_id)
    return HTMLResponse("", status_code=200)
```

> Clean up the inline `__import__` into a top-of-file `from claimos.models_grants import RoleGrant` import; it's written inline here only to keep the snippet self-contained.

- [ ] **Step 4: Render current grants on the org user detail page**

In the org user-detail template (`templates/admin/org/user_detail.html`), add a "Roles & Access" section listing `list_grants(db, user.id)` (role, scope, claims) with a revoke button (`data-action`, delegated in app.js — no inline JS) and a small form to assign a role (`<select name="user_role">` from `USER_ROLES`, scope radio, optional claim multiselect). Pass `user_roles=USER_ROLES` and the group's claims into the template context from the detail route.

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_admin_org_grants.py tests/test_admin_org.py -v`
Expected: PASS.

- [ ] **Step 6: Format, lint, commit**

```bash
uv run ruff format . && uv run ruff format --check . && uv run ruff check .
git add src/claimos/routers/admin/org.py src/claimos/templates/admin/org/ src/claimos/static/app.js tests/test_admin_org_grants.py tests/conftest.py
git commit -m "feat: minimal org-panel grant management (assign/list/revoke)"
```

---

### Task 9: Docs

**Files:**
- Modify: `docs/RBAC.md` (rewrite for RBAC v2)
- Modify: `docs/data-model.md` (three new tables + migration note)
- Modify: `docs/BACKLOG.md` (Users page slice; fold-in-internal-users slice)

- [ ] **Step 1: Rewrite `docs/RBAC.md`**

Document: the six external User Roles and their profiles (§2 of the spec); the `viewer<editor<contributor<approver<manager` hierarchy with approver = contributor + item approval; group-scoped grants with claim-narrowing and the claimant single-claim rule; the per-object action ladder (§6 of the spec); the resolution algorithm; and **correct the stale line** that says external groups cannot own claims — firms own their claims via `owner_group_id`. Update the test scenarios to the new model (photographer upload-not-edit, adjuster approves, claimant single-claim isolation).

- [ ] **Step 2: Update `docs/data-model.md`**

Add `role_grants`, `role_grant_claims`, `role_grant_overrides` with column definitions and the rationale (per-object roles, group scope, overrides). Note the external `claim_access` → grants data migration and that internal `claim_access` is retained.

- [ ] **Step 3: Update `docs/BACKLOG.md`**

Add two items: (1) firm-facing **Users page** replacing `/admin/org` screens for Lawyers/Paralegals (own spec + `@DESIGN.md` pass; includes the override editor UI); (2) **fold internal users into RBAC v2** (define internal user roles; migrate internal `claim_access`).

- [ ] **Step 4: Commit**

```bash
git add docs/RBAC.md docs/data-model.md docs/BACKLOG.md
git commit -m "docs: RBAC v2 — roles, grants, ladder, migration, backlog"
```

---

## Self-Review

**Spec coverage:**
- §2 registry → Task 1. §3 tables → Task 2. Grant creation/validation (claimant single-claim, group match) → Task 3. §4 approver/confirm → Task 5. §5 resolver + `require_claim_role(object_type)` + cache → Task 4. §6 ladder deltas → Tasks 5–6. §7 system role default → surfaced in Task 8 assign flow + docs (invite defaulting is org-panel/backlog UI; the column already exists). §8 org plumbing → Task 8. §9 migration → Task 7. §10 docs → Task 9. §11 testing → each task's tests. §12 follow-ups → Task 9 backlog.
- Gap noted: §7 "default system_role from user role at invite" is only partially realized (the column exists and is set at invite today). Full auto-defaulting from the assigned User Role belongs with the Users-page slice; the current org invite flow already sets system_role. No separate task needed now — documented in Task 9.

**Placeholder scan:** No "TBD"/"handle edge cases"/"similar to Task N". Route-tagging steps enumerate exact files and the exact object_type per file. The one inline `__import__` in Task 8 is explicitly flagged to be replaced with a top-level import.

**Type consistency:** `_external_effective_role`, `_check_claim_access(..., object_type=None)`, `require_claim_role(minimum_role, object_type=None)`, and `check_claim_access_cached(..., object_type=None)` share the same signatures across Tasks 4–8. `create_grant(db, *, user_id, user_role, scope, claim_ids, overrides, granted_by_id)` is used identically in Tasks 3–8. `role_for_object` gains the `_uniform:` branch in Task 7 without breaking Task 1's callers.
