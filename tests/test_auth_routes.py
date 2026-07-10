"""Integration tests for auth routes."""

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import claimos.models_auth  # ensure auth tables are registered on Base.metadata  # noqa: F401
from claimos.auth import hash_password
from claimos.config import settings
from claimos.models import Base
from claimos.models_auth import Group, User


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
    from unittest.mock import patch

    from claimos.db import get_db
    from claimos.main import app

    def override_get_db():
        try:
            yield seeded_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    # CI defaults to cookie_secure=True (production). The TestClient talks to
    # http://testserver, so a Secure auth cookie would be dropped on the return
    # trip and any test that round-trips a login cookie would fail. Force it off
    # so cookie-auth paths are exercised deterministically regardless of env.
    with patch.object(settings, "cookie_secure", False):
        with TestClient(app) as c:
            yield c
    app.dependency_overrides.clear()


def test_splash_page(client, monkeypatch):
    from claimos.config import settings

    monkeypatch.setattr(settings, "auto_login_user_id", "")
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 200
    assert "Sign In" in resp.text


def test_root_authenticated_shows_dashboard(client, monkeypatch):
    # Force the cookie path (not dev auto-login) so the test is deterministic.
    monkeypatch.setattr(settings, "auto_login_user_id", "")
    login = client.post(
        "/api/auth/login",
        data={"email": "admin@test.com", "password": "correcthorse12"},
        follow_redirects=False,
    )
    assert login.status_code == 303  # cookie now stored on the TestClient
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Dashboard" in resp.text
    assert "coming soon" in resp.text


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


# ---------------------------------------------------------------------------
# MFA verify endpoint tests
# ---------------------------------------------------------------------------

# Stable test credentials reused across all MFA tests
_TEST_JWT_SECRET = "test-mfa-jwt-secret-key-must-be-long-enough-32b"
_TEST_FERNET_KEY = "zPTtO26OeIAGeNbiniA1oEiLacqPXkyeDNK-6WnivI8="
_TEST_TOTP_SECRET = "JBSWY3DPEHPK3PXP"


@pytest.fixture
def mfa_client(db_session):
    """Client with a user that has MFA enabled. Patches jwt_secret and mfa_encryption_key."""
    from unittest.mock import patch

    from claimos.db import get_db
    from claimos.main import app
    from claimos.services.mfa import encrypt_secret

    group = Group(id="g2", name="MFA Group", kind="internal")
    db_session.add(group)

    encrypted = encrypt_secret(_TEST_TOTP_SECRET, _TEST_FERNET_KEY)

    mfa_user = User(
        id="u2",
        email="mfa@test.com",
        display_name="MFA User",
        password_hash=hash_password("correcthorse12"),
        system_role="specialist",
        group_id="g2",
        mfa_enabled=True,
        mfa_secret=encrypted,
    )
    db_session.add(mfa_user)
    db_session.commit()

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with (
        patch.object(settings, "jwt_secret", _TEST_JWT_SECRET),
        patch.object(settings, "mfa_encryption_key", _TEST_FERNET_KEY),
    ):
        with TestClient(app) as c:
            yield c
    app.dependency_overrides.clear()


def _make_mfa_token(user_id: str) -> str:
    """Build a valid short-lived MFA verification JWT signed with the test secret."""
    exp = datetime.now(tz=timezone.utc) + timedelta(minutes=5)
    return jwt.encode(
        {"sub": user_id, "purpose": "mfa_verification", "exp": exp},
        _TEST_JWT_SECRET,
        algorithm="HS256",
    )


def test_mfa_verify_invalid_token(client):
    """POST /api/auth/mfa/verify with a garbage mfa_token returns 401 and login page."""
    resp = client.post(
        "/api/auth/mfa/verify",
        data={"mfa_token": "not-a-valid-jwt", "code": "123456", "next": ""},
    )
    assert resp.status_code == 401
    assert "mfa session expired" in resp.text.lower() or "sign in" in resp.text.lower()


def test_mfa_verify_wrong_code(mfa_client):
    """POST /api/auth/mfa/verify with valid token but wrong TOTP code → 401 + MFA form."""
    mfa_token = _make_mfa_token("u2")
    resp = mfa_client.post(
        "/api/auth/mfa/verify",
        data={"mfa_token": mfa_token, "code": "000000", "next": ""},
    )
    assert resp.status_code == 401
    assert "invalid code" in resp.text.lower()


def test_mfa_verify_open_redirect_blocked(mfa_client):
    """POST /api/auth/mfa/verify with absolute next URL redirects to /dashboard instead."""
    import pyotp

    valid_code = pyotp.TOTP(_TEST_TOTP_SECRET).now()
    mfa_token = _make_mfa_token("u2")
    resp = mfa_client.post(
        "/api/auth/mfa/verify",
        data={"mfa_token": mfa_token, "code": valid_code, "next": "https://evil.com"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/dashboard"
