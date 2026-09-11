"""Per-item AI recommendation runs: launch, status polling, and agent progress.

Three routes with two different principals. Launch and status are session-authed
specialist actions; progress is called by the Cloudflare container with an
X-API-Key. Auth is declared per route rather than per file.
"""

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, selectinload

from cvp.config import settings
from cvp.db import get_db
from cvp.dependencies import CurrentUser, require_matter_role
from cvp.models import Item
from cvp.models_agent import AgentRun
from cvp.services import agent_launch
from cvp.services.agent_models import resolve_model
from cvp.services.recommendation_feed import MAX_PENDING_PER_ITEM, pending_count

BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.filters["cents"] = lambda c: f"${c / 100:,.2f}" if c else "$0.00"

router = APIRouter()

# Single module-level dependency instance so tests can override it by identity.
EDITOR = require_matter_role("editor")

AGENT_IMPL = "custom-python"

#: Statuses that mean a run still occupies the item.
IN_FLIGHT = ("queued", "running", "searching", "submitting")


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
            request=request, run=run, item=item, recommendations=[]
        )
    )
