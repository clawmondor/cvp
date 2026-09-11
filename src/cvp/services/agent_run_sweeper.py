"""Reap agent runs whose container never reported a terminal status.

Storage on Cloudflare is ephemeral and logs live there, so CVP cannot ask a
dead container what happened — it can only notice that nothing arrived.
Mirrors `vision_worker.recover_stale_jobs()`.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from cvp.models_agent import AgentRun

logger = logging.getLogger(__name__)


def sweep_stale_runs(db: Session, *, older_than_minutes: int) -> int:
    """Mark non-terminal runs older than the cutoff as failed. Returns the count."""
    cutoff = datetime.now(tz=timezone.utc) - timedelta(minutes=older_than_minutes)
    stale = (
        db.query(AgentRun)
        .filter(AgentRun.status.notin_(tuple(AgentRun.TERMINAL)), AgentRun.created_at < cutoff)
        .all()
    )
    for run in stale:
        run.status = "failed"
        run.error = f"Agent run timed out after {older_than_minutes} minutes with no response."
        run.finished_at = datetime.now(tz=timezone.utc)
    if stale:
        db.commit()
        logger.info("agent_run_sweeper: reaped %d stale runs", len(stale))
    return len(stale)
