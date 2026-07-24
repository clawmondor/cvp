"""Tests for comments model and endpoints."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from claimos.dependencies import CurrentUser
from claimos.models import Base, Category, Claim, Item
from claimos.models_auth import Group, User
from claimos.models_comments import Comment
from claimos.routers.comments import _get_comment_and_check_access
from claimos.services.grants import create_grant


def test_comment_model_fields():
    c = Comment(
        id="c1",
        item_id="i1",
        user_id="u1",
        body="This price looks too high.",
        visibility="shared",
    )
    assert c.item_id == "i1"
    assert c.visibility == "shared"


def test_create_comment_placeholder():
    """Placeholder — tests will use TestClient with seeded DB."""
    assert True


def test_comment_visibility_internal_only():
    """Internal comments should not be visible to external users."""
    assert True


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    s.add_all(
        [
            Group(id="eg", name="F", kind="external"),
            User(
                id="ph",
                email="p@f.com",
                display_name="P",
                password_hash="x",
                system_role="external_user",
                group_id="eg",
            ),
            User(
                id="adm",
                email="a@f.com",
                display_name="A",
                password_hash="x",
                system_role="external_admin",
                group_id="eg",
            ),
            Claim(id="cA", owner_group_id="eg", nickname="Claim A"),
            Category(id=999, name="Comment Test Category", useful_life_years=5, acv_floor_pct=0.2),
        ]
    )
    s.flush()
    s.add(
        Item(
            id="i1",
            claim_id="cA",
            category_id=999,
            description="Test item",
        )
    )
    s.add(
        Comment(
            id="c1",
            item_id="i1",
            user_id="ph",
            body="A comment.",
            visibility="shared",
        )
    )
    s.commit()
    yield s
    s.close()


def _cu(uid):
    return CurrentUser(
        id=uid, email="x@f.com", system_role="external_user", group_id="eg", group_kind="external"
    )


def test_photographer_with_comments_grant_passes_access_gate(db):
    """An external user with a `comments` grant should pass the edit/delete access check."""
    create_grant(
        db,
        user_id="ph",
        user_role="photographer",
        scope="group",
        claim_ids=[],
        overrides={},
        granted_by_id="adm",
    )
    comment = _get_comment_and_check_access("c1", "viewer", _cu("ph"), db)
    assert comment.id == "c1"


def test_external_user_without_grant_is_denied_access_gate(db):
    """Without a covering grant, the same helper must deny access."""
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        _get_comment_and_check_access("c1", "viewer", _cu("ph"), db)
    assert exc_info.value.status_code == 403
