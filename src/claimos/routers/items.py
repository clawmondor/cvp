"""Item CRUD endpoints with ACV auto-computation."""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func
from sqlalchemy.orm import selectinload

from claimos.config import settings
from claimos.db import SessionLocal
from claimos.dependencies import CurrentUser, _check_claim_access, require_claim_role
from claimos.depreciation import compute_acv
from claimos.models import Category, Item, ItemGroup, Room, SerpSearch
from claimos.services.audit import get_client_ip, write_audit_log
from claimos.services.item_groups import find_or_create
from claimos.services.pagination import paginate_by_cursor
from claimos.services.serp_display import extract_results
from claimos.templating import templates

router = APIRouter()

CONDITIONS = ["excellent", "above_average", "average", "below_average"]
ITEMS_PAGE_SIZE = 50


def _get_context(claim_id: str, db):
    categories = db.query(Category).order_by(Category.id).all()
    rooms = db.query(Room).filter(Room.claim_id == claim_id).order_by(Room.sort_order).all()
    item_groups = (
        db.query(ItemGroup)
        .filter(ItemGroup.claim_id == claim_id)
        .order_by(ItemGroup.created_at)
        .all()
    )
    return categories, rooms, item_groups


def compute_items_totals(claim_id: str, db) -> dict[str, int]:
    """Money + count totals for a claim's items.

    Money totals (RCV/ACV) count only rows that are confirmed and not
    excluded. Counts are integer cents — never floats.
    """
    rows = (
        db.query(
            Item.confirmed,
            Item.excluded,
            Item.rcv_total_cents,
            Item.acv_total_cents,
            Item.retail_unit_cents,
        )
        .filter(Item.claim_id == claim_id)
        .all()
    )
    confirmed_rows = [r for r in rows if r.confirmed and not r.excluded]
    return {
        "items_total_count": len(rows),
        "items_confirmed_count": len(confirmed_rows),
        "items_rcv_total_cents": sum(r.rcv_total_cents for r in confirmed_rows),
        "items_acv_total_cents": sum(r.acv_total_cents for r in confirmed_rows),
        "unconfirmed_count": sum(1 for r in rows if not r.confirmed),
        "missing_price_count": sum(1 for r in confirmed_rows if r.retail_unit_cents == 0),
    }


def _compute_and_set_totals(item: Item, cat: Category) -> None:
    item.rcv_total_cents = item.retail_unit_cents * item.quantity
    item.acv_total_cents = compute_acv(
        retail_unit_cents=item.retail_unit_cents,
        quantity=item.quantity,
        age_years=item.age_years,
        useful_life_years=cat.useful_life_years,
        acv_floor_pct=cat.acv_floor_pct,
        condition=item.condition,
        acv_override_cents=item.acv_override_cents,
    )


def _item_row_html(
    item: Item, categories: list, rooms: list, item_groups: list, can_approve: bool = False
) -> str:
    return templates.get_template("_item_row.html").render(
        item=item,
        categories=categories,
        rooms=rooms,
        item_groups=item_groups,
        can_approve=can_approve,
    )


def _item_row_edit_html(
    item: Item,
    categories: list,
    rooms: list,
    item_groups: list,
    latest_by_crop: dict | None = None,
    display_by_crop: dict | None = None,
) -> str:
    return templates.get_template("_item_row_edit.html").render(
        item=item,
        categories=categories,
        rooms=rooms,
        item_groups=item_groups,
        conditions=CONDITIONS,
        public_base_url=settings.public_base_url,
        latest_by_crop=latest_by_crop or {},
        display_by_crop=display_by_crop or {},
    )


def _resolve_item_group_id(
    db,
    claim_id: str,
    item_group_id: str,
    new_item_group_name: str,
) -> str | None:
    """Apply the item-group form fields to a candidate ``item_group_id`` value.

    ``new_item_group_name`` wins over ``item_group_id`` (explicit create beats
    select). Returns ``None`` when both are empty (clear / leave unset). Raises
    HTTPException(400) when ``item_group_id`` refers to a group in another claim.
    """
    if new_item_group_name.strip():
        ig = find_or_create(db, claim_id, new_item_group_name)
        return ig.id
    if item_group_id:
        ig = db.get(ItemGroup, item_group_id)
        if ig is None or ig.claim_id != claim_id:
            raise HTTPException(status_code=400, detail="Group not in claim")
        return ig.id
    return None


