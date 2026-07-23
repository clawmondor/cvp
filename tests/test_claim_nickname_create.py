"""POST /claims enforces a required, group-unique nickname."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

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
    monkeypatch.setattr("claimos.routers.claims.SessionLocal", lambda: seeded_db)
    yield TestClient(app, follow_redirects=False)
    app.dependency_overrides.clear()


def test_create_with_nickname_succeeds(client, seeded_db):
    resp = client.post("/claims", data={"nickname": "Jones File", "policyholder_name": "Jones"})
    assert resp.status_code == 303  # redirect to the new claim
    row = seeded_db.query(Claim).filter(func.lower(Claim.nickname) == "jones file").one()
    assert row.owner_group_id == "ig"


def test_create_without_nickname_rejected(client, seeded_db):
    resp = client.post("/claims", data={"nickname": "   ", "policyholder_name": "X"})
    assert resp.status_code == 200  # re-rendered form, not a redirect
    assert "Nickname is required." in resp.text
    assert seeded_db.query(Claim).count() == 0


def test_create_duplicate_nickname_rejected(client, seeded_db):
    seeded_db.add(Claim(id="c1", owner_group_id="ig", nickname="Smith File"))
    seeded_db.commit()
    resp = client.post("/claims", data={"nickname": "smith file"})
    assert resp.status_code == 200
    assert "already used in your group" in resp.text
    assert seeded_db.query(Claim).count() == 1  # no second row created
