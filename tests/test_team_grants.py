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
            Claim(id="cA", owner_group_id="eg", claim_number="cA", nickname="Claim A"),
            Claim(id="cB", owner_group_id="eg", claim_number="cB", nickname="Claim B"),
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


def test_assign_group_scoped_role(client, db_session):
    r = client.post(
        "/team/users/m1/grants",
        data={"user_role": "photographer", "scope": "group"},
        follow_redirects=False,
    )
    assert r.status_code in (302, 303)
    from claimos.services.grants import list_grants

    grants = list_grants(db_session, "m1")
    assert len(grants) == 1 and grants[0].user_role == "photographer"


def test_assign_cross_group_member_is_404(client):
    r = client.post(
        "/team/users/out/grants",
        data={"user_role": "photographer", "scope": "group"},
        follow_redirects=False,
    )
    assert r.status_code == 404


def test_claimant_requires_single_claim_returns_400(client):
    r = client.post(
        "/team/users/m1/grants",
        data={"user_role": "claimant", "scope": "group"},
        follow_redirects=False,
    )
    assert r.status_code == 400


def test_revoke_grant(client, db_session):
    from claimos.services.grants import create_grant, list_grants

    g = create_grant(
        db_session,
        user_id="m1",
        user_role="valuator",
        scope="group",
        claim_ids=[],
        overrides={},
        granted_by_id="ea",
    )
    r = client.post(f"/team/grants/{g.id}/revoke", follow_redirects=False)
    assert r.status_code in (302, 303)
    assert list_grants(db_session, "m1") == []


def test_revoke_cross_group_grant_is_403(client, db_session):
    from claimos.services.grants import create_grant

    g = create_grant(
        db_session,
        user_id="out",
        user_role="valuator",
        scope="group",
        claim_ids=[],
        overrides={},
        granted_by_id="out",
    )
    r = client.post(f"/team/grants/{g.id}/revoke", follow_redirects=False)
    assert r.status_code == 403


def test_add_and_remove_override_via_endpoint(client, db_session):
    from claimos.services.grants import create_grant

    g = create_grant(
        db_session,
        user_id="m1",
        user_role="photographer",
        scope="group",
        claim_ids=[],
        overrides={},
        granted_by_id="ea",
    )
    r = client.post(
        f"/team/grants/{g.id}/overrides",
        data={"object_type": "items", "role": "contributor"},
        follow_redirects=False,
    )
    assert r.status_code in (302, 303)
    from claimos.services.effective_permissions import group_effective_matrix

    assert group_effective_matrix(db_session, "m1", "eg")["items"] == "contributor"

    r2 = client.post(f"/team/grants/{g.id}/overrides/items/remove", follow_redirects=False)
    assert r2.status_code in (302, 303)
    assert group_effective_matrix(db_session, "m1", "eg")["items"] == "viewer"


def test_override_on_cross_group_grant_is_403(client, db_session):
    from claimos.services.grants import create_grant

    g = create_grant(
        db_session,
        user_id="out",
        user_role="photographer",
        scope="group",
        claim_ids=[],
        overrides={},
        granted_by_id="out",
    )
    r = client.post(
        f"/team/grants/{g.id}/overrides",
        data={"object_type": "items", "role": "contributor"},
        follow_redirects=False,
    )
    assert r.status_code == 403
