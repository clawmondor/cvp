"""Tests for vision_worker — recover, claim, idle-stop behavior."""

import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cvp.models_vision  # noqa: F401
from cvp.models import Base, EvidenceFile, Matter, VisionJob, VisionJobImage


@pytest.fixture(autouse=True)
def _stop_worker_after_test():
    """Ensure no worker thread leaks between tests regardless of execution order."""
    yield
    from cvp.services import vision_worker

    vision_worker.stop_worker()


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
    session.add(Matter(id="m1", policyholder_name="T", loss_type="total_loss"))
    session.add(
        EvidenceFile(
            id="ef1",
            matter_id="m1",
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


def _add_job_image(db, status="pending"):
    job = VisionJob(matter_id="m1", model_slug="some/model", status="running")
    db.add(job)
    db.flush()
    ji = VisionJobImage(job_id=job.id, evidence_file_id="ef1", status=status)
    db.add(ji)
    db.commit()
    return ji.id


def test_recover_stale_jobs_resets_running_to_pending(db, monkeypatch):
    from cvp.services import vision_worker

    monkeypatch.setattr("cvp.services.vision_worker.SessionLocal", lambda: db)

    ji_id = _add_job_image(db, status="running")

    vision_worker.recover_stale_jobs()

    db.expire_all()
    ji = db.get(VisionJobImage, ji_id)
    assert ji.status == "pending"
    assert ji.started_at is None


def test_recover_leaves_done_rows_unchanged(db, monkeypatch):
    from cvp.services import vision_worker

    monkeypatch.setattr("cvp.services.vision_worker.SessionLocal", lambda: db)

    ji_id = _add_job_image(db, status="done")
    vision_worker.recover_stale_jobs()

    db.expire_all()
    ji = db.get(VisionJobImage, ji_id)
    assert ji.status == "done"


def test_claim_next_pending_marks_running(db, monkeypatch):
    from cvp.services import vision_worker

    monkeypatch.setattr("cvp.services.vision_worker.SessionLocal", lambda: db)

    ji_id = _add_job_image(db, status="pending")
    claimed = vision_worker._claim_next_pending()

    assert claimed == ji_id
    db.expire_all()
    ji = db.get(VisionJobImage, ji_id)
    assert ji.status == "running"
    assert ji.started_at is not None


def test_claim_next_pending_returns_none_when_empty(db, monkeypatch):
    from cvp.services import vision_worker

    monkeypatch.setattr("cvp.services.vision_worker.SessionLocal", lambda: db)

    result = vision_worker._claim_next_pending()
    assert result is None


def test_worker_processes_pending_row(db, monkeypatch):
    from cvp.services import vision_worker

    monkeypatch.setattr("cvp.services.vision_worker.SessionLocal", lambda: db)

    processed = []

    def fake_process(job_image_id):
        ji = db.get(VisionJobImage, job_image_id)
        ji.status = "done"
        db.commit()
        processed.append(job_image_id)

    monkeypatch.setattr("cvp.services.vision_worker._process_fn", fake_process)
    monkeypatch.setattr("cvp.services.vision_worker._SLEEP_SECONDS", 0)

    ji_id = _add_job_image(db, status="pending")

    vision_worker.start_worker()
    vision_worker.wake()

    deadline = time.time() + 3.0
    while time.time() < deadline and ji_id not in processed:
        time.sleep(0.05)

    assert ji_id in processed
