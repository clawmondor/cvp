import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from cvp.models import Base
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
