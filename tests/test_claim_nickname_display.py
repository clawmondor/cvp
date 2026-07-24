"""The dashboard lists claims by nickname (primary), policyholder secondary."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
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
    s.add(
        Claim(
            id="c1", owner_group_id="ig", nickname="Smith Residence", policyholder_name="Jane Smith"
        )
    )
    s.commit()
    yield s
    s.close()


@pytest.fixture
def client(seeded_db):
    from claimos.db import get_db
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

    def override_db():
        yield seeded_db

    # The /dashboard route (main.py) reads claims via the get_db dependency.
    app.dependency_overrides[require_active_user] = mock_user
    app.dependency_overrides[get_db] = override_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_dashboard_shows_nickname_as_link(client):
    html = client.get("/dashboard").text
    # Nickname appears as the clickable label; policyholder as secondary text.
    link_idx = html.find("Smith Residence")
    ph_idx = html.find("Jane Smith")
    assert link_idx != -1 and ph_idx != -1
    assert link_idx < ph_idx  # nickname rendered before policyholder in the row
