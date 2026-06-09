"""Tests for the placard-aware vision prompt and response parser."""

import json

from cvp.services.vision import _parse_response
from cvp.services.vision_prompts import SCAN_PROMPT_VERSION, build_scan_prompt


def test_prompt_version_bumped() -> None:
    assert SCAN_PROMPT_VERSION == "v4"


def test_prompt_mentions_placard_field() -> None:
    prompt = build_scan_prompt(800, 600)
    assert "placard_text" in prompt
    assert "placard" in prompt.lower()


def test_parse_response_object_with_items_and_placard() -> None:
    payload = json.dumps(
        {
            "items": [{"description": "TV"}, {"description": "lamp"}],
            "placard_text": "12",
        }
    )
    items, placard = _parse_response(payload)
    assert len(items) == 2
    assert placard == "12"


def test_parse_response_object_with_empty_placard() -> None:
    payload = json.dumps({"items": [{"description": "TV"}], "placard_text": ""})
    items, placard = _parse_response(payload)
    assert len(items) == 1
    assert placard == ""


def test_parse_response_legacy_array_returns_empty_placard() -> None:
    """Older prompt versions / non-compliant models still return a JSON array."""
    payload = json.dumps([{"description": "TV"}])
    items, placard = _parse_response(payload)
    assert len(items) == 1
    assert placard == ""


def test_parse_response_garbage_returns_empty() -> None:
    items, placard = _parse_response("not json")
    assert items == []
    assert placard == ""


def test_parse_response_strips_markdown_fences() -> None:
    """JSON wrapped in ```json fences must still parse."""
    payload = "```json\n" + json.dumps({"items": [], "placard_text": "A"}) + "\n```"
    items, placard = _parse_response(payload)
    assert items == []
    assert placard == "A"
