"""Tests for matter sharing endpoints."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cvp.dependencies as deps
import cvp.models_access  # ensure matter_access table is registered  # noqa: F401
import cvp.models_auth  # ensure auth tables are registered on Base.metadata  # noqa: F401
from cvp.auth import hash_password
from cvp.models import Base, Matter
from cvp.models_auth import Group, User


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def seeded_share_db(db_session):
    ig = Group(id="ig", name="Internal", kind="internal")
    eg = Group(id="eg", name="External", kind="external")
    db_session.add_all([ig, eg])

    admin = User(
        id="ia",
        email="ia@test.com",
        display_name="Admin",
        password_hash=hash_password("testpassword1"),
        system_role="internal_admin",
        group_id="ig",
    )
    ext_user = User(
        id="eu",
        email="eu@test.com",
        display_name="Ext",
        password_hash=hash_password("testpassword1"),
        system_role="external_user",
        group_id="eg",
    )
    db_session.add_all([admin, ext_user])
    matter = Matter(id="m1", owner_group_id="ig", created_by_id="ia")
    db_session.add(matter)
    db_session.commit()
    return db_session


@pytest.fixture
def client(seeded_share_db, monkeypatch):
    from cvp.db import get_db
    from cvp.dependencies import CurrentUser, require_active_user
    from cvp.main import app

    def override_get_db():
        try:
            yield seeded_share_db
        finally:
            pass

    async def mock_admin():
        return CurrentUser(
            id="ia",
            email="ia@test.com",
            system_role="internal_admin",
            group_id="ig",
            group_kind="internal",
        )

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_active_user] = mock_admin
    # Bypass RBAC checks
    monkeypatch.setattr(deps, "_check_matter_access", lambda db, user, matter_id, role: True)

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


def test_grant_access(client):
    resp = client.post(
        "/api/matters/m1/access",
        data={"user_id": "eu", "role": "viewer"},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_list_access(client):
    # First grant access
    client.post("/api/matters/m1/access", data={"user_id": "eu", "role": "viewer"})
    resp = client.get("/api/matters/m1/access")
    assert resp.status_code == 200
    data = resp.json()
    assert any(item["user_id"] == "eu" for item in data)


def test_revoke_access(client):
    # Grant first
    client.post("/api/matters/m1/access", data={"user_id": "eu", "role": "viewer"})
    # Then revoke
    resp = client.delete("/api/matters/m1/access/eu")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_invalid_role(client):
    resp = client.post(
        "/api/matters/m1/access",
        data={"user_id": "eu", "role": "superuser"},
    )
    assert resp.status_code == 400


def test_grant_user_not_found(client):
    resp = client.post(
        "/api/matters/m1/access",
        data={"user_id": "nonexistent-user-id", "role": "viewer"},
    )
    assert resp.status_code == 404


def test_revoke_grant_not_found(client):
    # No grant exists for "eu" — revoke should 404
    resp = client.delete("/api/matters/m1/access/eu")
    assert resp.status_code == 404


def test_grant_cross_tenant_blocked(seeded_share_db, monkeypatch):
    """External admin cannot grant access to a user in a different group."""
    import cvp.dependencies as deps_local

    # Add an external_admin user in the "eg" group
    from cvp.auth import hash_password as hp
    from cvp.db import get_db
    from cvp.dependencies import CurrentUser, require_active_user
    from cvp.main import app
    from cvp.models_auth import User as U

    ea = U(
        id="ea",
        email="ea@test.com",
        display_name="ExtAdmin",
        password_hash=hp("testpassword1"),
        system_role="external_admin",
        group_id="eg",
    )
    seeded_share_db.add(ea)
    seeded_share_db.commit()

    def override_get_db():
        try:
            yield seeded_share_db
        finally:
            pass

    async def mock_ext_admin():
        return CurrentUser(
            id="ea",
            email="ea@test.com",
            system_role="external_admin",
            group_id="eg",
            group_kind="external",
        )

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_active_user] = mock_ext_admin
    monkeypatch.setattr(deps_local, "_check_matter_access", lambda db, user, matter_id, role: True)

    try:
        with TestClient(app) as c:
            # "ia" is in group "ig" (internal), external admin is in "eg" — cross-tenant
            resp = c.post(
                "/api/matters/m1/access",
                data={"user_id": "ia", "role": "viewer"},
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 403
