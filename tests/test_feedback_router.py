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


def test_widget_get_returns_panel_with_own_threads(client_and_db):
    client, db = client_and_db
    db.add(
        Feedback(
            id="f1",
            author_user_id="u1",
            author_group_id="g1",
            page_url="/x",
            body="mine",
        )
    )
    db.add(
        Feedback(
            id="f2",
            author_user_id="u2",
            author_group_id="g1",
            page_url="/x",
            body="not mine",
        )
    )
    db.commit()
    resp = client.get("/feedback/widget")
    assert resp.status_code == 200
    assert "mine" in resp.text
    assert "not mine" not in resp.text


def test_widget_get_hides_authors_soft_deleted(client_and_db):
    from datetime import datetime, timezone

    client, db = client_and_db
    db.add(
        Feedback(
            id="f1",
            author_user_id="u1",
            author_group_id="g1",
            page_url="/x",
            body="visible-body",
        )
    )
    db.add(
        Feedback(
            id="f2",
            author_user_id="u1",
            author_group_id="g1",
            page_url="/x",
            body="deleted-body",
            deleted_at=datetime.now(timezone.utc),
            deleted_by_user_id="u1",
        )
    )
    db.commit()
    resp = client.get("/feedback/widget")
    assert "visible-body" in resp.text
    assert "deleted-body" not in resp.text


def test_get_thread_as_author_succeeds(client_and_db):
    client, db = client_and_db
    db.add(
        Feedback(
            id="fA",
            author_user_id="u1",
            author_group_id="g1",
            page_url="/x",
            body="my-body",
        )
    )
    db.commit()
    resp = client.get("/feedback/fA")
    assert resp.status_code == 200
    assert "my-body" in resp.text


def test_get_thread_as_other_user_403(client_and_db):
    client, db = client_and_db
    db.add(
        Feedback(
            id="fB",
            author_user_id="u2",
            author_group_id="g1",
            page_url="/x",
            body="other-body",
        )
    )
    db.commit()
    resp = client.get("/feedback/fB")
    assert resp.status_code == 403


def test_get_thread_404_when_missing(client_and_db):
    client, _db = client_and_db
    resp = client.get("/feedback/does-not-exist")
    assert resp.status_code == 404


def test_post_comment_as_author_succeeds(client_and_db):
    client, db = client_and_db
    db.add(
        Feedback(
            id="fC",
            author_user_id="u1",
            author_group_id="g1",
            page_url="/x",
            body="parent",
        )
    )
    db.commit()
    resp = client.post("/feedback/fC/comments", data={"body": "a reply"})
    assert resp.status_code == 200
    comments = db.query(FeedbackComment).all()
    assert len(comments) == 1
    assert comments[0].body == "a reply"
    assert comments[0].author_user_id == "u1"


def test_post_comment_rejects_html(client_and_db):
    client, db = client_and_db
    db.add(
        Feedback(
            id="fD",
            author_user_id="u1",
            author_group_id="g1",
            page_url="/x",
            body="parent",
        )
    )
    db.commit()
    resp = client.post("/feedback/fD/comments", data={"body": "<img onerror=x>"})
    assert resp.status_code == 400


def test_post_comment_rejects_oversize(client_and_db):
    client, db = client_and_db
    db.add(
        Feedback(
            id="fE",
            author_user_id="u1",
            author_group_id="g1",
            page_url="/x",
            body="parent",
        )
    )
    db.commit()
    resp = client.post("/feedback/fE/comments", data={"body": "a" * 2001})
    assert resp.status_code == 400


def test_post_comment_on_others_thread_403(client_and_db):
    client, db = client_and_db
    db.add(
        Feedback(
            id="fF",
            author_user_id="u2",
            author_group_id="g1",
            page_url="/x",
            body="not mine",
        )
    )
    db.commit()
    resp = client.post("/feedback/fF/comments", data={"body": "hi"})
    assert resp.status_code == 403


def test_mark_read_as_author_updates_author_cursor(client_and_db):
    client, db = client_and_db
    db.add(
        Feedback(
            id="fR",
            author_user_id="u1",
            author_group_id="g1",
            page_url="/x",
            body="b",
        )
    )
    db.commit()
    resp = client.post("/feedback/fR/read")
    assert resp.status_code == 200
    db.expire_all()
    fb = db.get(Feedback, "fR")
    assert fb.last_author_read_at is not None
    assert fb.last_admin_read_at is None


def test_soft_delete_feedback_as_author(client_and_db):
    client, db = client_and_db
    db.add(
        Feedback(
            id="fS",
            author_user_id="u1",
            author_group_id="g1",
            page_url="/x",
            body="b",
        )
    )
    db.commit()
    resp = client.post("/feedback/fS/delete")
    assert resp.status_code == 200
    db.expire_all()
    fb = db.get(Feedback, "fS")
    assert fb.deleted_at is not None
    assert fb.deleted_by_user_id == "u1"


def test_soft_delete_feedback_as_other_403(client_and_db):
    client, db = client_and_db
    db.add(
        Feedback(
            id="fS2",
            author_user_id="u2",
            author_group_id="g1",
            page_url="/x",
            body="b",
        )
    )
    db.commit()
    resp = client.post("/feedback/fS2/delete")
    assert resp.status_code == 403


def test_soft_delete_comment_as_comment_author(client_and_db):
    client, db = client_and_db
    db.add(
        Feedback(
            id="fC2",
            author_user_id="u1",
            author_group_id="g1",
            page_url="/x",
            body="b",
        )
    )
    db.add(FeedbackComment(id="cD", feedback_id="fC2", author_user_id="u1", body="mine"))
    db.commit()
    resp = client.post("/feedback/comments/cD/delete")
    assert resp.status_code == 200
    db.expire_all()
    c = db.get(FeedbackComment, "cD")
    assert c.deleted_at is not None
    assert c.deleted_by_user_id == "u1"


def test_soft_delete_other_user_comment_403(client_and_db):
    client, db = client_and_db
    db.add(
        Feedback(
            id="fC3",
            author_user_id="u1",
            author_group_id="g1",
            page_url="/x",
            body="b",
        )
    )
    db.add(FeedbackComment(id="cE", feedback_id="fC3", author_user_id="u2", body="theirs"))
    db.commit()
    resp = client.post("/feedback/comments/cE/delete")
    assert resp.status_code == 403