def _parse_cents(dollars_str: str) -> int:
    try:
        return round(float(dollars_str or 0) * 100)
    except ValueError:
        return 0


@router.get("/api/claims/{claim_id}/items-rows", response_class=HTMLResponse)
def get_items_rows(
    request: Request,
    claim_id: str,
    cursor: str = "",
    user: CurrentUser = Depends(require_claim_role("viewer", "items")),
) -> HTMLResponse:
    """Render one cursor-paginated page of item `<tr>` rows + sentinel.

    `cursor` is the line_number of the last row from the previous page
    (empty string for the first page). Rows are ordered by `line_number` ASC.
    """
    cursor_int = int(cursor) if cursor else None
    db = SessionLocal()
    try:
        rows, next_cursor = paginate_by_cursor(
            db.query(Item).options(selectinload(Item.crops)).filter(Item.claim_id == claim_id),
            cursor_col=Item.line_number,
            cursor_value=cursor_int,
            limit=ITEMS_PAGE_SIZE,
            order="asc",
        )
        categories, room_objs, _groups = _get_context(claim_id, db)
        can_approve = _check_claim_access(db, user, claim_id, "approver", "items")
    finally:
        db.close()
    return HTMLResponse(
        templates.get_template("_items_rows_fragment.html").render(
            items=rows,
            items_next_cursor=next_cursor,
            claim_id=claim_id,
            categories=categories,
            rooms=room_objs,
            can_approve=can_approve,
        )
    )


@router.get("/api/claims/{claim_id}/items-summary", response_class=HTMLResponse)
def get_items_summary(
    claim_id: str,
    user: CurrentUser = Depends(require_claim_role("viewer", "items")),
) -> HTMLResponse:
    """Render the Confirmed / RCV total / ACV total summary block."""
    db = SessionLocal()
    try:
        totals = compute_items_totals(claim_id, db)
    finally:
        db.close()
    return HTMLResponse(
        templates.get_template("_items_summary.html").render(claim_id=claim_id, **totals)
    )


@router.post("/api/claims/{claim_id}/items", response_class=HTMLResponse)
def create_item(
    request: Request,
    claim_id: str,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_claim_role("contributor", "items")),
    description: str = Form(""),
    category_id: int = Form(...),
    room_id: str = Form(""),
    quantity: int = Form(1),
    age_years: float = Form(0.0),
    condition: str = Form("average"),
    rcv_unit_dollars: str = Form("0"),
    brand: str = Form(""),
    model_num: str = Form(""),
    notes: str = Form(""),
    item_group_id: str = Form(""),
    new_item_group_name: str = Form(""),
) -> HTMLResponse:
    db = SessionLocal()
    try:
        cat = db.get(Category, category_id)
        if cat is None:
            raise HTTPException(status_code=400, detail="Invalid category")

        max_line = (
            db.query(func.max(Item.line_number)).filter(Item.claim_id == claim_id).scalar() or 0
        )
        item = Item(
            claim_id=claim_id,
            category_id=category_id,
            room_id=room_id or None,
            line_number=max_line + 1,
            description=description.strip(),
            brand=brand.strip() or None,
            model=model_num.strip() or None,
            quantity=max(1, quantity),
            age_years=max(0.0, age_years),
            condition=condition,
            retail_unit_cents=_parse_cents(rcv_unit_dollars),
            notes=notes.strip(),
            confirmed=True,  # manually entered items start confirmed; Vision drafts use False
        )
        item.item_group_id = _resolve_item_group_id(
            db, claim_id, item_group_id, new_item_group_name
        )
        _compute_and_set_totals(item, cat)
        db.add(item)
        db.commit()
        db.refresh(item)
        item_id = item.id
        categories, rooms, item_groups = _get_context(claim_id, db)
        can_approve = _check_claim_access(db, user, claim_id, "approver", "items")
        row_html = _item_row_html(item, categories, rooms, item_groups, can_approve)
        # Remove the empty-state placeholder if it's present; HTMX silently
        # no-ops when the target element isn't in the DOM.
        oob_clear_empty = '<tr id="items-empty-row" hx-swap-oob="delete"></tr>'
        row_html = row_html + oob_clear_empty
    finally:
        db.close()
    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="item.create",
        resource_type="item",
        resource_id=item_id,
        claim_id=claim_id,
        ip_address=get_client_ip(request),
    )
    # Use HX-Trigger to nudge the client to refresh totals + drop empty-state row.
    headers = {"HX-Trigger": "item-created"}
    return HTMLResponse(row_html, headers=headers, status_code=200)


