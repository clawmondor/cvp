import json

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cvp.models_agent  # noqa: F401
from cvp.models import Base, Category, Item, Matter
from cvp.models_agent import AgentKey, AgentRun
from cvp.services import agent_launch
from cvp.services.agent_keys import generate_key


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


@pytest.fixture
def run_id(session_factory, monkeypatch):
    monkeypatch.setattr(agent_launch, "SessionLocal", session_factory)
    db = session_factory()
    m = Matter(firm_name="F")
    db.add(m)
    db.add(Category(id=1, name="Furniture", useful_life_years=10, acv_floor_pct=0.2))
    db.flush()
    item = Item(matter_id=m.id, category_id=1, description="chair", quantity=1)
    db.add(item)
    _, prefix, key_hash = generate_key()
    key = AgentKey(name="cf", key_prefix=prefix, key_hash=key_hash)
    db.add(key)
    db.flush()
    run = AgentRun(
        item_id=item.id,
        matter_id=m.id,
        agent_impl="custom-python",
        model_slug="anthropic/claude-haiku-4.5",
        agent_key_id=key.id,
    )
    db.add(run)
    db.commit()
    rid = run.id
    db.close()
    return rid


class _Resp:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


def test_successful_launch_marks_running(run_id, session_factory, monkeypatch):
    captured = {}

    class _Client:
        def __init__(self, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, content=None, headers=None):
            captured["url"] = url
            captured["content"] = content
            captured["headers"] = headers
            return _Resp(202)

    monkeypatch.setattr(agent_launch.httpx, "Client", _Client)
    monkeypatch.setattr(agent_launch.settings, "cloudflare_agent_worker_url", "https://w.example")
    monkeypatch.setattr(agent_launch.settings, "cloudflare_launch_hmac_secret", "s3cret")

    agent_launch.launch_run(run_id)

    db = session_factory()
    run = db.get(AgentRun, run_id)
    assert run.status == "running"
    assert run.started_at is not None
    assert captured["url"] == "https://w.example/runs"
    assert "X-CVP-Signature" in captured["headers"]
    assert "X-CVP-Timestamp" in captured["headers"]
    # The launch payload must never carry credentials. An exact key set, not a
    # substring scan: no reachable value contains "KEY" or "secret", so the
    # old assertions would have passed even with a secret added under a
    # differently-spelled key.
    assert set(json.loads(captured["content"])) == {
        "run_id",
        "matter_id",
        "item_id",
        "model_slug",
        "agent_impl",
    }
    db.close()


def test_non_2xx_marks_failed(run_id, session_factory, monkeypatch):
    class _Client:
        def __init__(self, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, content=None, headers=None):
            return _Resp(500, "boom")

    monkeypatch.setattr(agent_launch.httpx, "Client", _Client)
    monkeypatch.setattr(agent_launch.settings, "cloudflare_agent_worker_url", "https://w.example")
    monkeypatch.setattr(agent_launch.settings, "cloudflare_launch_hmac_secret", "s3cret")

    agent_launch.launch_run(run_id)

    db = session_factory()
    run = db.get(AgentRun, run_id)
    assert run.status == "failed"
    assert "500" in run.error
    db.close()


def test_unconfigured_worker_marks_failed(run_id, session_factory, monkeypatch):
    monkeypatch.setattr(agent_launch.settings, "cloudflare_agent_worker_url", "")

    agent_launch.launch_run(run_id)

    db = session_factory()
    run = db.get(AgentRun, run_id)
    assert run.status == "failed"
    assert "not configured" in run.error
    db.close()


def test_unreachable_worker_marks_failed(run_id, session_factory, monkeypatch):
    """Transport failure — e.g. the Worker is down or DNS fails — is the
    money-at-risk path: a launch that silently drops here would strand a
    run with no record of what happened."""

    class _Client:
        def __init__(self, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, content=None, headers=None):
            raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(agent_launch.httpx, "Client", _Client)
    monkeypatch.setattr(agent_launch.settings, "cloudflare_agent_worker_url", "https://w.example")
    monkeypatch.setattr(agent_launch.settings, "cloudflare_launch_hmac_secret", "s3cret")

    agent_launch.launch_run(run_id)

    db = session_factory()
    run = db.get(AgentRun, run_id)
    assert run.status == "failed"
    assert "reach" in run.error.lower()
    db.close()


def test_unexpected_error_marks_failed_without_raising(run_id, session_factory, monkeypatch):
    """launch_run runs in a BackgroundTask with no caller to observe an
    exception, so nothing may propagate — not even a failure that happens
    before the outbound POST (e.g. signing blows up). This exercises the
    outer catch-all rather than the transport-specific except."""

    monkeypatch.setattr(agent_launch.settings, "cloudflare_agent_worker_url", "https://w.example")
    monkeypatch.setattr(agent_launch.settings, "cloudflare_launch_hmac_secret", "s3cret")

    def _boom(*args, **kwargs):
        raise RuntimeError("signing exploded")

    monkeypatch.setattr(agent_launch, "sign_payload", _boom)

    agent_launch.launch_run(run_id)  # must return normally, not raise

    db = session_factory()
    run = db.get(AgentRun, run_id)
    assert run.status == "failed"
    assert "signing exploded" in run.error
    db.close()
