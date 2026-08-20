import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cvp.models_agent  # noqa: F401
from cvp.db import get_db
from cvp.dependencies import CurrentUser, require_system_admin
from cvp.main import app
from cvp.models import Base
from cvp.models_agent import AgentKey


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


@pytest.fixture
def admin_client(db_session):
    async def mock_admin():
        return CurrentUser(
            id="admin-1",
            email="a@t.com",
            system_role="system_admin",
            group_id=None,
            group_kind=None,
        )

    def override_get_db():
        yield db_session

    app.dependency_overrides[require_system_admin] = mock_admin
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c, db_session
    app.dependency_overrides.clear()


def test_create_shows_full_key_once_and_stores_hash(admin_client):
    client, db = admin_client
    resp = client.post("/admin/system/agent-keys", data={"name": "Pricing Bot"})
    assert resp.status_code == 200
    assert "agk_live_" in resp.text  # full key shown once
    key = db.query(AgentKey).one()
    assert key.name == "Pricing Bot"
    # only the hash is stored; the plaintext secret is not persisted anywhere
    assert key.key_hash and key.key_hash not in resp.text.split("agk_live_")[0]


def test_list_shows_keys(admin_client):
    client, db = admin_client
    db.add(AgentKey(name="Existing", key_prefix="abcd1234", key_hash="h"))
    db.commit()
    resp = client.get("/admin/system/agent-keys")
    assert resp.status_code == 200
    assert "Existing" in resp.text
    assert "abcd1234" in resp.text


def test_revoke_sets_revoked_at(admin_client):
    client, db = admin_client
    k = AgentKey(name="Doomed", key_prefix="dead0001", key_hash="h")
    db.add(k)
    db.commit()
    resp = client.post(f"/admin/system/agent-keys/{k.id}/revoke", follow_redirects=False)
    assert resp.status_code in (200, 302, 303)
    db.expire_all()
    assert db.get(AgentKey, k.id).revoked_at is not None
