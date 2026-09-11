"""Launching a Cloudflare agent run: signing, payload, and the outbound POST.

The Worker is world-reachable, so a forged launch would spend real money
against a capped OpenRouter key. Requests are HMAC-signed over
"<timestamp>.<body>" and the Worker enforces a freshness window.
"""

import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timezone

import httpx

from cvp.config import settings
from cvp.db import SessionLocal
from cvp.models_agent import AgentRun

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 10.0


def sign_payload(secret: str, timestamp: str, body: str) -> str:
    """Return "v1=<hex>" for HMAC-SHA256 over "<timestamp>.<body>".

    The Cloudflare Worker implements the identical computation; the fixed
    vector in tests/test_agent_launch_signing.py is the shared contract.
    """
    mac = hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}.{body}".encode("utf-8"),
        hashlib.sha256,
    )
    return f"v1={mac.hexdigest()}"


def launch_run(run_id: str) -> None:
    """POST the launch to the Cloudflare Worker and transition the run.

    Runs in a BackgroundTask with no caller to observe a raised exception, so
    this function must never raise. Every failure — including one we did not
    anticipate — is recorded on the run row (best-effort) where the UI can
    show it, and logged either way so it stays diagnosable.
    """
    db = SessionLocal()
    run: AgentRun | None = None
    try:
        try:
            run = db.get(AgentRun, run_id)
            if run is None:
                logger.warning("launch_run: no such run %s", run_id)
                return

            if not settings.cloudflare_agent_worker_url:
                _fail(db, run, "Cloudflare agent worker is not configured.")
                return

            body = json.dumps(
                {
                    "run_id": run.id,
                    "matter_id": run.matter_id,
                    "item_id": run.item_id,
                    "model_slug": run.model_slug,
                    "agent_impl": run.agent_impl,
                },
                separators=(",", ":"),
                sort_keys=True,
            )
            timestamp = str(int(time.time()))
            headers = {
                "Content-Type": "application/json",
                "X-CVP-Timestamp": timestamp,
                "X-CVP-Signature": sign_payload(
                    settings.cloudflare_launch_hmac_secret, timestamp, body
                ),
            }
            url = f"{settings.cloudflare_agent_worker_url.rstrip('/')}/runs"

            try:
                with httpx.Client(timeout=_TIMEOUT_SECONDS) as client:
                    response = client.post(url, content=body, headers=headers)
            except Exception as exc:  # noqa: BLE001
                logger.exception("launch_run: transport failure for %s", run_id)
                _fail(db, run, f"Could not reach the agent worker: {exc}")
                return

            if response.status_code >= 300:
                _fail(db, run, f"Worker returned {response.status_code}: {response.text[:200]}")
                return

            run.status = "running"
            run.started_at = datetime.now(tz=timezone.utc)
            db.commit()
        except Exception as exc:  # noqa: BLE001
            # Catch-all: nothing above this point may escape launch_run, since
            # it runs in a BackgroundTask with no caller to observe it. This
            # also backstops a broken _fail() commit — the exception it would
            # raise is caught here too, so launch_run still returns normally.
            logger.exception("launch_run: unexpected failure for run %s", run_id)
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                logger.exception("launch_run: rollback after unexpected failure also failed")

            target = run
            if target is None:
                try:
                    target = db.get(AgentRun, run_id)
                except Exception:  # noqa: BLE001
                    target = None
            if target is not None:
                _fail(db, target, f"Unexpected error launching the agent run: {exc}")
    finally:
        db.close()


def _fail(db, run: AgentRun, message: str) -> None:
    """Mark the run failed. Must never raise — if even this commit fails, we
    degrade to a log line rather than let the exception reach launch_run's
    caller."""
    try:
        run.status = "failed"
        run.error = message
        run.finished_at = datetime.now(tz=timezone.utc)
        db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("launch_run: could not record failure on the run row")
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            logger.exception("launch_run: rollback after failed _fail commit also failed")
