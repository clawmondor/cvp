"""Tests for Internal Admin panel."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

import cvp.models_auth  # ensure auth tables are registered on Base.metadata  # noqa: F401
from cvp.models import Base, Matter
from cvp.models_auth import Group, User
from cvp.auth import hash_password


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
    from cvp.main import app
    from cvp.db import get_db
    import cvp.dependencies as deps

    ig = Group(id="ig", name="Internal", kind="internal")
    db_session.add(ig)
    db_session.commit()

    def override_get_db():
        yield db_session

    async def mock_internal_admin():
        from cvp.dependencies import CurrentUser
        return CurrentUser(
            id="ia", email="ia@test.com", system_role="internal_admin",
            group_id="ig", group_kind="internal",
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
