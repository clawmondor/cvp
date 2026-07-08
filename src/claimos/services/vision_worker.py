"""Single-threaded vision scan worker. Idles via threading.Event; zero CPU when empty."""

import logging
import threading
import time
from datetime import datetime, timezone

from claimos.db import SessionLocal
from claimos.models import VisionJobImage

logger = logging.getLogger(__name__)

_wake = threading.Event()
_stop = threading.Event()
_thread: threading.Thread | None = None
_lock = threading.Lock()

_SLEEP_SECONDS: float = 0.5  # overridable in tests


def _process_fn(job_image_id: str) -> None:
    """Default process function — swappable in tests via monkeypatch."""
    from claimos.services.vision import process_one_image

    process_one_image(job_image_id)


def wake() -> None:
    """Signal the worker that new work is available."""
    _wake.set()


def recover_stale_jobs() -> None:
    """On startup, reset any rows stuck in 'running' (from a prior crash) to 'pending'."""
    db = SessionLocal()
    try:
        count = (
            db.query(VisionJobImage)
            .filter_by(status="running")
            .update({"status": "pending", "started_at": None})
        )
        db.commit()
        if count > 0:
            logger.info("vision_worker: reset %d stale running rows to pending", count)
    finally:
        db.close()
    wake()


def _claim_next_pending() -> str | None:
    """Atomically claim the oldest pending row; return its ID or None."""
    db = SessionLocal()
    try:
        row = (
            db.query(VisionJobImage)
            .filter_by(status="pending")
            .order_by(VisionJobImage.created_at)
            .first()
        )
        if row is None:
            return None
        row.status = "running"
        row.started_at = datetime.now(timezone.utc)
        db.commit()
        return row.id
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def stop_worker() -> None:
    """Stop the background worker thread and reset module state. Used in tests."""
    global _thread
    _stop.set()
    _wake.set()  # unblock any _wake.wait() so the thread sees _stop
    t = None
    with _lock:
        t, _thread = _thread, None
    if t is not None:
        t.join(timeout=2.0)
    _stop.clear()
    _wake.clear()


def _loop() -> None:
    while not _stop.is_set():
        try:
            job_image_id = _claim_next_pending()
            if job_image_id is None:
                _wake.clear()
                # Re-check after clearing to avoid missing a signal set between the
                # initial claim attempt and the clear.
                job_image_id = _claim_next_pending()
                if job_image_id is None:
                    _wake.wait()
                    continue
            _process_fn(job_image_id)
        except Exception:
            logger.exception("vision_worker: unexpected error in loop")
            time.sleep(1.0)
            continue
        time.sleep(_SLEEP_SECONDS)


def start_worker() -> None:
    """Start the background worker thread if not already running."""
    global _thread
    with _lock:
        if _thread is not None and _thread.is_alive():
            return
        _thread = threading.Thread(target=_loop, daemon=True, name="vision-worker")
        _thread.start()
