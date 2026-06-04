"""Integration tests for the admin feedback router."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cvp.models_auth  # noqa: F401
import cvp.models_feedback  # noqa: F401
from cvp.dependencies import CurrentUser, require_active_user, require_system_admin
from cvp.models import Base
from cvp.models_auth import Group, User
from cvp.models_feedback import Feedback


def _session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


@pytest.fixture
def admin_client():
    from cvp.db import get_db
    from cvp.main import app

    db = _session()
    g = Group(id="g1", name="Internal", kind="internal")
    admin = User(
        id="admin",
        email="a@test.com",
        display_name="Admin",
        system_role="system_admin",
        group_id="g1",
        is_active=True,
    )
    u = User(
        id="u1",
        email="u@test.com",
        display_name="User",
        system_role="internal_user",
        group_id="g1",
        is_active=True,
    )
    db.add_all([g, admin, u])
    db.commit()

    admin_cu = CurrentUser(
        id="admin",
        email="a@test.com",
        system_role="system_admin",
        group_id="g1",
        group_kind="internal",
    )

    async def fake_active():
        return admin_cu

    async def fake_admin():
        return admin_cu

    def override_db():
        yield db

    app.dependency_overrides[require_active_user] = fake_active
    app.dependency_overrides[require_system_admin] = fake_admin
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as c:
        yield c, db
    app.dependency_overrides.clear()


@pytest.fixture
def nonadmin_client():
    from cvp.db import get_db
    from cvp.main import app

    db = _session()
    g = Group(id="g1", name="Internal", kind="internal")
    u = User(
        id="u1",
        email="u@test.com",
        display_name="User",
        system_role="internal_admin",  # internal_admin is not system_admin
        group_id="g1",
        is_active=True,
    )
    db.add_all([g, u])
    db.commit()

    cu = CurrentUser(
        id="u1",
        email="u@test.com",
        system_role="internal_admin",
        group_id="g1",
        group_kind="internal",
    )

    async def fake_active():
        return cu

    def override_db():
        yield db

    app.dependency_overrides[require_active_user] = fake_active
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as c:
        yield c, db
    app.dependency_overrides.clear()


def test_admin_list_renders(admin_client):
    client, db = admin_client
    db.add(
        Feedback(
            id="f1",
            author_user_id="u1",
            author_group_id="g1",
            page_url="/x",
            body="hello-from-user",
        )
    )
    db.commit()
    resp = client.get("/admin/system/feedback")
    assert resp.status_code == 200
    assert "hello-from-user" in resp.text


def test_admin_list_filters_by_status(admin_client):
    client, db = admin_client
    db.add(
        Feedback(
            id="f1",
            author_user_id="u1",
            author_group_id="g1",
            page_url="/x",
            body="pending-one",
            status="pending",
        )
    )
    db.add(
        Feedback(
            id="f2",
            author_user_id="u1",
            author_group_id="g1",
            page_url="/x",
            body="done-one",
            status="done",
        )
    )
    db.commit()
    resp = client.get("/admin/system/feedback?status=pending")
    assert "pending-one" in resp.text
    assert "done-one" not in resp.text


def test_internal_admin_gets_403(nonadmin_client):
    client, _db = nonadmin_client
    resp = client.get("/admin/system/feedback")
    assert resp.status_code == 403
