"""Tests for evidence_cleanup.delete_evidence_file cascade helper."""

import uuid

import pytest
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import claimos.models_vision  # noqa: F401
from claimos.models import Base, Category, Claim, EvidenceFile, Item, ItemCrop


@pytest.fixture
def db(tmp_path):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    session.add(Category(id=1, name="Misc", useful_life_years=8, acv_floor_pct=0.2))
    session.commit()
    yield session
    session.close()


@pytest.fixture
def claim(db):
    m = Claim(policyholder_name="Test", loss_type="total_loss")
    db.add(m)
    db.commit()
    return m


def _make_jpeg(path):
    Image.new("RGB", (10, 10), "white").save(path, "JPEG")


def test_delete_removes_evidence_file_from_disk(db, claim, tmp_path):
    from claimos.services.evidence_cleanup import delete_evidence_file

    img = tmp_path / "photo.jpg"
    _make_jpeg(img)
    ef = EvidenceFile(
        claim_id=claim.id,
        filename="photo.jpg",
        stored_path=img.name,
        mime_type="image/jpeg",
        kind="image",
        size_bytes=img.stat().st_size,
    )
    db.add(ef)
    db.commit()

    delete_evidence_file(db, ef, tmp_path, tmp_path)

    assert not img.exists()
    assert db.get(EvidenceFile, ef.id) is None


def test_delete_cascades_to_orphan_item_and_crop(db, claim, tmp_path):
    from claimos.services.evidence_cleanup import delete_evidence_file

    img = tmp_path / "photo2.jpg"
    _make_jpeg(img)
    ef = EvidenceFile(
        claim_id=claim.id,
        filename="photo2.jpg",
        stored_path=img.name,
        mime_type="image/jpeg",
        kind="image",
        size_bytes=img.stat().st_size,
    )
    db.add(ef)
    db.flush()

    item = Item(
        claim_id=claim.id,
        category_id=1,
        line_number=1,
        description="TV",
        quantity=1,
        age_years=0.0,
        condition="average",
        retail_unit_cents=0,
        rcv_total_cents=0,
        acv_total_cents=0,
        confirmed=False,
    )
    db.add(item)
    db.flush()

    crop_file = tmp_path / f"{ef.id}" / f"{str(uuid.uuid4())}.jpg"
    crop_file.parent.mkdir(parents=True, exist_ok=True)
    _make_jpeg(crop_file)

    crop = ItemCrop(
        id=str(uuid.uuid4()),
        item_id=item.id,
        evidence_file_id=ef.id,
        bbox_left=0,
        bbox_upper=0,
        bbox_right=5,
        bbox_lower=5,
        crop_path=str(crop_file.relative_to(tmp_path)),
    )
    db.add(crop)
    db.commit()

    delete_evidence_file(db, ef, tmp_path, tmp_path)

    assert db.get(Item, item.id) is None
    assert db.get(ItemCrop, crop.id) is None
    assert not crop_file.exists()


def test_delete_keeps_item_with_crop_from_other_file(db, claim, tmp_path):

    from claimos.services.evidence_cleanup import delete_evidence_file

    img1 = tmp_path / "photo_a.jpg"
    img2 = tmp_path / "photo_b.jpg"
    _make_jpeg(img1)
    _make_jpeg(img2)

    ef1 = EvidenceFile(
        claim_id=claim.id,
        filename="photo_a.jpg",
        stored_path=img1.name,
        mime_type="image/jpeg",
        kind="image",
        size_bytes=1,
    )
    ef2 = EvidenceFile(
        claim_id=claim.id,
        filename="photo_b.jpg",
        stored_path=img2.name,
        mime_type="image/jpeg",
        kind="image",
        size_bytes=1,
    )
    db.add_all([ef1, ef2])
    db.flush()

    item = Item(
        claim_id=claim.id,
        category_id=1,
        line_number=1,
        description="Sofa",
        quantity=1,
        age_years=0.0,
        condition="average",
        retail_unit_cents=0,
        rcv_total_cents=0,
        acv_total_cents=0,
        confirmed=False,
    )
    db.add(item)
    db.flush()

    crop1 = ItemCrop(
        id=str(uuid.uuid4()),
        item_id=item.id,
        evidence_file_id=ef1.id,
        bbox_left=0,
        bbox_upper=0,
        bbox_right=5,
        bbox_lower=5,
        crop_path="",
    )
    crop2 = ItemCrop(
        id=str(uuid.uuid4()),
        item_id=item.id,
        evidence_file_id=ef2.id,
        bbox_left=0,
        bbox_upper=0,
        bbox_right=5,
        bbox_lower=5,
        crop_path="",
    )
    db.add_all([crop1, crop2])
    db.commit()

    delete_evidence_file(db, ef1, tmp_path, tmp_path)

    # Item still exists — it has a crop from ef2
    assert db.get(Item, item.id) is not None
    # crop1 gone, crop2 remains
    assert db.get(ItemCrop, crop1.id) is None
    assert db.get(ItemCrop, crop2.id) is not None
