import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import claimos.models_auth  # noqa: F401
import claimos.models_grants  # noqa: F401
from claimos.dependencies import CurrentUser
from claimos.models import Base, Claim
from claimos.models_auth import Group, User


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    s.add_all(
        [
            Group(id="eg", name="Acme Law", kind="external"),
            Group(id="og", name="Other Firm", kind="external"),
            User(
                id="ea",
                email="ea@acme.com",
                display_name="Ext Admin",
                system_role="external_admin",
                group_id="eg",
            ),
            User(
                id="m1",
                email="m1@acme.com",
                display_name="Member One",
                system_role="external_user",
                group_id="eg",
            ),
            User(
                id="out",
                email="out@other.com",
                display_name="Outsider",
                system_role="external_user",
                group_id="og",
            ),
            Claim(id="cA", owner_group_id="eg", policyholder_name="Rossi", nickname="Rossi Claim"),
            Claim(id="cX", owner_group_id="og", policyholder_name="Other", nickname="Other Claim"),
        ]
    )
    s.commit()
    yield s
    s.close()


@pytest.fixture
def client(db_session):
    from claimos.db import get_db
    from claimos.main import app
    from claimos.routers.team import require_external_admin

    def override_db():
        yield db_session

    async def mock_user():
        return CurrentUser(
            id="ea",
            email="ea@acme.com",
            system_role="external_admin",
            group_id="eg",
            group_kind="external",
        )

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_external_admin] = mock_user
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_team_index_shows_both_sections_scoped_to_firm(client):
    resp = client.get("/team")
    assert resp.status_code == 200
    # Members section (own firm only)
    assert "m1@acme.com" in resp.text
    assert "out@other.com" not in resp.text
    # Claim Access section (own firm only)
    assert "Rossi" in resp.text
    assert "Other" not in resp.text
    # Section headings present, Members before Claim Access
    assert resp.text.index("Members") < resp.text.index("Claim Access")


def test_old_list_routes_redirect_to_team(client):
    r1 = client.get("/team/users", follow_redirects=False)
    assert r1.status_code in (302, 307) and r1.headers["location"] == "/team"
    r2 = client.get("/team/claims", follow_redirects=False)
    assert r2.status_code in (302, 307) and r2.headers["location"] == "/team"
