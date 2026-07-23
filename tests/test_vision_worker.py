"""Tests for vision_worker — recover, claim, idle-stop behavior."""

import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import claimos.models_vision  # noqa: F401
from claimos.models import Base, Claim, EvidenceFile, VisionJob, VisionJobImage


@pytest.fixture
def engine(tmp_path):
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def Session(engine):
    """Session factory — each call returns a fresh session on the test engine."""
    return sessionmaker(bind=engine)


@pytest.fixture
def db(engine, Session):
    session = Session()
    session.add(
        Claim(id="m1", policyholder_name="T", loss_type="total_loss", nickname="Test Claim")
    )
    session.add(
        EvidenceFile(
            id="ef1",
            claim_id="m1",
            filename="a.jpg",
            stored_path="/tmp/a.jpg",
            mime_type="image/jpeg",
            kind="image",
            size_bytes=1,
        )
    )
    session.commit()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def _isolate_worker(db):
    """Kill any running worker before and after each test.

    Depending on `db` ensures this fixture tears down BEFORE `db` closes,
    so the worker cannot race against session cleanup in teardown.
    """
    from claimos.services import vision_worker

    vision_worker.stop_worker()  # kill any stale worker from previous test
    yield
    vision_worker.stop_worker()  # kill worker started by this test


def _add_job_image(db, status="pending"):
    job = VisionJob(claim_id="m1", model_slug="some/model", status="running")
    db.add(job)
    db.flush()
    ji = VisionJobImage(job_id=job.id, evidence_file_id="ef1", status=status)
    db.add(ji)
    db.commit()
    return ji.id


def test_recover_stale_jobs_resets_running_to_pending(db, Session, monkeypatch):
    from claimos.services import vision_worker

    monkeypatch.setattr("claimos.services.vision_worker.SessionLocal", Session)

    ji_id = _add_job_image(db, status="running")

    vision_worker.recover_stale_jobs()

    db.expire_all()
    ji = db.get(VisionJobImage, ji_id)
    assert ji.status == "pending"
    assert ji.started_at is None


def test_recover_leaves_done_rows_unchanged(db, Session, monkeypatch):
    from claimos.services import vision_worker

    monkeypatch.setattr("claimos.services.vision_worker.SessionLocal", Session)

    ji_id = _add_job_image(db, status="done")
    vision_worker.recover_stale_jobs()

    db.expire_all()
    ji = db.get(VisionJobImage, ji_id)
    assert ji.status == "done"


def test_claim_next_pending_marks_running(db, Session, monkeypatch):
    from claimos.services import vision_worker

    monkeypatch.setattr("claimos.services.vision_worker.SessionLocal", Session)

    ji_id = _add_job_image(db, status="pending")
    claimed = vision_worker._claim_next_pending()

    assert claimed == ji_id
    db.expire_all()
    ji = db.get(VisionJobImage, ji_id)
    assert ji.status == "running"
    assert ji.started_at is not None


def test_claim_next_pending_returns_none_when_empty(db, Session, monkeypatch):
    from claimos.services import vision_worker

    monkeypatch.setattr("claimos.services.vision_worker.SessionLocal", Session)

    result = vision_worker._claim_next_pending()
    assert result is None


def test_worker_processes_pending_row(db, Session, monkeypatch):
    from claimos.services import vision_worker

    monkeypatch.setattr("claimos.services.vision_worker.SessionLocal", Session)

    processed = []

    def fake_process(job_image_id):
        ji = db.get(VisionJobImage, job_image_id)
        ji.status = "done"
        db.commit()
        processed.append(job_image_id)

    monkeypatch.setattr("claimos.services.vision_worker._process_fn", fake_process)
    monkeypatch.setattr("claimos.services.vision_worker._SLEEP_SECONDS", 0)

    ji_id = _add_job_image(db, status="pending")

    vision_worker.start_worker()
    vision_worker.wake()

    deadline = time.time() + 3.0
    while time.time() < deadline and ji_id not in processed:
        time.sleep(0.05)

    assert ji_id in processed


def test_region_bbox_property():
    from claimos.models import VisionJobImage

    none_set = VisionJobImage(job_id="j", evidence_file_id="ef1")
    assert none_set.region_bbox is None

    all_set = VisionJobImage(
        job_id="j",
        evidence_file_id="ef1",
        region_left=10,
        region_upper=20,
        region_right=110,
        region_lower=120,
    )
    assert all_set.region_bbox == (10, 20, 110, 120)

    partial = VisionJobImage(job_id="j", evidence_file_id="ef1", region_left=10)
    assert partial.region_bbox is None
