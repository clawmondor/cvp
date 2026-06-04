"""Tests for FastAPI auth dependencies."""

from unittest.mock import MagicMock

from cvp.auth import create_access_token
from cvp.dependencies import CurrentUser, _decode_and_build_user, _extract_token

TEST_SECRET = "testsecret123456789012345678901234"


def _make_token(**overrides) -> str:
    defaults = {
        "user_id": "u1",
        "email": "test@example.com",
        "system_role": "internal_user",
        "group_id": "g1",
        "group_kind": "internal",
        "secret": TEST_SECRET,
        "ttl_minutes": 60,
    }
    defaults.update(overrides)
    return create_access_token(**defaults)


def test_current_user_model():
    u = CurrentUser(
        id="u1",
        email="test@example.com",
        system_role="internal_user",
        group_id="g1",
        group_kind="internal",
    )
    assert u.id == "u1"
    assert u.system_role == "internal_user"


def test_extract_token_from_auth_header():
    request = MagicMock()
    request.headers = {"authorization": "Bearer mytoken123"}
    request.cookies = {}
    token, source = _extract_token(request)
    assert token == "mytoken123"
    assert source == "header"


def test_extract_token_from_cookie():
    request = MagicMock()
    request.headers = {}
    request.cookies = {"cvp_access": "cookietoken456"}
    token, source = _extract_token(request)
    assert token == "cookietoken456"
    assert source == "cookie"


def test_extract_token_none_when_missing():
    request = MagicMock()
    request.headers = {}
    request.cookies = {}
    token, source = _extract_token(request)
    assert token is None
    assert source is None


def test_extract_token_header_takes_precedence():
    request = MagicMock()
    request.headers = {"authorization": "Bearer headertoken"}
    request.cookies = {"cvp_access": "cookietoken"}
    token, source = _extract_token(request)
    assert token == "headertoken"
    assert source == "header"


def test_decode_and_build_user_valid():
    token = _make_token()
    user = _decode_and_build_user(token, TEST_SECRET)
    assert user.id == "u1"
    assert user.email == "test@example.com"


def test_decode_and_build_user_expired():
    token = _make_token(ttl_minutes=-1)
    user = _decode_and_build_user(token, TEST_SECRET)
    assert user is None


def test_decode_and_build_user_bad_secret():
    token = _make_token()
    user = _decode_and_build_user(token, "wrong_secret_that_is_long_enough!!")
    assert user is None


def test_check_feedback_access_author_allowed():
    from cvp.dependencies import CurrentUser, _check_feedback_access
    from cvp.models_feedback import Feedback

    user = CurrentUser(
        id="u1", email="u@x", system_role="internal_user", group_id="g", group_kind="internal"
    )
    fb = Feedback(id="f", author_user_id="u1", author_group_id="g", page_url="/x", body="b")
    assert _check_feedback_access(user, fb) is True


def test_check_feedback_access_admin_allowed():
    from cvp.dependencies import CurrentUser, _check_feedback_access
    from cvp.models_feedback import Feedback

    user = CurrentUser(
        id="admin", email="a@x", system_role="system_admin", group_id="g", group_kind="internal"
    )
    fb = Feedback(
        id="f", author_user_id="someone_else", author_group_id="g", page_url="/x", body="b"
    )
    assert _check_feedback_access(user, fb) is True


def test_check_feedback_access_other_user_denied():
    from cvp.dependencies import CurrentUser, _check_feedback_access
    from cvp.models_feedback import Feedback

    user = CurrentUser(
        id="u2", email="u@x", system_role="internal_admin", group_id="g", group_kind="internal"
    )
    fb = Feedback(id="f", author_user_id="u1", author_group_id="g", page_url="/x", body="b")
    assert _check_feedback_access(user, fb) is False
