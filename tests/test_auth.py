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
