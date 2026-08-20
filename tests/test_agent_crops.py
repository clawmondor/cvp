import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cvp.models_agent  # noqa: F401
from cvp.config import settings
from cvp.db import get_db
from cvp.main import app
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
def key(db_session):
    full, prefix, key_hash = generate_key()
    db_session.add(AgentKey(name="Bot", key_prefix=prefix, key_hash=key_hash))
    db_session.commit()
    return full


def test_crop_route_requires_key(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "crop_dir", str(tmp_path))

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    try:
        assert client.get("/api/agent/crops/x.jpg").status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_crop_route_serves_and_blocks_traversal(db_session, key, tmp_path, monkeypatch):
    (tmp_path / "c.jpg").write_bytes(b"img")
    monkeypatch.setattr(settings, "crop_dir", str(tmp_path))

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    try:
        ok = client.get("/api/agent/crops/c.jpg", headers={"X-API-Key": key})
        assert ok.status_code == 200 and ok.content == b"img"
        bad = client.get("/api/agent/crops/../secret", headers={"X-API-Key": key})
        assert bad.status_code in (403, 404)
    finally:
        app.dependency_overrides.clear()
