"""Org-admin grant management endpoints. Follows tests/test_admin_org.py client setup."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import claimos.models_auth  # noqa: F401 — register models with Base
import claimos.models_grants  # noqa: F401 — register models with Base
from claimos.models import Base
from claimos.models_auth import Group, User
from claimos.services.grants import list_grants


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture
def seed_org(db_session):
    eg = Group(id="eg", name="Acme Law", kind="external")
    other_g = Group(id="og", name="Other Firm", kind="external")
    db_session.add_all([eg, other_g])

    member1 = User(
        id="member1",
        email="member1@test.com",
        display_name="Member One",
        system_role="external_user",
        group_id="eg",
    )
    outsider = User(
        id="outsider",
        email="outsider@test.com",
        display_name="Outsider",
        system_role="external_user",
        group_id="og",
    )
    db_session.add_all([member1, outsider])
    db_session.commit()

    class SeedOrg:
        db = db_session

    return SeedOrg()


@pytest.fixture
def org_client(db_session, seed_org):
    """Internal admin actor: exercises panel functionality that survived the
    /team redirect (external_admin is now bounced off /admin/org/* to /team,
    except /admin/org/profile — see test_team_redirect.py). Internal/system
    admins remain the panel's real audience."""
    from claimos.db import get_db
    from claimos.dependencies import require_active_user
    from claimos.main import app
    from claimos.routers.admin.org import _require_org_admin_or_above

    def override_get_db():
        yield db_session

    async def mock_internal_admin():
        from claimos.dependencies import CurrentUser

        return CurrentUser(
            id="ia",
            email="ia@test.com",
            system_role="internal_admin",
            group_id=None,
            group_kind="internal",
        )

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[_require_org_admin_or_above] = mock_internal_admin
    app.dependency_overrides[require_active_user] = mock_internal_admin
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def external_admin_client(db_session, seed_org):
    """External-admin actor with the router-level /team redirect bypassed.

    Real external_admin traffic never reaches these routes anymore (the
    `_redirect_external_admin` dependency bounces it to /team first). But the
    per-route cross-group guards inside org_assign_grant/org_revoke_grant are
    still real defense-in-depth code, so this fixture overrides
    `_redirect_external_admin` directly (in addition to auth) to keep
    exercising them at the unit level.
    """
    from claimos.db import get_db
    from claimos.main import app
    from claimos.routers.admin.org import _redirect_external_admin, _require_org_admin_or_above

    def override_get_db():
        yield db_session

    async def mock_external_admin():
        from claimos.dependencies import CurrentUser

        return CurrentUser(
            id="ea",
            email="ea@test.com",
            system_role="external_admin",
            group_id="eg",
            group_kind="external",
        )

    async def noop_redirect() -> None:
        return None

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[_require_org_admin_or_above] = mock_external_admin
    app.dependency_overrides[_redirect_external_admin] = noop_redirect
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_org_admin_assigns_group_scoped_photographer(org_client, seed_org):
    resp = org_client.post(
        "/admin/org/users/member1/grants",
        data={"user_role": "photographer", "scope": "group"},
    )
    assert resp.status_code in (200, 303)
    grants = list_grants(seed_org.db, "member1")
    assert len(grants) == 1
    assert grants[0].user_role == "photographer"
    assert grants[0].scope == "group"


def test_org_admin_cannot_grant_cross_group(external_admin_client, seed_org):
    """Defense-in-depth: even with the /team redirect bypassed, external_admin
    still cannot grant a role to a user outside their own group."""
    resp = external_admin_client.post(
        "/admin/org/users/outsider/grants",
        data={"user_role": "photographer", "scope": "group"},
    )
    assert resp.status_code == 403


def test_org_admin_revokes_group_scoped_grant(org_client, seed_org):
    org_client.post(
        "/admin/org/users/member1/grants",
        data={"user_role": "photographer", "scope": "group"},
    )
    grants = list_grants(seed_org.db, "member1")
    assert len(grants) == 1
    grant_id = grants[0].id

    resp = org_client.post(f"/admin/org/grants/{grant_id}/revoke")
    assert resp.status_code in (200, 303)
    assert list_grants(seed_org.db, "member1") == []


def test_org_admin_cannot_revoke_cross_group_grant(external_admin_client, seed_org, db_session):
    """Defense-in-depth: even with the /team redirect bypassed, external_admin
    still cannot revoke a grant belonging to a user outside their own group."""
    from claimos.services.grants import create_grant

    grant = create_grant(
        db_session,
        user_id="outsider",
        user_role="photographer",
        scope="group",
        claim_ids=[],
        overrides={},
        granted_by_id="other-admin",
    )
    resp = external_admin_client.post(f"/admin/org/grants/{grant.id}/revoke")
    assert resp.status_code == 403
    assert len(list_grants(db_session, "outsider")) == 1


def test_org_user_detail_renders_grants_section(org_client, seed_org):
    org_client.post(
        "/admin/org/users/member1/grants",
        data={"user_role": "photographer", "scope": "group"},
    )
    resp = org_client.get("/admin/org/users/member1")
    assert resp.status_code == 200
    assert "Roles &amp; Access" in resp.text or "Roles &" in resp.text
    assert "photographer" in resp.text
