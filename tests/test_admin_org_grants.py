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
    from claimos.db import get_db
    from claimos.main import app
    from claimos.routers.admin.org import _require_org_admin_or_above

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

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[_require_org_admin_or_above] = mock_external_admin
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


def test_org_admin_cannot_grant_cross_group(org_client, seed_org):
    resp = org_client.post(
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


def test_org_admin_cannot_revoke_cross_group_grant(org_client, seed_org, db_session):
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
    resp = org_client.post(f"/admin/org/grants/{grant.id}/revoke")
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
