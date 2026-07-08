"""Unit tests for recrop_item_crop service."""

from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy.orm import configure_mappers

from claimos.models import EvidenceFile, ItemCrop
from claimos.services.crop import recrop_item_crop

configure_mappers()


def _make_ef(ef_id: str, stored_path: str) -> EvidenceFile:
    ef = EvidenceFile.__new__(EvidenceFile)
    ef.__dict__.update({"id": ef_id, "stored_path": stored_path})
    return ef


def _make_crop(
    crop_id: str,
    *,
    left=0,
    upper=0,
    right=50,
    lower=50,
    adj_left=None,
    adj_upper=None,
    adj_right=None,
    adj_lower=None,
) -> ItemCrop:
    crop = ItemCrop.__new__(ItemCrop)
    crop.__dict__.update(
        {
            "id": crop_id,
            "bbox_left": left,
            "bbox_upper": upper,
            "bbox_right": right,
            "bbox_lower": lower,
            "adjusted_bbox_left": adj_left,
            "adjusted_bbox_upper": adj_upper,
            "adjusted_bbox_right": adj_right,
            "adjusted_bbox_lower": adj_lower,
        }
    )
    return crop


@pytest.fixture
def tmp_dirs(tmp_path):
    upload = tmp_path / "uploads"
    crops = tmp_path / "crops"
    upload.mkdir()
    crops.mkdir()
    return upload, crops


def _write_image(path: Path, w: int = 200, h: int = 200) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (w, h), color=(128, 64, 32)).save(path, "JPEG")


def test_recrop_saves_jpeg_and_returns_relative_path(tmp_dirs):
    upload, crop_base = tmp_dirs
    _write_image(upload / "ef1" / "photo.jpg")

    ef = _make_ef("ef1", "ef1/photo.jpg")
    crop = _make_crop("crop1", left=10, upper=10, right=60, lower=60)

    result = recrop_item_crop(crop, ef, upload, crop_base)

    assert result == "ef1/crop1.jpg"
    assert (crop_base / "ef1" / "crop1.jpg").exists()
    assert not result.startswith("/")


def test_recrop_uses_adjusted_bbox_when_all_four_set(tmp_dirs):
    upload, crop_base = tmp_dirs
    _write_image(upload / "ef2" / "photo.jpg")

    ef = _make_ef("ef2", "ef2/photo.jpg")
    # Claude bbox is 10×10; adjusted bbox is 80×80 — output size should differ
    crop = _make_crop(
        "crop2",
        left=0,
        upper=0,
        right=10,
        lower=10,
        adj_left=10,
        adj_upper=10,
        adj_right=90,
        adj_lower=90,
    )

    recrop_item_crop(crop, ef, upload, crop_base)

    saved = Image.open(crop_base / "ef2" / "crop2.jpg")
    w, h = saved.size
    assert w > 20 and h > 20  # 80×80 adjusted bbox, not the 10×10 Claude bbox


def test_recrop_uses_claude_bbox_when_adjustment_incomplete(tmp_dirs):
    upload, crop_base = tmp_dirs
    _write_image(upload / "ef3" / "photo.jpg")

    ef = _make_ef("ef3", "ef3/photo.jpg")
    crop = _make_crop(
        "crop3",
        left=0,
        upper=0,
        right=20,
        lower=20,
        adj_left=50,
        adj_upper=None,
        adj_right=100,
        adj_lower=100,  # adj_upper is None
    )

    recrop_item_crop(crop, ef, upload, crop_base)

    saved = Image.open(crop_base / "ef3" / "crop3.jpg")
    w, h = saved.size
    assert w == 20 and h == 20  # Claude bbox used (20×20), not the 50×100 range
