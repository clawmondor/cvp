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


def test_claims_list_shows_own_firm_claims_only(client, db_session):
    db_session.add_all(
        [
            Claim(id="cA", owner_group_id="eg", nickname="Claim A", policyholder_name="Rossi"),
            Claim(id="cX", owner_group_id="og", nickname="Claim X", policyholder_name="Other"),
        ]
    )
    db_session.commit()
    resp = client.get("/team")
    assert resp.status_code == 200
    assert "Claim A" in resp.text
    assert "Claim X" not in resp.text


def test_claim_access_view_shows_resolved_roles(client, db_session):
    from claimos.models import Claim
    from claimos.models_auth import User
    from claimos.services.grants import create_grant

    db_session.add(
        Claim(id="cA", owner_group_id="eg", nickname="Claim A", policyholder_name="Rossi")
    )
    db_session.add(
        User(
            id="ph",
            email="ph@acme.com",
            display_name="Photog",
            system_role="external_user",
            group_id="eg",
        )
    )
    db_session.commit()
    create_grant(
        db_session,
        user_id="ph",
        user_role="photographer",
        scope="group",
        claim_ids=[],
        overrides={},
        granted_by_id="ea",
    )
    resp = client.get("/team/claims/cA/access")
    assert resp.status_code == 200
    assert "ph@acme.com" in resp.text
    assert "contributor" in resp.text  # photographer → contributor on evidence


def test_claim_access_cross_group_is_404(client, db_session):
    from claimos.models import Claim

    db_session.add(
        Claim(id="cX", owner_group_id="og", nickname="Claim X", policyholder_name="Other")
    )
    db_session.commit()
    assert client.get("/team/claims/cX/access").status_code == 404


def test_grant_claim_access_creates_claim_scoped_grant(client, db_session):
    from claimos.models import Claim
    from claimos.models_auth import User

    db_session.add(
        Claim(id="cA", owner_group_id="eg", nickname="Claim A", policyholder_name="Rossi")
    )
    db_session.add(
        User(
            id="val",
            email="val@acme.com",
            display_name="Val",
            system_role="external_user",
            group_id="eg",
        )
    )
    db_session.commit()
    r = client.post(
        "/team/claims/cA/grant",
        data={"user_id": "val", "user_role": "valuator"},
        follow_redirects=False,
    )
    assert r.status_code in (302, 303)
    from claimos.services.grants import list_grants

    g = list_grants(db_session, "val")[0]
    assert g.scope == "claims" and [c.claim_id for c in g.claims] == ["cA"]


def test_grant_claim_access_rejects_cross_group_member(client, db_session):
    from claimos.models import Claim

    db_session.add(
        Claim(id="cA", owner_group_id="eg", nickname="Claim A", policyholder_name="Rossi")
    )
    db_session.commit()
    r = client.post(
        "/team/claims/cA/grant",
        data={"user_id": "out", "user_role": "valuator"},
        follow_redirects=False,
    )
    assert r.status_code == 404
