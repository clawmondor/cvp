import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cloudflare" / "images" / "shared"))

import search  # noqa: E402


def test_dollars_to_cents_is_half_up_and_integral():
    assert search.dollars_to_cents("129.99") == 12999
    assert search.dollars_to_cents("0.005") == 1
    assert search.dollars_to_cents(3.97) == 397
    assert isinstance(search.dollars_to_cents("1.00"), int)


def test_cost_is_converted_to_micro_usd():
    assert search.usd_to_micro(0.009835) == 9835
    assert search.usd_to_micro(0) == 0


def test_parses_fenced_json_reply(monkeypatch):
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


def test_returns_none_when_model_finds_nothing(monkeypatch):
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


def test_rejects_result_missing_source_url(monkeypatch):
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
