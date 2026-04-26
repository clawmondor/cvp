"""Integration tests for auth routes."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from cvp.auth import hash_password
from cvp.models import Base
from cvp.models_auth import Group, User


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def seeded_db(db_session):
    """Seed a test DB with a group and user."""
    group = Group(id="g1", name="Test Internal", kind="internal")
    db_session.add(group)
    user = User(
        id="u1",
        email="admin@test.com",
        display_name="Admin",
        password_hash=hash_password("correcthorse12"),
        system_role="system_admin",
        group_id="g1",
    )
    db_session.add(user)
    db_session.commit()
    return db_session


@pytest.fixture
def client(seeded_db):
    from cvp.main import app
    from cvp.db import get_db

    def override_get_db():
        try:
            yield seeded_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_splash_page(client):
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 200
    assert "Sign In" in resp.text


def test_login_page(client):
    resp = client.get("/login")
    assert resp.status_code == 200
    assert "email" in resp.text.lower()


def test_login_success(client):
    resp = client.post(
        "/api/auth/login",
        data={"email": "admin@test.com", "password": "correcthorse12"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "cvp_access" in resp.cookies
    assert "cvp_refresh" in resp.cookies
    assert "cvp_csrf" in resp.cookies


def test_login_wrong_password(client):
    resp = client.post(
        "/api/auth/login",
        data={"email": "admin@test.com", "password": "wrongpassword1"},
    )
    assert resp.status_code == 401


def test_login_nonexistent_user(client):
    resp = client.post(
        "/api/auth/login",
        data={"email": "nobody@test.com", "password": "doesntmatter1"},
    )
    assert resp.status_code == 401
