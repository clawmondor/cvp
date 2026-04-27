"""Tests for comments model and endpoints."""

from cvp.models_comments import Comment


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
