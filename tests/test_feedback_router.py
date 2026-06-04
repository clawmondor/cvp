"""Integration tests for the user-facing feedback router."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cvp.models_auth  # noqa: F401
import cvp.models_feedback  # noqa: F401
from cvp.dependencies import CurrentUser, require_active_user
from cvp.models import Base
from cvp.models_auth import Group, User
from cvp.models_feedback import Feedback, FeedbackComment


def _session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _seed(db, *, role="internal_user"):
    group = Group(id="g1", name="Internal", kind="internal")
    user = User(
        id="u1",
        email="u1@test.com",
        display_name="User One",
        system_role=role,
        group_id="g1",
        is_active=True,
    )
    other = User(
        id="u2",
        email="u2@test.com",
        display_name="User Two",
        system_role="internal_user",
        group_id="g1",
        is_active=True,
    )
    db.add_all([group, user, other])
    db.commit()
    return user, other


@pytest.fixture
def client_and_db():
    from cvp.db import get_db
    from cvp.main import app

    db = _session()
    user, _other = _seed(db)

    async def fake_user():
        return CurrentUser(
            id=user.id,
            email=user.email,
            system_role=user.system_role,
            group_id=user.group_id,
            group_kind="internal",
        )

    def override_get_db():
        yield db

    app.dependency_overrides[require_active_user] = fake_user
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c, db
    app.dependency_overrides.clear()


def test_submit_feedback_creates_pending_row(client_and_db):
    client, db = client_and_db
    resp = client.post(
        "/feedback",
        data={"body": "The font is too small.", "page_url": "/dashboard"},
    )
    assert resp.status_code == 200
    rows = db.query(Feedback).all()
    assert len(rows) == 1
    assert rows[0].body == "The font is too small."
    assert rows[0].status == "pending"
    assert rows[0].page_url == "/dashboard"
    assert rows[0].author_user_id == "u1"
    assert rows[0].author_group_id == "g1"


def test_submit_feedback_rejects_html(client_and_db):
    client, _db = client_and_db
    resp = client.post(
        "/feedback",
        data={"body": "<script>x</script>", "page_url": "/dashboard"},
    )
    assert resp.status_code == 400


def test_submit_feedback_rejects_empty(client_and_db):
    client, _db = client_and_db
    resp = client.post("/feedback", data={"body": "   ", "page_url": "/dashboard"})
    assert resp.status_code == 400


def test_submit_feedback_rejects_oversize(client_and_db):
    client, _db = client_and_db
    resp = client.post(
        "/feedback",
        data={"body": "a" * 5001, "page_url": "/dashboard"},
    )
    assert resp.status_code == 400


def test_submit_feedback_sanitizes_bad_url_to_root(client_and_db):
    client, db = client_and_db
    resp = client.post(
        "/feedback",
        data={"body": "fine body", "page_url": "//evil.com"},
    )
    assert resp.status_code == 200
    assert db.query(Feedback).one().page_url == "/"
