"""Tests for feedback-router sanitization helpers."""

from cvp.routers.feedback import _clean_page_url


def test_accepts_simple_path():
    assert _clean_page_url("/dashboard") == "/dashboard"


def test_accepts_path_with_query():
    assert _clean_page_url("/matters/abc?tab=items") == "/matters/abc?tab=items"


def test_rejects_protocol_relative():
    assert _clean_page_url("//evil.com/x") == "/"


def test_rejects_absolute_http():
    assert _clean_page_url("http://evil.com/x") == "/"


def test_rejects_absolute_https():
    assert _clean_page_url("https://evil.com/x") == "/"


def test_rejects_javascript_scheme():
    assert _clean_page_url("javascript:alert(1)") == "/"


def test_rejects_data_scheme():
    assert _clean_page_url("data:text/html,foo") == "/"


def test_rejects_empty():
    assert _clean_page_url("") == "/"


def test_rejects_no_leading_slash():
    assert _clean_page_url("dashboard") == "/"


def test_truncates_over_2048_to_fallback():
    long_url = "/" + ("a" * 3000)
    assert _clean_page_url(long_url) == "/"
