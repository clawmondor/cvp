"""Cascade-delete helper for removing evidence files and their dependents."""

from pathlib import Path

from sqlalchemy.orm import Session

from cvp.models import EvidenceFile, Item, ItemCrop


def delete_evidence_file(
    db: Session,
    ef: EvidenceFile,
    upload_base: Path,
    crop_base: Path,
) -> None:
    """Delete an EvidenceFile and cascade to orphaned Items, ItemCrops, and disk files.

    Commits on completion. Safe to call in a loop — each call is its own transaction.
    """
    upload_base = upload_base.resolve()
    crop_base = crop_base.resolve()

    # Collect crop info before ORM deletes wipe the rows.
    crops = db.query(ItemCrop).filter_by(evidence_file_id=ef.id).all()

    # Items whose ONLY crop points at this file should be deleted.
    item_ids_to_delete: set[str] = set()
    for crop in crops:
        other_count = (
            db.query(ItemCrop)
            .filter(
                ItemCrop.item_id == crop.item_id,
                ItemCrop.evidence_file_id != ef.id,
            )
            .count()
        )
        if other_count == 0:
            item_ids_to_delete.add(crop.item_id)

    # Delete crop image files from disk.
    for crop in crops:
        if crop.crop_path:
            crop_file = (crop_base / crop.crop_path).resolve()
            if str(crop_file).startswith(str(crop_base)) and crop_file.exists():
                crop_file.unlink()

    # Delete evidence file from disk.
    dest = (upload_base / ef.stored_path).resolve()
    if str(dest).startswith(str(upload_base)) and dest.exists():
        dest.unlink()

    # ORM delete cascades to ItemCrop rows and VisionRun rows.
    db.delete(ef)
    db.flush()

    # Delete orphaned Item rows (crops already gone via cascade above).
    for item_id in item_ids_to_delete:
        item = db.get(Item, item_id)
        if item is not None:
            db.delete(item)

    db.commit()
