"""Tests for the project-wide plain-text input validator."""

import pytest
from fastapi import HTTPException

from cvp.text_validation import assert_plain_text


def test_accepts_plain_ascii():
    assert_plain_text("Hello world, this is fine.", field_name="body")


def test_accepts_unicode_and_emoji():
    assert_plain_text("Café — résumé — 🎉 — Привет", field_name="body")


def test_accepts_newlines_tabs_and_carriage_returns():
    assert_plain_text("line one\nline two\twith tab\r\nline three", field_name="body")


def test_rejects_less_than():
    with pytest.raises(HTTPException) as exc:
        assert_plain_text("a < b", field_name="body")
    assert exc.value.status_code == 400
    assert "body" in exc.value.detail


def test_rejects_greater_than():
    with pytest.raises(HTTPException) as exc:
        assert_plain_text("a > b", field_name="body")
    assert exc.value.status_code == 400


def test_rejects_script_tag():
    with pytest.raises(HTTPException) as exc:
        assert_plain_text("<script>alert(1)</script>", field_name="body")
    assert exc.value.status_code == 400


def test_rejects_numeric_html_entity():
    with pytest.raises(HTTPException) as exc:
        assert_plain_text("&#60;script&#62;", field_name="body")
    assert exc.value.status_code == 400


def test_rejects_named_html_entity():
    with pytest.raises(HTTPException) as exc:
        assert_plain_text("AT&amp;T", field_name="body")
    assert exc.value.status_code == 400


def test_rejects_javascript_scheme_case_insensitive():
    with pytest.raises(HTTPException):
        assert_plain_text("click javascript:alert(1)", field_name="body")
    with pytest.raises(HTTPException):
        assert_plain_text("click JaVaScRiPt:alert(1)", field_name="body")


def test_rejects_data_scheme_case_insensitive():
    with pytest.raises(HTTPException):
        assert_plain_text("see data:text/html,foo", field_name="body")
    with pytest.raises(HTTPException):
        assert_plain_text("see DATA:text/html,foo", field_name="body")


def test_rejects_nul_byte():
    with pytest.raises(HTTPException):
        assert_plain_text("hello\x00world", field_name="body")


def test_rejects_escape_byte():
    with pytest.raises(HTTPException):
        assert_plain_text("hello\x1bworld", field_name="body")


def test_error_message_uses_field_name():
    with pytest.raises(HTTPException) as exc:
        assert_plain_text("<", field_name="Matter description")
    assert "Matter description" in exc.value.detail


def test_default_field_name_is_input():
    with pytest.raises(HTTPException) as exc:
        assert_plain_text("<")
    assert "input" in exc.value.detail
