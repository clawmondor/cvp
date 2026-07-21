import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import claimos.models_auth  # noqa: F401
import claimos.models_grants  # noqa: F401
from claimos.dependencies import CurrentUser, require_active_user
from claimos.models import Base
from claimos.models_auth import Group, User


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    s.add_all(
        [
            Group(id="eg", name="Firm", kind="external"),
            User(
                id="ea",
                email="ea@f.com",
                display_name="EA",
                system_role="external_admin",
                group_id="eg",
            ),
        ]
    )
    s.commit()
    from claimos.db import get_db
    from claimos.main import app

    def override_db():
        yield s

    async def mock_ea():
        return CurrentUser(
            id="ea",
            email="ea@f.com",
            system_role="external_admin",
            group_id="eg",
            group_kind="external",
        )

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_active_user] = mock_ea
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()
    s.close()


def test_external_admin_redirected_off_admin_org(client):
    r = client.get("/admin/org/", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/team"


def test_profile_carveout_not_redirected(client):
    r = client.get("/admin/org/profile", follow_redirects=False)
    assert r.status_code != 302  # profile stays reachable (200 or its own handling)
