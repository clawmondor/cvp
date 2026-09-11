"""Per-item AI recommendation runs: launch, status polling, and agent progress.

Three routes with two different principals. Launch and status are session-authed
specialist actions; progress is called by the Cloudflare container with an
X-API-Key. Auth is declared per route rather than per file.
"""

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session, selectinload

from cvp.agent_auth import AgentPrincipal, require_agent_key
from cvp.config import settings
from cvp.db import get_db
from cvp.dependencies import CurrentUser, require_matter_role
from cvp.models import Item
from cvp.models_agent import AgentRun
from cvp.services import agent_launch
from cvp.services.agent_models import resolve_model
from cvp.services.agent_run_sweeper import sweep_stale_runs
from cvp.services.recommendation_feed import MAX_PENDING_PER_ITEM, pending_count

BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.filters["cents"] = lambda c: f"${c / 100:,.2f}" if c else "$0.00"

router = APIRouter()

# Single module-level dependency instance so tests can override it by identity.
EDITOR = require_matter_role("editor")

AGENT_IMPL = "custom-python"

#: Every status a run may report. The progress endpoint validates against it.
_VALID_STATUSES = (
    "queued",
    "running",
    "searching",
    "submitting",
    "succeeded",
    "failed",
)

#: Statuses that mean a run still occupies the item. Derived rather than
#: hand-listed: "in flight" is exactly "not terminal", and spelling it out
#: twice is how the two drift apart.
IN_FLIGHT = tuple(s for s in _VALID_STATUSES if s not in AgentRun.TERMINAL)


def _load_item(db: Session, item_id: str) -> Item:
    item = (
        db.query(Item)
        .options(selectinload(Item.ai_recommendations))
        .filter(Item.id == item_id)
        .first()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


@router.post("/api/items/{item_id}/agent-runs", response_class=HTMLResponse)
def launch(
    request: Request,
    item_id: str,
    background_tasks: BackgroundTasks,
    model_slug: str | None = Query(default=None),
    user: CurrentUser = Depends(EDITOR),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Create a run and hand the outbound POST to a background task.

    Every guard runs before anything leaves Railway: a bad model, a duplicate
    click, or an item already at the pending cap must not cost a container
    start and an LLM call.
    """
    # Reap stranded runs before the in-flight guard reads them. The sweeper
    # otherwise only runs at process start, so a run whose container died
    # without reporting would block this item until the next redeploy. One
    # indexed query on a user-initiated action is a fair price for that.
    sweep_stale_runs(db, older_than_minutes=settings.agent_run_stale_minutes)

    item = _load_item(db, item_id)

    try:
        model = resolve_model(db, model_slug)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    in_flight = (
        db.query(AgentRun)
        .filter(AgentRun.item_id == item_id, AgentRun.status.in_(IN_FLIGHT))
        .first()
    )
    if in_flight is not None:
        raise HTTPException(status_code=409, detail="A recommendation run is already in progress.")

    if pending_count(db, item_id) >= MAX_PENDING_PER_ITEM:
        raise HTTPException(
            status_code=409,
            detail="This item already has the maximum number of pending recommendations.",
        )

    if not settings.cloudflare_agent_key_id:
        raise HTTPException(status_code=503, detail="No Cloudflare agent key is configured.")

    run = AgentRun(
        item_id=item.id,
        matter_id=item.matter_id,
        agent_impl=AGENT_IMPL,
        model_slug=model,
        agent_key_id=settings.cloudflare_agent_key_id,
        started_by_id=user.id,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    background_tasks.add_task(agent_launch.launch_run, run.id)

    return HTMLResponse(
        templates.get_template("_agent_run_status.html").render(
            request=request,
            run=run,
            item=item,
            recommendations=[],
            terminal=run.status in AgentRun.TERMINAL,
            # A fresh run is never terminal, so there is nothing to swap out
            # of band and no #ai-recs-<id> guaranteed on the page yet.
            oob=False,
        )
    )


class ProgressIn(BaseModel):
    """A progress report from the container. Terminal reports carry telemetry."""

    status: str
    message: str | None = None
    error: str | None = None
    agent_impl: str | None = None
    image_tag: str | None = None
    model_slug: str | None = None
    cost_micro_usd: int | None = Field(default=None, ge=0)
    latency_ms: int | None = Field(default=None, ge=0)
    browser_run_used: bool | None = None

    @field_validator("status")
    @classmethod
    def _known_status(cls, v: str) -> str:
        if v not in _VALID_STATUSES:
            raise ValueError(f"status must be one of {_VALID_STATUSES}")
        return v


@router.post("/api/agent/runs/{run_id}/progress")
def progress(
    run_id: str,
    body: ProgressIn,
    principal: AgentPrincipal = Depends(require_agent_key),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Record progress from the container.

    The run is bound to an agent key at creation, so this is a strict equality
    check — a valid key must not be able to write progress onto another
    principal's run.
    """
    run = db.get(AgentRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.agent_key_id != principal.agent_key_id:
        raise HTTPException(status_code=403, detail="Run belongs to another agent key")
    if run.status in AgentRun.TERMINAL:
        raise HTTPException(status_code=409, detail="Run has already finished")

    run.status = body.status
    if body.message is not None:
        run.status_message = body.message
    if body.error is not None:
        run.error = body.error
    # Telemetry is reported by the image, so it describes what actually ran.
    if body.image_tag is not None:
        run.image_tag = body.image_tag
    if body.agent_impl is not None:
        run.agent_impl = body.agent_impl
    if body.model_slug is not None:
        run.model_slug = body.model_slug
    if body.cost_micro_usd is not None:
        run.cost_micro_usd = body.cost_micro_usd
    if body.latency_ms is not None:
        run.latency_ms = body.latency_ms
    if body.browser_run_used is not None:
        run.browser_run_used = body.browser_run_used

    if body.status in AgentRun.TERMINAL:
        run.finished_at = datetime.now(tz=timezone.utc)

    db.commit()
    return {"status": run.status}


@router.get("/api/items/{item_id}/agent-runs/{run_id}", response_class=HTMLResponse)
def status(
    request: Request,
    item_id: str,
    run_id: str,
    user: CurrentUser = Depends(EDITOR),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Render the polling partial. Stops polling once the run is terminal."""
    item = _load_item(db, item_id)
    run = db.get(AgentRun, run_id)
    if run is None or run.item_id != item_id:
        raise HTTPException(status_code=404, detail="Run not found")

    recommendations = [r for r in item.ai_recommendations if r.status == "pending"]
    return HTMLResponse(
        templates.get_template("_agent_run_status.html").render(
            request=request,
            run=run,
            item=item,
            recommendations=recommendations,
            terminal=run.status in AgentRun.TERMINAL,
            # This partial is the whole response to a poll, so the OOB swap has
            # a live #ai-recs-<id> to land on.
            oob=True,
        )
    )
