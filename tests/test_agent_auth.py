import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cvp.models_agent  # noqa: F401
from cvp.agent_auth import AgentPrincipal, require_agent_key
from cvp.db import get_db
from cvp.models import Base
from cvp.models_agent import AgentKey
from cvp.services.agent_keys import generate_key


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
def client(db_session):
    app = FastAPI()

    @app.get("/whoami")
    def whoami(principal: AgentPrincipal = Depends(require_agent_key)):
        return {"agent_key_id": principal.agent_key_id, "name": principal.name}

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def _make_key(db_session, revoked=False):
    full, prefix, key_hash = generate_key()
    from datetime import datetime

    key = AgentKey(
        name="Bot A",
        key_prefix=prefix,
        key_hash=key_hash,
        revoked_at=datetime.utcnow() if revoked else None,
    )
    db_session.add(key)
    db_session.commit()
    return full, key.id


def test_valid_key_authenticates_and_updates_last_used(client, db_session):
    full, key_id = _make_key(db_session)
    resp = client.get("/whoami", headers={"X-API-Key": full})
    assert resp.status_code == 200
    assert resp.json()["agent_key_id"] == key_id
    refreshed = db_session.get(AgentKey, key_id)
    assert refreshed.last_used_at is not None


def test_missing_key_is_401(client):
    assert client.get("/whoami").status_code == 401


def test_unknown_prefix_is_401(client):
    assert client.get("/whoami", headers={"X-API-Key": "agk_live_deadbeef_zzz"}).status_code == 401


def test_tampered_secret_is_401(client, db_session):
    full, _ = _make_key(db_session)
    tampered = full[:-3] + "aaa"
    assert client.get("/whoami", headers={"X-API-Key": tampered}).status_code == 401


def test_revoked_key_is_401(client, db_session):
    full, _ = _make_key(db_session, revoked=True)
    assert client.get("/whoami", headers={"X-API-Key": full}).status_code == 401
