"""Tests for System Admin panel."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cvp.models_auth  # ensure auth tables are registered on Base.metadata  # noqa: F401
from cvp.dependencies import CurrentUser, require_system_admin
from cvp.models import Base
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
def admin_client(db_session):
    from cvp.db import get_db
    from cvp.main import app

    async def mock_admin():
        return CurrentUser(
            id="sa",
            email="sa@test.com",
            system_role="system_admin",
            group_id="ig",
            group_kind="internal",
        )

    def override_get_db():
        yield db_session

    app.dependency_overrides[require_system_admin] = mock_admin
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def seeded_client(db_session):
    """Client with a pre-seeded Group and User in the in-memory DB."""
    from cvp.db import get_db
    from cvp.main import app

    # Seed a group
    group = Group(id="test-group-id", name="Test Group", kind="internal")
    db_session.add(group)

    # Seed an existing user
    existing_user = User(
        id="existing-user-id",
        email="existing@test.com",
        display_name="Existing User",
        system_role="internal_user",
        group_id="test-group-id",
        is_active=True,
    )
    db_session.add(existing_user)
    db_session.commit()

    async def mock_admin():
        return CurrentUser(
            id="sa",
            email="sa@test.com",
            system_role="system_admin",
            group_id="ig",
            group_kind="internal",
        )

    def override_get_db():
        yield db_session

    app.dependency_overrides[require_system_admin] = mock_admin
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c, db_session
    app.dependency_overrides.clear()


def test_system_dashboard_accessible(admin_client):
    resp = admin_client.get("/admin/system/")
    assert resp.status_code == 200


def test_system_users_page(admin_client):
    resp = admin_client.get("/admin/system/users")
    assert resp.status_code == 200


def test_system_invite_user_creates_user(seeded_client):
    client, db = seeded_client
    resp = client.post(
        "/admin/system/users/invite",
        data={
            "email": "newuser@test.com",
            "display_name": "New User",
            "system_role": "specialist",
            "group_id": "test-group-id",
        },
    )
    assert resp.status_code == 200
    assert "register/" in resp.text
    created = db.query(User).filter(User.email == "newuser@test.com").first()
    assert created is not None
    assert created.display_name == "New User"
    assert created.system_role == "specialist"


def test_system_invite_user_duplicate_email(seeded_client):
    client, db = seeded_client
    resp = client.post(
        "/admin/system/users/invite",
        data={
            "email": "existing@test.com",
            "display_name": "Dup User",
            "system_role": "internal_user",
            "group_id": "test-group-id",
        },
    )
    assert resp.status_code == 400


def test_system_invite_user_invalid_role(seeded_client):
    client, db = seeded_client
    resp = client.post(
        "/admin/system/users/invite",
        data={
            "email": "hacker@test.com",
            "display_name": "Hacker",
            "system_role": "hacker",
            "group_id": "test-group-id",
        },
    )
    assert resp.status_code == 400


def test_system_deactivate_user(seeded_client):
    client, db = seeded_client
    resp = client.post("/admin/system/users/existing-user-id/deactivate")
    assert resp.status_code == 200
    db.expire_all()
    user = db.get(User, "existing-user-id")
    assert user.is_active is False