@router.get("/api/items/{item_id}/edit", response_class=HTMLResponse)
def item_edit_form(
    item_id: str, user: CurrentUser = Depends(require_claim_role("editor", "items"))
) -> HTMLResponse:
    db = SessionLocal()
    try:
        item = db.query(Item).options(selectinload(Item.crops)).filter(Item.id == item_id).first()
        if item is None:
            raise HTTPException(status_code=404)
        categories, rooms, item_groups = _get_context(item.claim_id, db)

        latest_by_crop: dict = {}
        display_by_crop: dict = {}
        for crop in item.crops:
            latest = (
                db.query(SerpSearch)
                .filter(SerpSearch.item_crop_id == crop.id)
                .order_by(SerpSearch.ran_at.desc())
                .first()
            )
            latest_by_crop[crop.id] = latest
            if latest and latest.response_json:
                display_by_crop[crop.id] = extract_results(
                    latest.service, json.loads(latest.response_json)
                )
            else:
                display_by_crop[crop.id] = []

        html = _item_row_edit_html(
            item, categories, rooms, item_groups, latest_by_crop, display_by_crop
        )
    finally:
        db.close()
    return HTMLResponse(html)


@router.get("/api/items/{item_id}/view", response_class=HTMLResponse)
def item_view_row(
    item_id: str, user: CurrentUser = Depends(require_claim_role("viewer", "items"))
) -> HTMLResponse:
    db = SessionLocal()
    try:
        item = db.query(Item).options(selectinload(Item.crops)).filter(Item.id == item_id).first()
        if item is None:
            raise HTTPException(status_code=404)
        categories, rooms, item_groups = _get_context(item.claim_id, db)
        can_approve = _check_claim_access(db, user, item.claim_id, "approver", "items")
        html = _item_row_html(item, categories, rooms, item_groups, can_approve)
    finally:
        db.close()
    return HTMLResponse(html)


@router.patch("/api/items/{item_id}", response_class=HTMLResponse)
def update_item(
    request: Request,
    item_id: str,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_claim_role("editor", "items")),
    description: str = Form(""),
    category_id: int = Form(...),
    room_id: str = Form(""),
    quantity: int = Form(1),
    age_years: float = Form(0.0),
    condition: str = Form("average"),
    rcv_unit_dollars: str = Form("0"),
    brand: str = Form(""),
    model_num: str = Form(""),
    notes: str = Form(""),
    source_retailer: str = Form(""),
    source_url: str = Form(""),
    match_type: str = Form("exact"),
    acv_override_dollars: str = Form(""),
    acv_override_reason: str = Form(""),
    item_group_id: str = Form(""),
    new_item_group_name: str = Form(""),
) -> HTMLResponse:
    db = SessionLocal()
    try:
        item = db.query(Item).options(selectinload(Item.crops)).filter(Item.id == item_id).first()
        if item is None:
            raise HTTPException(status_code=404)
        cat = db.get(Category, category_id)
        if cat is None:
            raise HTTPException(status_code=400, detail="Invalid category")

        item.description = description.strip()
        item.category_id = category_id
        item.room_id = room_id or None
        item.quantity = max(1, quantity)
        item.age_years = max(0.0, age_years)
        item.condition = condition
        item.retail_unit_cents = _parse_cents(rcv_unit_dollars)
        item.brand = brand.strip() or None
        item.model = model_num.strip() or None
        item.notes = notes.strip()
        item.source_retailer = source_retailer.strip()
        item.source_url = source_url.strip()
        item.match_type = match_type

        if acv_override_dollars.strip() and acv_override_reason.strip():
            item.acv_override_cents = _parse_cents(acv_override_dollars)
            item.acv_override_reason = acv_override_reason.strip()
        else:
            item.acv_override_cents = None
            item.acv_override_reason = None

        item.item_group_id = _resolve_item_group_id(
            db, item.claim_id, item_group_id, new_item_group_name
        )

        _compute_and_set_totals(item, cat)
        db.commit()
        db.refresh(item)
        claim_id = item.claim_id
        categories, rooms, item_groups = _get_context(claim_id, db)
        can_approve = _check_claim_access(db, user, claim_id, "approver", "items")
        html = _item_row_html(item, categories, rooms, item_groups, can_approve)
    finally:
        db.close()
    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="item.update",
        resource_type="item",
        resource_id=item_id,
        claim_id=claim_id,
        ip_address=get_client_ip(request),
    )
    return HTMLResponse(html)


