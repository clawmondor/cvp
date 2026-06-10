"""Tests for vision prompt v4."""

from cvp.services.vision_prompts import SCAN_PROMPT_VERSION, build_scan_prompt


def test_version_is_v4():
    assert SCAN_PROMPT_VERSION == "v4"


def test_build_scan_prompt_injects_dimensions():
    prompt = build_scan_prompt(1920, 1080)
    assert "1920" in prompt
    assert "1080" in prompt
    assert "1920×1080" in prompt


def test_build_scan_prompt_contains_bounding_box():
    prompt = build_scan_prompt(800, 600)
    assert '"bounding_box"' in prompt


def test_build_scan_prompt_contains_insurance_framing():
    prompt = build_scan_prompt(800, 600)
    assert "insurance claim" in prompt
    assert "contents inventory specialist" in prompt


def test_build_scan_prompt_contains_category_hints():
    prompt = build_scan_prompt(800, 600)
    assert "Electronics, TVs and displays" in prompt
    assert "Miscellaneous household goods" in prompt


def test_build_scan_prompt_contains_search_hint():
    prompt = build_scan_prompt(800, 600)
    assert '"search_hint"' in prompt


def test_build_scan_prompt_bbox_example_coordinates_are_in_bounds():
    w, h = 640, 480
    prompt = build_scan_prompt(w, h)
    # ex_left = round(w * 2/3) = 427, ex_right = w - 20 = 620, ex_lower = round(h * 0.85) = 408
    assert "427" in prompt
    assert "620" in prompt
    assert "408" in prompt
