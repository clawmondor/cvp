"""HTTP tests for the custom export template CRUD router + custom export endpoint."""

import json
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cvp.dependencies as deps
import cvp.models_access  # noqa: F401 — register matter_access table
import cvp.models_auth  # noqa: F401 — register auth tables
from cvp.auth import hash_password
from cvp.models import Base, Category, ExportTemplate, ExportTemplateColumn, Matter
from cvp.models_auth import Group, User


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
    ig = Group(id="ig", name="Internal", kind="internal")
    db_session.add(ig)
    admin = User(
        id="ia",
        email="ia@test.com",
        display_name="Admin",
        password_hash=hash_password("x"),
        system_role="internal_admin",
        group_id="ig",
    )
    db_session.add(admin)
    db_session.add(Category(id=1, name="Misc", useful_life_years=10, acv_floor_pct=0.2))
    matter = Matter(id="m1", owner_group_id="ig", created_by_id="ia")
    db_session.add(matter)
    db_session.commit()
    return db_session


@pytest.fixture
def make_client(seeded_db, monkeypatch):
    """Factory: returns ``(client, matter_id)`` for the given role on matter 'm1'."""
    from cvp.db import get_db
    from cvp.dependencies import CurrentUser, require_active_user
    from cvp.main import app

    def override_get_db():
        try:
            yield seeded_db
        finally:
            pass

    async def mock_user():
        return CurrentUser(
            id="ia",
            email="ia@test.com",
            system_role="internal_admin",
            group_id="ig",
            group_kind="internal",
        )

    levels = {"viewer": 0, "contributor": 1, "editor": 2, "manager": 3}

    def _make(role: str = "manager"):
        def fake_check(db, user, matter_id, required):
            return levels[role] >= levels[required]

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[require_active_user] = mock_user
        monkeypatch.setattr(deps, "_check_matter_access", fake_check)
        monkeypatch.setattr("cvp.routers.export_templates.SessionLocal", lambda: seeded_db)
        monkeypatch.setattr("cvp.services.csv_export.SessionLocal", lambda: seeded_db)
        return TestClient(app), "m1"

    yield _make
    app.dependency_overrides.clear()


def _payload(**over):
    cols = over.pop(
        "columns",
        [{"field_key": "description", "header_label": None, "static_value": None}],
    )
    data = {
        "name": "Packet",
        "description": "",
        "sort_field": "line_number",
        "columns_json": json.dumps(cols),
    }
    data.update(over)
    return data


def test_create_lists_and_delete(seeded_db, make_client):
    client, matter_id = make_client()
    r = client.post(f"/api/matters/{matter_id}/export-templates", data=_payload())
    assert r.status_code in (200, 201)

    page = client.get(f"/matters/{matter_id}/export-templates")
    assert page.status_code == 200
    assert "Packet" in page.text

    tid = re.search(r'data-template-id="([^"]+)"', page.text).group(1)

    r = client.request("DELETE", f"/api/matters/{matter_id}/export-templates/{tid}")
    assert r.status_code == 200

    page = client.get(f"/matters/{matter_id}/export-templates")
    assert "Packet" not in page.text


def test_cross_group_template_404(seeded_db, make_client):
    client, matter_id = make_client()
    other = ExportTemplate(id="tX", group_id="other-group", name="Nope", sort_field="line_number")
    other.columns = [ExportTemplateColumn(position=0, field_key="description")]
    seeded_db.add(other)
    seeded_db.commit()

    r = client.request("DELETE", f"/api/matters/{matter_id}/export-templates/tX")
    assert r.status_code == 404


def test_cross_group_put_404(seeded_db, make_client):
    client, matter_id = make_client()
    other = ExportTemplate(id="tY", group_id="other-group", name="Nope", sort_field="line_number")
    other.columns = [ExportTemplateColumn(position=0, field_key="description")]
    seeded_db.add(other)
    seeded_db.commit()

    r = client.put(f"/api/matters/{matter_id}/export-templates/tY", data=_payload())
    assert r.status_code == 404


def test_invalid_payload_400(seeded_db, make_client):
    client, matter_id = make_client()
    r = client.post(
        f"/api/matters/{matter_id}/export-templates",
        data=_payload(columns=[]),
    )
    assert r.status_code == 400


def test_malformed_columns_json_returns_400(seeded_db, make_client):
    client, matter_id = make_client()
    r = client.post(
        f"/api/matters/{matter_id}/export-templates",
        data=_payload(columns_json=json.dumps(["a", "b"])),
    )
    assert r.status_code == 400


def test_custom_export_runs(seeded_db, make_client, tmp_path, monkeypatch):
    from cvp.services import csv_export

    monkeypatch.setattr(csv_export.settings, "export_dir", str(tmp_path))
    client, matter_id = make_client()

    client.post(f"/api/matters/{matter_id}/export-templates", data=_payload())
    page = client.get(f"/matters/{matter_id}/export-templates")
    tid = re.search(r'data-template-id="([^"]+)"', page.text).group(1)

    r = client.post(f"/api/matters/{matter_id}/exports/custom", data={"template_id": tid})
    assert r.status_code == 200
    assert "generated successfully" in r.text


def test_builder_page_has_catalog_and_form(seeded_db, make_client):
    client, matter_id = make_client()
    r = client.get(f"/matters/{matter_id}/export-templates")
    assert r.status_code == 200
    assert 'data-action="add-col"' in r.text
    assert 'id="columns-json"' in r.text
    assert 'id="col-row-template"' in r.text
    assert 'data-action="load-xactimate"' in r.text


def test_mutation_returns_fragment_not_full_page(seeded_db, make_client):
    client, matter_id = make_client()
    r = client.post(f"/api/matters/{matter_id}/export-templates", data=_payload())
    assert r.status_code in (200, 201)
    assert 'id="builder-root"' in r.text
    lowered = r.text.lower()
    assert "<!doctype" not in lowered
    assert "<html" not in lowered
