"""Tests for External Admin (Org) panel."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import claimos.models_auth  # noqa: F401 — register models with Base
from claimos.models import Base
from claimos.models_auth import Group


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
    from claimos.main import app
    from claimos.routers.admin.org import _require_org_admin_or_above

    eg = Group(id="eg", name="Acme Law", kind="external")
    db_session.add(eg)
    db_session.commit()

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


def test_org_dashboard_accessible(org_client):
    resp = org_client.get("/admin/org/")
    assert resp.status_code == 200


def test_org_users_page(org_client):
    resp = org_client.get("/admin/org/users")
    assert resp.status_code == 200
