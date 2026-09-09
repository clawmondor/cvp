"""Unit tests for the Firecrawl service."""

from unittest.mock import patch

import httpx
import pytest

from cvp.models import Item
from cvp.services.firecrawl import FIRECRAWL_SEARCH_URL, build_query, call_firecrawl


def _item(**kw) -> Item:
    defaults = {"description": "", "brand": None, "model": None}
    defaults.update(kw)
    return Item(**defaults)


def test_build_query_joins_brand_model_description():
    item = _item(brand="Stickley", model="A-12", description="oak dining chair")
    assert build_query(item) == "Stickley A-12 oak dining chair"


def test_build_query_skips_missing_brand_and_model():
    item = _item(description="oak dining chair")
    assert build_query(item) == "oak dining chair"


def test_build_query_skips_blank_strings():
    item = _item(brand="   ", model="", description="lamp")
    assert build_query(item) == "lamp"


def test_build_query_collapses_internal_whitespace():
    item = _item(brand="West  Elm", description="floor\tlamp\n")
    assert build_query(item) == "West Elm floor lamp"


def test_build_query_all_empty_returns_empty_string():
    assert build_query(_item()) == ""


class _Resp:
    def __init__(self, status_code=200, payload=None, text="", ct="application/json"):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text
        self.headers = {"content-type": ct}

    def json(self):
        return self._payload


@pytest.fixture
def _key(monkeypatch):
    monkeypatch.setattr("cvp.config.settings.firecrawl_api_key", "fc-secret-abc123")


def test_call_firecrawl_unconfigured_key_returns_error(monkeypatch):
    monkeypatch.setattr("cvp.config.settings.firecrawl_api_key", "")
    url, body, data, status = call_firecrawl("lamp")
    assert status == 0
    assert "not configured" in data["error"]
    assert url == FIRECRAWL_SEARCH_URL


def test_call_firecrawl_success_returns_payload(_key):
    payload = {"success": True, "data": {"web": []}, "creditsUsed": 3}
    with patch("httpx.Client.post", return_value=_Resp(200, payload)):
        url, body, data, status = call_firecrawl("oak chair")
    assert status == 200
    assert data == payload
    assert body["query"] == "oak chair"
    assert body["limit"] == 5
    assert body["scrapeOptions"]["formats"][0]["type"] == "json"


def test_call_firecrawl_never_leaks_the_api_key(_key):
    """The returned body is persisted to SerpSearch.request_params and shown to admins."""
    payload = {"success": True, "data": {"web": []}}
    with patch("httpx.Client.post", return_value=_Resp(200, payload)):
        _url, body, _data, _status = call_firecrawl("oak chair")
    assert "fc-secret-abc123" not in str(body)
    assert "Authorization" not in str(body)


def test_call_firecrawl_timeout_returns_error(_key):
    with patch("httpx.Client.post", side_effect=httpx.TimeoutException("boom")):
        _url, _body, data, status = call_firecrawl("lamp")
    assert status == 0
    assert "timed out" in data["error"]


def test_call_firecrawl_non_json_body_is_wrapped(_key):
    with patch("httpx.Client.post", return_value=_Resp(502, text="Bad Gateway", ct="text/html")):
        _url, _body, data, status = call_firecrawl("lamp")
    assert status == 502
    assert data == {"raw": "Bad Gateway"}


def test_call_firecrawl_unexpected_error_returns_error(_key):
    with patch("httpx.Client.post", side_effect=RuntimeError("kaboom")):
        _url, _body, data, status = call_firecrawl("lamp")
    assert status == 0
    assert "kaboom" in data["error"]