@router.post("/api/items/{item_id}/confirm", response_class=HTMLResponse)
def confirm_item(
    request: Request,
    item_id: str,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_claim_role("approver", "items")),
) -> HTMLResponse:
    return _set_item_confirmed(item_id, True, user, request, background_tasks)


@router.post("/api/items/{item_id}/unconfirm", response_class=HTMLResponse)
def unconfirm_item(
    request: Request,
    item_id: str,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_claim_role("approver", "items")),
) -> HTMLResponse:
    return _set_item_confirmed(item_id, False, user, request, background_tasks)


def _set_item_confirmed(
    item_id: str,
    value: bool,
    user: CurrentUser,
    request: Request,
    background_tasks: BackgroundTasks,
) -> HTMLResponse:
    db = SessionLocal()
    try:
        item = db.query(Item).options(selectinload(Item.crops)).filter(Item.id == item_id).first()
        if item is None:
            raise HTTPException(status_code=404)
        item.confirmed = value
        item.confirmed_by_id = user.id if value else None
        item.confirmed_at = datetime.now(timezone.utc) if value else None
        db.commit()
        db.refresh(item)
        claim_id = item.claim_id
        categories, rooms, item_groups = _get_context(item.claim_id, db)
        can_approve = _check_claim_access(db, user, item.claim_id, "approver", "items")
        html = _item_row_html(item, categories, rooms, item_groups, can_approve)
    finally:
        db.close()
    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="item.confirm" if value else "item.unconfirm",
        resource_type="item",
        resource_id=item_id,
        claim_id=claim_id,
        ip_address=get_client_ip(request),
    )
    return HTMLResponse(html)


@router.post("/api/items/{item_id}/toggle-exclude", response_class=HTMLResponse)
def toggle_exclude(
    request: Request,
    item_id: str,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_claim_role("manager", "items")),
) -> HTMLResponse:
    db = SessionLocal()
    try:
        item = db.query(Item).options(selectinload(Item.crops)).filter(Item.id == item_id).first()
        if item is None:
            raise HTTPException(status_code=404)
        item.excluded = not item.excluded
        db.commit()
        db.refresh(item)
        claim_id = item.claim_id
        categories, rooms, item_groups = _get_context(claim_id, db)
        can_approve = _check_claim_access(db, user, claim_id, "approver", "items")
        html = _item_row_html(item, categories, rooms, item_groups, can_approve)
    finally:
        db.close()
    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="item.update",
        resource_type="item",
        resource_id=item_id,
        claim_id=claim_id,
        ip_address=get_client_ip(request),
    )
    return HTMLResponse(html)


@router.delete("/api/items/{item_id}", response_class=HTMLResponse)
def delete_item(
    request: Request,
    item_id: str,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_claim_role("manager", "items")),
) -> HTMLResponse:
    db = SessionLocal()
    try:
        item = db.get(Item, item_id)
        if item is None:
            raise HTTPException(status_code=404)
        claim_id = item.claim_id
        db.delete(item)
        db.commit()
    finally:
        db.close()
    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="item.delete",
        resource_type="item",
        resource_id=item_id,
        claim_id=claim_id,
        ip_address=get_client_ip(request),
    )
    return HTMLResponse("", status_code=200)
