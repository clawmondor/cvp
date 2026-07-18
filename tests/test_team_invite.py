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
            Claim(id="cA", owner_group_id="eg", claim_number="cA"),
            Claim(id="cB", owner_group_id="og", claim_number="cB"),
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


def test_invite_form_renders(client):
    resp = client.get("/team/users/invite")
    assert resp.status_code == 200
    assert "invite" in resp.text.lower()


def test_invite_sets_system_role_and_creates_grant(client, db_session):
    r = client.post(
        "/team/users/invite",
        data={
            "email": "new@acme.com",
            "display_name": "New Hire",
            "user_role": "photographer",
            "scope": "group",
        },
    )
    assert r.status_code == 200
    from claimos.models_auth import User
    from claimos.services.grants import list_grants

    u = db_session.query(User).filter(User.email == "new@acme.com").first()
    assert u is not None and u.system_role == "external_user" and u.group_id == "eg"
    assert list_grants(db_session, u.id)[0].user_role == "photographer"


def test_invite_lawyer_is_external_admin(client, db_session):
    client.post(
        "/team/users/invite",
        data={
            "email": "boss@acme.com",
            "display_name": "Boss",
            "user_role": "lawyer",
            "scope": "group",
        },
    )
    from claimos.models_auth import User

    u = db_session.query(User).filter(User.email == "boss@acme.com").first()
    assert u.system_role == "external_admin"


def test_invite_unknown_role_is_400(client):
    r = client.post(
        "/team/users/invite",
        data={
            "email": "x@acme.com",
            "display_name": "X",
            "user_role": "not-a-role",
            "scope": "group",
        },
    )
    assert r.status_code == 400


def test_invite_duplicate_email_is_400(client):
    r = client.post(
        "/team/users/invite",
        data={
            "email": "m1@acme.com",
            "display_name": "Dup",
            "user_role": "photographer",
            "scope": "group",
        },
    )
    assert r.status_code == 400


def test_invite_invalid_grant_is_atomic(client, db_session):
    """A claimant invite with scope=group is invalid (claimant is single-claim-only).

    The grant validation failure must roll back the User row too, so the
    admin can re-invite the same email without hitting "already registered".
    """
    r = client.post(
        "/team/users/invite",
        data={
            "email": "claimant@acme.com",
            "display_name": "Claimant Person",
            "user_role": "claimant",
            "scope": "group",
        },
    )
    assert r.status_code == 400

    from claimos.models_auth import User

    assert db_session.query(User).filter(User.email == "claimant@acme.com").first() is None


def test_invite_foreign_claim_is_400_and_creates_no_user(client, db_session):
    """Cross-firm privilege escalation: inviting scope=claims with another firm's
    claim id must be rejected, and must NOT create the user (atomic on failure).
    """
    r = client.post(
        "/team/users/invite",
        data={
            "email": "escalator@acme.com",
            "display_name": "Escalator",
            "user_role": "valuator",
            "scope": "claims",
            "claim_ids": ["cB"],
        },
    )
    assert r.status_code == 400

    from claimos.models_auth import User

    assert db_session.query(User).filter(User.email == "escalator@acme.com").first() is None


def test_invite_own_claim_scope_succeeds(client, db_session):
    r = client.post(
        "/team/users/invite",
        data={
            "email": "valuator@acme.com",
            "display_name": "Valuator",
            "user_role": "valuator",
            "scope": "claims",
            "claim_ids": ["cA"],
        },
    )
    assert r.status_code == 200

    from claimos.models_auth import User
    from claimos.services.grants import list_grants

    u = db_session.query(User).filter(User.email == "valuator@acme.com").first()
    assert u is not None
    grants = list_grants(db_session, u.id)
    assert len(grants) == 1
    assert grants[0].scope == "claims"
    assert {c.claim_id for c in grants[0].claims} == {"cA"}
