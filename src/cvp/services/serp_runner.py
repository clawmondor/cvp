"""Shared run-search / persist / render / audit helper for the SERP router.

Extracted out of `routers/serp.py` to keep that router under the project's
200-line-per-router ceiling. A `session_factory` callable is threaded through
rather than importing `SessionLocal` here directly, so callers (and their
tests) keep patching their own module's `SessionLocal` — this function still
opens exactly one session per call, it just doesn't own the reference to it.
"""

import json
from collections.abc import Callable

from fastapi import BackgroundTasks, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from cvp.dependencies import CurrentUser
from cvp.models import Item, ItemCrop, SerpSearch
from cvp.services.audit import get_client_ip, write_audit_log
from cvp.services.serp_display import extract_results

# Template variable prefix for each search service the crop panel can display.
_PANEL_SERVICES: tuple[tuple[str, str], ...] = (("google_lens", "lens"), ("firecrawl", "firecrawl"))


def latest_search_results_by_crop(
    db: Session, item: Item, service: str
) -> tuple[dict[str, SerpSearch | None], dict[str, list[dict]]]:
    """Look up each crop's most recent SerpSearch *for one service* and its display results.

    The `service` filter is load-bearing: a crop can carry runs from several
    services, and the panel keys each tab's state off its own service's row.
    """
    latest_by_crop: dict[str, SerpSearch | None] = {}
    display_by_crop: dict[str, list[dict]] = {}
    for crop in item.crops:
        latest = (
            db.query(SerpSearch)
            .filter(SerpSearch.item_crop_id == crop.id, SerpSearch.service == service)
            .order_by(SerpSearch.ran_at.desc())
            .first()
        )
        latest_by_crop[crop.id] = latest
        if latest and latest.response_json:
            response_dict = json.loads(latest.response_json)
            display_by_crop[crop.id] = extract_results(latest.service, response_dict, item.brand)
        else:
            display_by_crop[crop.id] = []
    return latest_by_crop, display_by_crop


def panel_context(db: Session, item: Item) -> dict[str, dict]:
    """Per-service latest-search maps for the crop panel and the inline edit row.

    Returns `latest_<prefix>_by_crop` / `display_<prefix>_by_crop` for every
    displayable service, so a template never has to guess which service a row
    came from.
    """
    context = empty_panel_context()
    for service, prefix in _PANEL_SERVICES:
        latest, display = latest_search_results_by_crop(db, item, service)
        context[f"latest_{prefix}_by_crop"] = latest
        context[f"display_{prefix}_by_crop"] = display
    return context


def empty_panel_context() -> dict[str, dict]:
    """The same key shape as `panel_context`, all empty — for renders that skip the lookup."""
    return {
        f"{kind}_{prefix}_by_crop": {}
        for _service, prefix in _PANEL_SERVICES
        for kind in ("latest", "display")
    }


def run_and_render(
    session_factory: Callable[[], Session],
    templates: Jinja2Templates,
    request: Request,
    background_tasks: BackgroundTasks,
    user: CurrentUser,
    item_id: str,
    crop_id: str,
    service: str,
    caller: Callable[[ItemCrop, Item | None], tuple[str, dict, dict, int]],
    image_url_fn: Callable[[ItemCrop], str] = lambda _crop: "",
) -> HTMLResponse:
    """Run a search, persist it, render the result partial, and audit.

    `caller` receives the loaded crop and item and returns the shared 4-tuple
    (request_url, params, response_dict, status_code). Both callables run
    inside this function's single session — do not open another.
    """
    db = session_factory()
    try:
        crop = db.get(ItemCrop, crop_id)
        if crop is None:
            raise HTTPException(status_code=404, detail="Crop not found")
        if crop.item_id != item_id:
            raise HTTPException(status_code=403, detail="Crop does not belong to this item")

        item = db.get(Item, item_id)
        request_url, params_dict, response_dict, status_code = caller(crop, item)

        search = SerpSearch(
            item_crop_id=crop.id,
            service=service,
            image_url=image_url_fn(crop),
            request_url=request_url,
            request_params=json.dumps(params_dict),
            response_json=json.dumps(response_dict),
            status_code=status_code,
        )
        db.add(search)
        db.commit()
        db.refresh(search)

        brand = item.brand if item else None
        display_results = extract_results(service, response_dict, brand)
        matter_id = item.matter_id if item else None

        html = templates.get_template("_serp_result.html").render(
            s=search, display_results=display_results, item_id=item_id
        )
    finally:
        db.close()

    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="serp.run",
        resource_type="item",
        resource_id=item_id,
        matter_id=matter_id,
        ip_address=get_client_ip(request),
    )
    return HTMLResponse(html)
