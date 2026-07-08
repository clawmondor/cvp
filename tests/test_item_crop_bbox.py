"""Unit tests for ItemCrop.effective_bbox property."""

from sqlalchemy.orm import configure_mappers

from claimos.models import ItemCrop

configure_mappers()


def _make_crop(**kwargs) -> ItemCrop:
    defaults = dict(
        id="crop-1",
        item_id="item-1",
        evidence_file_id="ef-1",
        bbox_left=10,
        bbox_upper=20,
        bbox_right=100,
        bbox_lower=200,
        crop_path="ef-1/crop-1.jpg",
        adjusted_bbox_left=None,
        adjusted_bbox_upper=None,
        adjusted_bbox_right=None,
        adjusted_bbox_lower=None,
    )
    defaults.update(kwargs)
    crop = ItemCrop.__new__(ItemCrop)
    crop.__dict__.update(defaults)
    return crop


def test_effective_bbox_returns_claude_bbox_when_no_adjustment():
    crop = _make_crop()
    assert crop.effective_bbox == (10, 20, 100, 200)


def test_effective_bbox_returns_adjusted_when_all_four_set():
    crop = _make_crop(
        adjusted_bbox_left=5,
        adjusted_bbox_upper=15,
        adjusted_bbox_right=95,
        adjusted_bbox_lower=195,
    )
    assert crop.effective_bbox == (5, 15, 95, 195)


def test_effective_bbox_falls_back_if_any_adjusted_is_none():
    crop = _make_crop(
        adjusted_bbox_left=5,
        adjusted_bbox_upper=None,
        adjusted_bbox_right=95,
        adjusted_bbox_lower=195,
    )
    assert crop.effective_bbox == (10, 20, 100, 200)


def test_effective_bbox_treats_zero_as_valid():
    """Zero is a valid pixel coordinate, not 'unset'."""
    crop = _make_crop(
        adjusted_bbox_left=0,
        adjusted_bbox_upper=0,
        adjusted_bbox_right=50,
        adjusted_bbox_lower=50,
    )
    assert crop.effective_bbox == (0, 0, 50, 50)
