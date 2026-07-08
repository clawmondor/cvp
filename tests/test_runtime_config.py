"""Tests for AppSetting model and runtime_config service."""

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from claimos.models import Base
from claimos.models_app_setting import AppSetting
from claimos.services import runtime_config


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


@pytest.fixture(autouse=True)
def clear_cache():
    runtime_config._cache.clear()
    yield
    runtime_config._cache.clear()


def test_app_setting_model_columns():
    cols = {c.name for c in AppSetting.__table__.columns}
    assert cols == {"key", "value_json", "updated_at", "updated_by_user_id"}


def test_get_int_returns_env_default_when_no_db_row(db):
    assert runtime_config.get_int(db, "evidence_upload_concurrency") == 4


def test_get_int_returns_db_override_when_row_exists(db):
    db.add(AppSetting(key="evidence_upload_concurrency", value_json=json.dumps(7)))
    db.commit()
    assert runtime_config.get_int(db, "evidence_upload_concurrency") == 7


def test_get_int_rejects_out_of_bounds_value_and_returns_default(db):
    db.add(AppSetting(key="evidence_upload_concurrency", value_json=json.dumps(999)))
    db.commit()
    # 999 exceeds the documented 1..16 bound; service falls back to env default
    assert runtime_config.get_int(db, "evidence_upload_concurrency") == 4


def test_cache_returns_stale_value_within_ttl(db, monkeypatch):
    db.add(AppSetting(key="evidence_upload_concurrency", value_json=json.dumps(7)))
    db.commit()
    assert runtime_config.get_int(db, "evidence_upload_concurrency") == 7

    # Update DB but stay within TTL — cached value (7) should still be returned
    db.query(AppSetting).filter_by(key="evidence_upload_concurrency").update(
        {"value_json": json.dumps(12)}
    )
    db.commit()
    assert runtime_config.get_int(db, "evidence_upload_concurrency") == 7


def test_cache_refreshes_after_ttl_expires(db, monkeypatch):
    db.add(AppSetting(key="evidence_upload_concurrency", value_json=json.dumps(7)))
    db.commit()
    assert runtime_config.get_int(db, "evidence_upload_concurrency") == 7

    # Fast-forward past TTL
    monkeypatch.setattr(
        runtime_config,
        "_now",
        lambda: (
            runtime_config._cache["evidence_upload_concurrency"][0]
            + runtime_config._TTL_SECONDS
            + 1
        ),
    )
    db.query(AppSetting).filter_by(key="evidence_upload_concurrency").update(
        {"value_json": json.dumps(12)}
    )
    db.commit()
    assert runtime_config.get_int(db, "evidence_upload_concurrency") == 12


def test_set_value_writes_row_and_invalidates_cache(db):
    runtime_config.set_value(db, "evidence_upload_concurrency", 9, updated_by_user_id="u1")
    row = db.query(AppSetting).filter_by(key="evidence_upload_concurrency").one()
    assert json.loads(row.value_json) == 9
    assert row.updated_by_user_id == "u1"
    # Cache invalidated, so a fresh read returns the new value immediately
    assert runtime_config.get_int(db, "evidence_upload_concurrency") == 9
