"""Tests for System Admin panel."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cvp.models_auth  # ensure auth tables are registered on Base.metadata  # noqa: F401
from cvp.models import Base
from cvp.dependencies import require_system_admin, CurrentUser


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
            id="sa", email="sa@test.com", system_role="system_admin",
            group_id="ig", group_kind="internal",
        )

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[require_system_admin] = mock_admin
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_system_dashboard_accessible(admin_client):
    resp = admin_client.get("/admin/system/")
    assert resp.status_code == 200


def test_system_users_page(admin_client):
    resp = admin_client.get("/admin/system/users")
    assert resp.status_code == 200
