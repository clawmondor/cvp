"""Tests for auth config, JWT, and password utilities."""

from cvp.config import Settings


def test_default_settings_have_auth_fields():
    """Auth settings exist with sensible defaults."""
    s = Settings(
        _env_file=None,
        jwt_secret="a" * 32,
    )
    assert s.environment == "production"
    assert s.jwt_secret == "a" * 32
    assert s.jwt_access_ttl_minutes == 60
    assert s.jwt_refresh_ttl_days == 7
    assert s.auto_login_user_id == ""
    assert s.cookie_secure is True
    assert s.cookie_domain == ""
    assert s.rate_limit_enabled is True


def test_dev_environment_settings():
    """Dev environment can disable cookie_secure and rate limiting."""
    s = Settings(
        _env_file=None,
        jwt_secret="b" * 32,
        environment="dev",
        cookie_secure=False,
        rate_limit_enabled=False,
    )
    assert s.environment == "dev"
    assert s.cookie_secure is False
    assert s.rate_limit_enabled is False


from cvp.models_auth import Group, User, RefreshToken


def test_group_model_fields():
    g = Group(id="g1", name="Test Group", kind="internal")
    assert g.id == "g1"
    assert g.name == "Test Group"
    assert g.kind == "internal"
    assert g.is_active is True


def test_user_model_fields():
    u = User(
        id="u1",
        email="test@example.com",
        display_name="Test User",
        password_hash="hashed",
        system_role="internal_user",
        group_id="g1",
    )
    assert u.id == "u1"
    assert u.email == "test@example.com"
    assert u.system_role == "internal_user"
    assert u.is_active is True
    assert u.mfa_enabled is False
    assert u.mfa_secret is None


def test_refresh_token_model_fields():
    rt = RefreshToken(
        id="rt1",
        user_id="u1",
        token_hash="hash123",
    )
    assert rt.id == "rt1"
    assert rt.user_id == "u1"
    assert rt.revoked_at is None


import time

from cvp.auth import (
    hash_password,
    verify_password,
    create_access_token,
    decode_access_token,
    create_refresh_token_value,
    hash_token,
    is_breached_password,
)


def test_hash_and_verify_password():
    hashed = hash_password("securepassword1")
    assert hashed != "securepassword1"
    assert verify_password("securepassword1", hashed) is True
    assert verify_password("wrongpassword", hashed) is False


def test_create_and_decode_access_token():
    token = create_access_token(
        user_id="u1",
        email="test@example.com",
        system_role="internal_user",
        group_id="g1",
        group_kind="internal",
        secret="testsecret123456789012345678901234",
        ttl_minutes=60,
    )
    payload = decode_access_token(token, secret="testsecret123456789012345678901234")
    assert payload["sub"] == "u1"
    assert payload["email"] == "test@example.com"
    assert payload["system_role"] == "internal_user"
    assert payload["group_id"] == "g1"
    assert payload["group_kind"] == "internal"


def test_decode_expired_token_raises():
    token = create_access_token(
        user_id="u1",
        email="test@example.com",
        system_role="internal_user",
        group_id="g1",
        group_kind="internal",
        secret="testsecret123456789012345678901234",
        ttl_minutes=-1,  # already expired
    )
    payload = decode_access_token(token, secret="testsecret123456789012345678901234")
    assert payload is None


def test_decode_invalid_token_returns_none():
    payload = decode_access_token("garbage.token.value", secret="testsecret123456789012345678901234")
    assert payload is None


def test_create_refresh_token_value():
    token = create_refresh_token_value()
    assert len(token) > 20  # url-safe token should be substantial


def test_hash_token():
    token = "my-refresh-token"
    h = hash_token(token)
    assert h != token
    assert hash_token(token) == h  # deterministic


def test_is_breached_password():
    # "password" should be in the top 100k list
    assert is_breached_password("password") is True
    # A random long string should not be
    assert is_breached_password("xK9$mP2vQ7wL4nR8jF5tY3hB6cD0aE1g") is False
