"""Crop image service — re-crop an ItemCrop using its effective_bbox."""

from pathlib import Path

from PIL import Image

from claimos.models import EvidenceFile, ItemCrop


def recrop_item_crop(
    item_crop: ItemCrop,
    evidence_file: EvidenceFile,
    upload_base: Path,
    crop_base: Path,
) -> str:
    """
    Re-crop the item using effective_bbox (adjusted if set, else Claude's original).

    Opens the original evidence image, crops to effective_bbox, saves JPEG at quality 85
    to <crop_base>/<evidence_file.id>/<item_crop.id>.jpg.
    Returns the relative crop_path string (no leading slash).
    No additional padding is applied — coordinates are the final crop boundary.
    """
    image_path = (upload_base / evidence_file.stored_path).resolve()
    left, upper, right, lower = item_crop.effective_bbox

    crop_dir = crop_base / evidence_file.id
    crop_dir.mkdir(parents=True, exist_ok=True)
    crop_filename = f"{item_crop.id}.jpg"

    with Image.open(image_path) as img:
        cropped = img.crop((left, upper, right, lower)).convert("RGB")
        cropped.save(crop_dir / crop_filename, "JPEG", quality=85)

    return f"{evidence_file.id}/{crop_filename}"
