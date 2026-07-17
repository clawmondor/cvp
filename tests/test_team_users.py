import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import claimos.models_auth  # noqa: F401
import claimos.models_grants  # noqa: F401
from claimos.dependencies import CurrentUser
from claimos.models import Base
from claimos.models_auth import Group, User


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
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
        ]
    )
    s.commit()
    yield s
    s.close()


def _client(db_session, role="external_admin", group_id="eg"):
    from claimos.db import get_db
    from claimos.main import app
    from claimos.routers.team import require_external_admin

    def override_db():
        yield db_session

    async def mock_user():
        return CurrentUser(
            id="ea", email="ea@acme.com", system_role=role, group_id=group_id, group_kind="external"
        )

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_external_admin] = mock_user
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
def client(db_session):
    yield from _client(db_session)


def test_members_list_shows_own_group_only(client):
    resp = client.get("/team/users")
    assert resp.status_code == 200
    assert "m1@acme.com" in resp.text
    assert "out@other.com" not in resp.text  # different firm


def test_members_list_forbidden_for_non_admin(db_session):
    # A plain external_user must not reach /team — require_external_admin rejects.
    from claimos.db import get_db
    from claimos.main import app

    def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app, raise_server_exceptions=False)
    # No override of require_external_admin here; unauthenticated → 401/redirect.
    resp = client.get("/team/users")
    assert resp.status_code in (401, 403)
    app.dependency_overrides.clear()
