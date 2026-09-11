import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from cvp.models import Base
from cvp.services import runtime_config
from cvp.services.agent_models import (
    ALLOWED_MODEL_SLUGS,
    DEFAULT_MODEL_SLUG,
    is_allowed,
    resolve_model,
)


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def test_default_is_allowed():
    assert DEFAULT_MODEL_SLUG in ALLOWED_MODEL_SLUGS


def test_is_allowed_rejects_unknown():
    assert is_allowed("anthropic/claude-haiku-4.5") is True
    assert is_allowed("some/expensive-model") is False
    assert is_allowed("") is False


def test_resolve_model_uses_default_when_not_requested(db_session):
    assert resolve_model(db_session, None) == DEFAULT_MODEL_SLUG


def test_resolve_model_accepts_allowed_override(db_session):
    assert resolve_model(db_session, "anthropic/claude-sonnet-4.6") == "anthropic/claude-sonnet-4.6"


def test_resolve_model_rejects_disallowed_override(db_session):
    with pytest.raises(ValueError, match="not allowed"):
        resolve_model(db_session, "some/expensive-model")


def test_resolve_model_rejects_a_disallowed_configured_default(db_session, monkeypatch, caplog):
    """The env default bypassed the allowlist entirely: runtime_config only
    validates a DB row, so `AI_RECOMMENDATION_MODEL=openai/o3-pro` reached the
    Worker — which validates nothing — and spent against a capped key."""
    monkeypatch.setattr(
        runtime_config.settings, "ai_recommendation_model", "openai/o3-pro", raising=False
    )
    # The read-through cache is module-global and TTL'd; clear it either side
    # so this test neither reads nor leaves a stale value.
    runtime_config._cache.pop("ai_recommendation_model", None)
    try:
        with caplog.at_level("WARNING"):
            assert resolve_model(db_session, None) == DEFAULT_MODEL_SLUG
        assert "openai/o3-pro" in caplog.text
    finally:
        runtime_config._cache.pop("ai_recommendation_model", None)
