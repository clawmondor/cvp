"""Tests for Internal Admin panel."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cvp.models_auth  # ensure auth tables are registered on Base.metadata  # noqa: F401
from cvp.models import Base
from cvp.models_auth import Group


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
def internal_client(db_session):
    from cvp.db import get_db
    from cvp.main import app

    ig = Group(id="ig", name="Internal", kind="internal")
    db_session.add(ig)
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
        yield c
    app.dependency_overrides.clear()


def test_internal_dashboard_accessible(internal_client):
    resp = internal_client.get("/admin/internal/")
    assert resp.status_code == 200


def test_internal_users_page(internal_client):
    resp = internal_client.get("/admin/internal/users")
    assert resp.status_code == 200


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
    from datetime import datetime, timedelta, timezone

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
    now = datetime.now(tz=timezone.utc)
    expires = user.invite_expires_at.replace(tzinfo=timezone.utc)
    assert now + timedelta(days=6, hours=23) < expires < now + timedelta(days=7, hours=1)
    assert user.password_changed_at is None


def test_internal_regenerate_invite_unknown_user_returns_404(seeded_internal_client):
    client, _ = seeded_internal_client
    resp = client.post("/admin/internal/users/does-not-exist/regenerate-invite")
    assert resp.status_code == 404


def test_internal_regenerate_invite_outside_group_returns_404(seeded_internal_client):
    client, _ = seeded_internal_client
    resp = client.post("/admin/internal/users/outsider-id/regenerate-invite")
    assert resp.status_code == 404
