"""POST /claims/{id}/update validates the nickname without a heavy re-render."""

from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import claimos.dependencies as deps
import claimos.models_auth  # noqa: F401
from claimos.models import Base, Claim
from claimos.models_auth import Group, User


@pytest.fixture
def seeded_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    s.add(Group(id="ig", name="Internal", kind="internal"))
    s.add(
        User(
            id="ia", email="ia@t.com", display_name="A", system_role="internal_admin", group_id="ig"
        )
    )
    s.add(Claim(id="c1", owner_group_id="ig", nickname="Smith File"))
    s.add(Claim(id="c2", owner_group_id="ig", nickname="Jones File"))
    s.commit()
    yield s
    s.close()


@pytest.fixture
def client(seeded_db, monkeypatch):
    from claimos.dependencies import CurrentUser, require_active_user
    from claimos.main import app

    async def mock_user():
        return CurrentUser(
            id="ia",
            email="ia@t.com",
            system_role="internal_admin",
            group_id="ig",
            group_kind="internal",
        )

    app.dependency_overrides[require_active_user] = mock_user
    monkeypatch.setattr(deps, "_check_claim_access", lambda *a, **k: True)
    monkeypatch.setattr("claimos.routers.claims.SessionLocal", lambda: seeded_db)
    yield TestClient(app, follow_redirects=False)
    app.dependency_overrides.clear()


def _form(**over):
    data = {"nickname": "Smith File", "policyholder_name": "Smith"}
    data.update(over)
    return data


def test_update_rename_succeeds(client, seeded_db):
    resp = client.post("/claims/c1/update", data=_form(nickname="Smith Residence"))
    assert resp.status_code == 303
    assert "nickname_error" not in resp.headers["location"]
    assert seeded_db.get(Claim, "c1").nickname == "Smith Residence"


def test_update_keeping_same_nickname_succeeds(client, seeded_db):
    resp = client.post("/claims/c1/update", data=_form(nickname="smith file"))
    assert resp.status_code == 303
    assert seeded_db.get(Claim, "c1").nickname == "smith file"


def test_update_to_duplicate_rejected(client, seeded_db):
    resp = client.post("/claims/c1/update", data=_form(nickname="Jones File"))
    assert resp.status_code == 303
    assert "nickname_error" in unquote(resp.headers["location"])
    # Unchanged in DB.
    assert seeded_db.get(Claim, "c1").nickname == "Smith File"
