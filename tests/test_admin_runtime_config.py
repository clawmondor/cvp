"""Tests for /admin/system/runtime-config admin page."""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import claimos.models_vision  # noqa: F401
from claimos.db import get_db
from claimos.dependencies import CurrentUser, require_system_admin
from claimos.main import app
from claimos.models import Base
from claimos.models_app_setting import AppSetting
from claimos.services import runtime_config


@pytest.fixture(autouse=True)
def clear_cache():
    runtime_config._cache.clear()
    yield
    runtime_config._cache.clear()


@pytest.fixture
def db_session():
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


@pytest.fixture
def admin_client(db_session):
    async def mock_admin():
        return CurrentUser(
            id="admin-1",
            email="admin@test.com",
            system_role="system_admin",
            group_id=None,
            group_kind=None,
        )

    def override_get_db():
        yield db_session

    app.dependency_overrides[require_system_admin] = mock_admin
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_get_renders_form_with_current_values(admin_client):
    resp = admin_client.get("/admin/system/runtime-config")
    assert resp.status_code == 200
    body = resp.text
    assert "evidence_upload_concurrency" in body
    assert "evidence_upload_max_file_mb" in body
    assert "evidence_upload_max_batch_count" in body
    # Defaults from Settings
    assert 'value="4"' in body
    assert 'value="10"' in body
    assert 'value="500"' in body


def test_post_updates_row_and_redirects(admin_client, db_session):
    resp = admin_client.post(
        "/admin/system/runtime-config",
        data={"evidence_upload_concurrency": "8"},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)
    row = db_session.query(AppSetting).filter_by(key="evidence_upload_concurrency").one()
    assert json.loads(row.value_json) == 8


def test_post_rejects_out_of_bounds(admin_client, db_session):
    resp = admin_client.post(
        "/admin/system/runtime-config",
        data={"evidence_upload_concurrency": "999"},
        follow_redirects=False,
    )
    assert resp.status_code == 400
    assert db_session.query(AppSetting).filter_by(key="evidence_upload_concurrency").first() is None
