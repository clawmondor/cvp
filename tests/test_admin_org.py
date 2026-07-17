"""Tests for External Admin (Org) panel."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import claimos.models_auth  # noqa: F401 — register models with Base
from claimos.models import Base, Claim
from claimos.models_access import ClaimAccess
from claimos.models_auth import Group, User


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
def org_client(db_session):
    from claimos.db import get_db
    from claimos.dependencies import require_active_user
    from claimos.main import app
    from claimos.routers.admin.org import _require_org_admin_or_above

    eg = Group(id="eg", name="Acme Law", kind="external")
    db_session.add(eg)
    db_session.commit()

    def override_get_db():
        yield db_session

    async def mock_internal_admin():
        # These tests exercise general panel functionality (dashboard rendering,
        # users listing, legacy grant validation) rather than external-admin-specific
        # access boundaries, so they run as internal_admin — the panel's remaining
        # audience now that external_admin is redirected to /team. Cross-tenant
        # access-boundary coverage for external_admin lives in test_admin_org_grants.py
        # and the new test_team_redirect.py.
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
    # Router-level `_redirect_external_admin` depends on `require_active_user` directly
    # (not `_require_org_admin_or_above`), so it must be overridden too or these
    # requests 401 in any environment without dev auto-login (e.g. CI).
    app.dependency_overrides[require_active_user] = mock_internal_admin
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_org_dashboard_accessible(org_client):
    resp = org_client.get("/admin/org/?group_id=eg")
    assert resp.status_code == 200


def test_org_users_page(org_client):
    resp = org_client.get("/admin/org/users?group_id=eg")
    assert resp.status_code == 200


def test_org_dashboard_uses_unified_shell(org_client):
    resp = org_client.get("/admin/org/?group_id=eg")
    assert resp.status_code == 200
    assert 'href="/dashboard"' in resp.text
    assert 'href="/admin/org/users?group_id=eg"' in resp.text
    assert "bg-admin-800" not in resp.text


@pytest.fixture
def org_client_with_claim(db_session, org_client):
    """Seeds a claim owned by the external-admin's group, plus an internal-group
    target user and an external-group target user, on top of the `org_client`
    fixture's Group("eg") and CurrentUser("ea", group_id="eg")."""
    ig = Group(id="ig", name="Internal", kind="internal")
    internal_target = User(
        id="internal-target",
        email="internal-target@test.com",
        display_name="Internal Target",
        system_role="internal_user",
        group_id="ig",
    )
    external_target = User(
        id="external-target",
        email="external-target@test.com",
        display_name="External Target",
        system_role="external_user",
        group_id="eg",
    )
    claim = Claim(id="claim1", owner_group_id="eg")
    db_session.add_all([ig, internal_target, external_target, claim])
    db_session.commit()
    return org_client


def test_legacy_grant_rejects_external_target(org_client_with_claim):
    """I1: the legacy claim-access grant screen must not silently no-op for
    external target users — resolver only reads role_grants for them."""
    resp = org_client_with_claim.post(
        "/admin/org/claims/claim1/access",
        data={"user_id": "external-target", "role": "viewer"},
    )
    assert resp.status_code == 400
    assert "role grant" in resp.json()["detail"].lower()


def test_legacy_grant_succeeds_for_internal_target(org_client_with_claim, db_session):
    """Internal target users still use the legacy claim_access path."""
    resp = org_client_with_claim.post(
        "/admin/org/claims/claim1/access",
        data={"user_id": "internal-target", "role": "viewer"},
    )
    assert resp.status_code == 200
    row = (
        db_session.query(ClaimAccess)
        .filter(ClaimAccess.user_id == "internal-target", ClaimAccess.claim_id == "claim1")
        .first()
    )
    assert row is not None
    assert row.role == "viewer"
