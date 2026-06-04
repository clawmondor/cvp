"""Tests for the feedback ORM models."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cvp.models_auth  # noqa: F401 — ensures users/groups tables exist
import cvp.models_feedback  # noqa: F401
from cvp.models import Base
from cvp.models_auth import Group, User
from cvp.models_feedback import Feedback, FeedbackComment


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # SQLite needs PRAGMA foreign_keys=ON for FK enforcement; CHECK works without it.
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    group = Group(id="g1", name="Internal", kind="internal")
    user = User(
        id="u1",
        email="u1@test.com",
        display_name="User One",
        system_role="internal_user",
        group_id="g1",
        is_active=True,
    )
    session.add_all([group, user])
    session.commit()
    yield session
    session.close()


def test_feedback_defaults(db):
    fb = Feedback(
        id="f1",
        author_user_id="u1",
        author_group_id="g1",
        page_url="/dashboard",
        body="Something is broken.",
    )
    db.add(fb)
    db.commit()
    db.refresh(fb)

    assert fb.status == "pending"
    assert fb.created_at is not None
    assert fb.deleted_at is None
    assert fb.deleted_by_user_id is None
    assert fb.last_admin_read_at is None
    assert fb.last_author_read_at is None
    assert fb.status_changed_at is None
    assert fb.status_changed_by_user_id is None


def test_feedback_status_check_rejects_unknown(db):
    fb = Feedback(
        id="f2",
        author_user_id="u1",
        author_group_id="g1",
        page_url="/x",
        body="hi",
        status="not-a-real-status",
    )
    db.add(fb)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_feedback_status_check_accepts_each_allowed_value(db):
    for i, status in enumerate(("pending", "reviewing", "backlog", "canceled", "done")):
        fb = Feedback(
            id=f"f-ok-{i}",
            author_user_id="u1",
            author_group_id="g1",
            page_url="/x",
            body="hi",
            status=status,
        )
        db.add(fb)
        db.commit()


def test_feedback_comment_defaults(db):
    fb = Feedback(
        id="f3",
        author_user_id="u1",
        author_group_id="g1",
        page_url="/x",
        body="hi",
    )
    db.add(fb)
    db.commit()
    c = FeedbackComment(
        id="c1",
        feedback_id="f3",
        author_user_id="u1",
        body="follow up",
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    assert c.created_at is not None
    assert c.deleted_at is None
    assert c.deleted_by_user_id is None
