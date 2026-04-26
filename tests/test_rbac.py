"""Tests for RBAC models and dependencies."""

from cvp.models_access import MatterAccess


def test_matter_access_model_fields():
    ma = MatterAccess(
        id="ma1",
        user_id="u1",
        matter_id="m1",
        role="editor",
        granted_by_id="u2",
    )
    assert ma.user_id == "u1"
    assert ma.matter_id == "m1"
    assert ma.role == "editor"
    assert ma.granted_by_id == "u2"
