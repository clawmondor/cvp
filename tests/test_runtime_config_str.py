import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from cvp.models import Base
from cvp.models_app_setting import AppSetting
from cvp.services import runtime_config


@pytest.fixture(autouse=True)
def clear_cache():
    runtime_config._cache.clear()
    yield
    runtime_config._cache.clear()


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def test_get_str_returns_env_default_when_unset(db_session):
    assert runtime_config.get_str(db_session, "ai_recommendation_min_confidence") == "high"


def test_get_str_returns_db_override(db_session):
    runtime_config.set_value(
        db_session, "ai_recommendation_min_confidence", "medium", updated_by_user_id=None
    )
    assert runtime_config.get_str(db_session, "ai_recommendation_min_confidence") == "medium"


def test_get_str_ignores_out_of_set_value(db_session):
    # Seed the invalid value directly, bypassing set_value's write-time guard,
    # to cover the read-side fallback (e.g. legacy/manually-edited DB rows).
    db_session.add(
        AppSetting(key="ai_recommendation_min_confidence", value_json=json.dumps("bogus"))
    )
    db_session.commit()
    assert runtime_config.get_str(db_session, "ai_recommendation_min_confidence") == "high"


def test_set_value_rejects_out_of_set_value(db_session):
    with pytest.raises(ValueError):
        runtime_config.set_value(
            db_session, "ai_recommendation_min_confidence", "bogus", updated_by_user_id=None
        )
