"""The container's search helper (see test_container_runner.py for why the
import is fixture-scoped rather than done at module import time)."""

import importlib
import json
import sys
from pathlib import Path

import pytest

SHARED = Path(__file__).resolve().parents[1] / "cloudflare" / "images" / "shared"


@pytest.fixture
def search(monkeypatch):
    """Import search.py off the image's flat layout, for one test only."""
    monkeypatch.syspath_prepend(str(SHARED))
    sys.modules.pop("search", None)
    module = importlib.import_module("search")
    yield module
    sys.modules.pop("search", None)


def test_dollars_to_cents_is_half_up_and_integral(search):
    assert search.dollars_to_cents("129.99") == 12999
    assert search.dollars_to_cents("0.005") == 1
    assert search.dollars_to_cents(3.97) == 397
    assert isinstance(search.dollars_to_cents("1.00"), int)


def test_cost_is_converted_to_micro_usd(search):
    assert search.usd_to_micro(0.009835) == 9835
    assert search.usd_to_micro(0) == 0


def test_parses_fenced_json_reply(search, monkeypatch):
    payload = {
        "choices": [
            {
                "message": {
                    "content": (
                        '```json\n{"product_title":"Chair","price_usd":1249.0,'
                        '"retailer":"Stickley","source_url":"https://s.example/c",'
                        '"match_type":"brand","rationale":"why"}\n```'
                    )
                }
            }
        ],
        "usage": {"cost": 0.009835},
    }
    monkeypatch.setattr(search, "_post_openrouter", lambda *a, **k: payload)

    result, cost, used_browser = search.search_for_item(
        description="oak dining chair",
        brand="Stickley",
        model=None,
        model_slug="anthropic/claude-haiku-4.5",
        openrouter_key="k",
        browser_account_id="",
        browser_token="",
    )

    assert result.product_title == "Chair"
    assert result.source_url == "https://s.example/c"
    assert result.match_type == "brand"
    assert cost == 9835
    assert used_browser is False


def test_returns_none_when_model_finds_nothing(search, monkeypatch):
    payload = {"choices": [{"message": {"content": "no match found"}}], "usage": {"cost": 0.001}}
    monkeypatch.setattr(search, "_post_openrouter", lambda *a, **k: payload)

    result, cost, _ = search.search_for_item(
        description="x",
        brand=None,
        model=None,
        model_slug="anthropic/claude-haiku-4.5",
        openrouter_key="k",
        browser_account_id="",
        browser_token="",
    )
    assert result is None
    assert cost == 1000


def test_rejects_result_missing_source_url(search, monkeypatch):
    """Every RCV must have a source — an unsourced match is not a match."""
    payload = {
        "choices": [
            {"message": {"content": json.dumps({"product_title": "C", "price_usd": 10.0})}}
        ],
        "usage": {"cost": 0.001},
    }
    monkeypatch.setattr(search, "_post_openrouter", lambda *a, **k: payload)

    result, _cost, _ = search.search_for_item(
        description="x",
        brand=None,
        model=None,
        model_slug="anthropic/claude-haiku-4.5",
        openrouter_key="k",
        browser_account_id="",
        browser_token="",
    )
    assert result is None


def test_price_keeps_currency_formatting_out_of_the_conversion(search):
    """`"$1,299.99"` is ordinary model output; float() raised ValueError on it,
    wasting a paid search and surfacing a traceback to the specialist."""
    assert search.clean_price("$1,299.99") == "1299.99"
    assert search.dollars_to_cents(search.clean_price("$1,299.99")) == 129999
    assert search.clean_price("USD 89") == "89"


def test_plain_numeric_price_is_passed_through_unconverted(search):
    assert search.clean_price(1249.0) == 1249.0
    assert search.clean_price(1249) == 1249
    assert search.dollars_to_cents(search.clean_price(1249.0)) == 124900


def test_unusable_price_is_discarded_rather_than_raising(search):
    for junk in (None, "", "$", "call for pricing", "$100-$200", True, {"amount": 1}):
        assert search.clean_price(junk) is None


def test_formatted_price_survives_a_full_search(search, monkeypatch):
    payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "product_title": "Chair",
                            "price_usd": "$1,299.99",
                            "retailer": "Shop",
                            "source_url": "https://s.example/c",
                        }
                    )
                }
            }
        ],
        "usage": {"cost": 0.001},
    }
    monkeypatch.setattr(search, "_post_openrouter", lambda *a, **k: payload)

    result, _cost, _ = search.search_for_item(
        description="chair",
        brand=None,
        model=None,
        model_slug="anthropic/claude-haiku-4.5",
        openrouter_key="k",
        browser_account_id="",
        browser_token="",
    )
    assert search.dollars_to_cents(result.price_usd) == 129999
