"""Item CRUD endpoints with ACV auto-computation."""

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus, urlencode

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import case, func, or_
from sqlalchemy.orm import Query, Session, selectinload

from cvp.config import settings
from cvp.db import SessionLocal
from cvp.dependencies import CurrentUser, require_matter_role
from cvp.depreciation import compute_acv
from cvp.models import Category, Item, ItemGroup, Room, SerpSearch
from cvp.services.audit import get_client_ip, write_audit_log
from cvp.services.item_groups import find_or_create
from cvp.services.serp_display import extract_results

BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.filters["cents"] = lambda c: f"${c / 100:,.2f}" if c else "$0.00"
templates.env.filters["qplus"] = quote_plus
templates.env.filters["pretty_json"] = lambda v: json.dumps(json.loads(v), indent=2) if v else ""

router = APIRouter()

CONDITIONS = ["excellent", "above_average", "average", "below_average"]
ITEMS_PAGE_SIZE = 50

SORTABLE_KEYS = [
    "line",
    "description",
    "room",
    "category",
    "qty",
    "age",
    "condition",
    "rcv_unit",
    "rcv_total",
    "acv_total",
    "status",
]

_SIMPLE_SORT_COLUMNS = {
    "line": Item.line_number,
    "description": Item.description,
    "qty": Item.quantity,
    "age": Item.age_years,
    "rcv_unit": Item.retail_unit_cents,
    "rcv_total": Item.rcv_total_cents,
    "acv_total": Item.acv_total_cents,
}

_CONDITION_RANK = case(
    {"excellent": 0, "above_average": 1, "average": 2, "below_average": 3},
    value=Item.condition,
    else_=99,
)

_STATUS_VALUES = {"all", "unconfirmed", "confirmed", "excluded", "missing_price", "needs_review"}


@dataclass
class ItemFilters:
    room_id: str = ""
    category_id: str = ""
    status: str = "all"
    q: str = ""
    sort: str = "line"
    dir: str = "asc"


def _parse_item_filters(request: Request) -> ItemFilters:
    p = request.query_params
    sort = p.get("sort", "line")
    if sort not in SORTABLE_KEYS:
        sort = "line"
        direction = "asc"
    else:
        direction = p.get("dir", "asc")
        if direction not in ("asc", "desc"):
            direction = "asc"
    status = p.get("status", "all")
    if status not in _STATUS_VALUES:
        status = "all"
    return ItemFilters(
        room_id=p.get("room_id", "").strip(),
        category_id=p.get("category_id", "").strip(),
        status=status,
        q=p.get("q", "").strip(),
        sort=sort,
        dir=direction,
    )


def _apply_item_filters(query: Query, f: ItemFilters) -> Query:
    if f.room_id == "__unassigned__":
        query = query.filter(Item.room_id.is_(None))
    elif f.room_id:
        query = query.filter(Item.room_id == f.room_id)
    if f.category_id:
        try:
            query = query.filter(Item.category_id == int(f.category_id))
        except ValueError:
            pass
    if f.status == "unconfirmed":
        query = query.filter(Item.confirmed.is_(False))
    elif f.status == "confirmed":
        query = query.filter(Item.confirmed.is_(True))
    elif f.status == "excluded":
        query = query.filter(Item.excluded.is_(True))
    elif f.status == "missing_price":
        query = query.filter(
            Item.confirmed.is_(True),
            Item.excluded.is_(False),
            Item.retail_unit_cents == 0,
        )
    elif f.status == "needs_review":
        query = query.filter(Item.needs_review.is_(True))
    if f.q:
        like = f"%{f.q}%"
        query = query.filter(
            or_(
                Item.description.ilike(like),
                Item.brand.ilike(like),
                Item.model.ilike(like),
            )
        )
    return query


def _apply_item_sort(query: Query, f: ItemFilters) -> Query:
    descending = f.dir == "desc"

    def d(expr):
        return expr.desc() if descending else expr.asc()

    if f.sort == "room":
        query = query.outerjoin(Room, Item.room_id == Room.id).order_by(d(Room.name), Item.id.asc())
    elif f.sort == "category":
        query = query.join(Category, Item.category_id == Category.id).order_by(
            d(Category.name), Item.id.asc()
        )
    elif f.sort == "condition":
        query = query.order_by(d(_CONDITION_RANK), Item.id.asc())
    elif f.sort == "status":
        query = query.order_by(d(Item.excluded), d(Item.confirmed), Item.id.asc())
    else:
        col = _SIMPLE_SORT_COLUMNS.get(f.sort, Item.line_number)
        query = query.order_by(d(col), Item.id.asc())
    return query


def _build_items_query(db: Session, matter_id: str, f: ItemFilters) -> Query:
    query = db.query(Item).options(selectinload(Item.crops)).filter(Item.matter_id == matter_id)
    query = _apply_item_filters(query, f)
    query = _apply_item_sort(query, f)
    return query


def _count_items(db: Session, matter_id: str, f: ItemFilters) -> int:
    query = db.query(Item).filter(Item.matter_id == matter_id)
    query = _apply_item_filters(query, f)
    return query.count()


def items_query_string(
    f: ItemFilters, *, sort: str | None = None, direction: str | None = None
) -> str:
    """Build a querystring for filters + sort, omitting defaults.

    ``sort``/``direction`` override the filter's own values (used to build
    per-column header links). The default sort (``line`` asc) is omitted so a
    reset view has an empty querystring.
    """
    params: dict[str, str] = {}
    if f.room_id:
        params["room_id"] = f.room_id
    if f.category_id:
        params["category_id"] = f.category_id
    if f.status and f.status != "all":
        params["status"] = f.status
    if f.q:
        params["q"] = f.q
    s = f.sort if sort is None else sort
    dirn = f.dir if direction is None else direction
    if s != "line" or dirn != "asc":
        params["sort"] = s
        params["dir"] = dirn
    return urlencode(params)


def _sort_state(f: ItemFilters, col: str) -> tuple[str, str]:
    """Return ``(querystring, indicator)`` for a sortable header link.

    Clicking the active column flips direction; any other column starts asc.
    Indicator is ▲ (asc active) / ▼ (desc active) / "" (inactive).
    """
    if f.sort == col:
        next_dir = "desc" if f.dir == "asc" else "asc"
        indicator = "▲" if f.dir == "asc" else "▼"
    else:
        next_dir = "asc"
        indicator = ""
    return items_query_string(f, sort=col, direction=next_dir), indicator


def _get_context(matter_id: str, db):
    categories = db.query(Category).order_by(Category.id).all()
    rooms = db.query(Room).filter(Room.matter_id == matter_id).order_by(Room.sort_order).all()
    item_groups = (
        db.query(ItemGroup)
        .filter(ItemGroup.matter_id == matter_id)
        .order_by(ItemGroup.created_at)
        .all()
    )
    return categories, rooms, item_groups


def compute_items_totals(matter_id: str, db) -> dict[str, int]:
    """Money + count totals for a matter's items.

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
        .filter(Item.matter_id == matter_id)
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
    item.rcv_total_cents = item.retail_unit_cents * item.quantity + item.shipping_cents
    item.acv_total_cents = compute_acv(
        retail_unit_cents=item.retail_unit_cents,
        quantity=item.quantity,
        age_years=item.age_years,
        useful_life_years=cat.useful_life_years,
        acv_floor_pct=cat.acv_floor_pct,
        condition=item.condition,
        acv_override_cents=item.acv_override_cents,
        shipping_cents=item.shipping_cents,
    )


def _item_row_html(item: Item, categories: list, rooms: list, item_groups: list) -> str:
    return templates.get_template("_item_row.html").render(
        item=item, categories=categories, rooms=rooms, item_groups=item_groups
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
    matter_id: str,
    item_group_id: str,
    new_item_group_name: str,
) -> str | None:
    """Apply the item-group form fields to a candidate ``item_group_id`` value.

    ``new_item_group_name`` wins over ``item_group_id`` (explicit create beats
    select). Returns ``None`` when both are empty (clear / leave unset). Raises
    HTTPException(400) when ``item_group_id`` refers to a group in another matter.
    """
    if new_item_group_name.strip():
        ig = find_or_create(db, matter_id, new_item_group_name)
        return ig.id
    if item_group_id:
        ig = db.get(ItemGroup, item_group_id)
        if ig is None or ig.matter_id != matter_id:
            raise HTTPException(status_code=400, detail="Group not in matter")
        return ig.id
    return None


def _parse_cents(dollars_str: str) -> int:
    try:
        return round(float(dollars_str or 0) * 100)
    except ValueError:
        return 0


@router.get("/api/matters/{matter_id}/items-rows", response_class=HTMLResponse)
def get_items_rows(
    request: Request,
    matter_id: str,
    offset: int = 0,
    user: CurrentUser = Depends(require_matter_role("viewer")),
) -> HTMLResponse:
    """Render one offset-paginated page of item `<tr>` rows + sentinel.

    Honors the sort/filter querystring (see `_parse_item_filters`). `offset`
    is the row offset of this page (0 for the first page).
    """
    offset = max(0, offset)
    f = _parse_item_filters(request)
    db = SessionLocal()
    try:
        rows = _build_items_query(db, matter_id, f).offset(offset).limit(ITEMS_PAGE_SIZE + 1).all()
        if len(rows) > ITEMS_PAGE_SIZE:
            rows = rows[:ITEMS_PAGE_SIZE]
            next_offset = offset + ITEMS_PAGE_SIZE
        else:
            next_offset = None
        categories, room_objs, _groups = _get_context(matter_id, db)
    finally:
        db.close()
    return HTMLResponse(
        templates.get_template("_items_rows_fragment.html").render(
            items=rows,
            items_next_offset=next_offset,
            items_qs=items_query_string(f),
            matter_id=matter_id,
            categories=categories,
            rooms=room_objs,
        )
    )


def items_region_context(db, matter_id: str, f: ItemFilters, *, offset: int = 0) -> dict:
    """Build the template context for the swappable items region."""
    rows = _build_items_query(db, matter_id, f).offset(offset).limit(ITEMS_PAGE_SIZE + 1).all()
    if len(rows) > ITEMS_PAGE_SIZE:
        rows = rows[:ITEMS_PAGE_SIZE]
        next_offset = offset + ITEMS_PAGE_SIZE
    else:
        next_offset = None
    categories, room_objs, _groups = _get_context(matter_id, db)
    total_count = db.query(func.count(Item.id)).filter(Item.matter_id == matter_id).scalar()
    return {
        "matter_id": matter_id,
        "f": f,
        "items": rows,
        "items_next_offset": next_offset,
        "items_qs": items_query_string(f),
        "header_sorts": {col: _sort_state(f, col) for col in SORTABLE_KEYS},
        "filtered_count": _count_items(db, matter_id, f),
        "items_total_count": total_count,
        "categories": categories,
        "rooms": room_objs,
    }


@router.get("/api/matters/{matter_id}/items-region", response_class=HTMLResponse)
def get_items_region(
    request: Request,
    matter_id: str,
    user: CurrentUser = Depends(require_matter_role("viewer")),
) -> HTMLResponse:
    """Render the full items region (filter bar + sortable header + page 1)."""
    f = _parse_item_filters(request)
    db = SessionLocal()
    try:
        ctx = items_region_context(db, matter_id, f)
    finally:
        db.close()
    return HTMLResponse(templates.get_template("_items_region.html").render(**ctx))


@router.get("/api/matters/{matter_id}/items-summary", response_class=HTMLResponse)
def get_items_summary(
    matter_id: str,
    user: CurrentUser = Depends(require_matter_role("viewer")),
) -> HTMLResponse:
    """Render the Confirmed / RCV total / ACV total summary block."""
    db = SessionLocal()
    try:
        totals = compute_items_totals(matter_id, db)
    finally:
        db.close()
    return HTMLResponse(
        templates.get_template("_items_summary.html").render(matter_id=matter_id, **totals)
    )


@router.post("/api/matters/{matter_id}/items", response_class=HTMLResponse)
def create_item(
    request: Request,
    matter_id: str,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_matter_role("contributor")),
    description: str = Form(""),
    category_id: int = Form(...),
    room_id: str = Form(""),
    quantity: int = Form(1),
    age_years: float = Form(0.0),
    condition: str = Form("average"),
    retail_unit_dollars: str = Form("0"),
    shipping_dollars: str = Form("0"),
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
            db.query(func.max(Item.line_number)).filter(Item.matter_id == matter_id).scalar() or 0
        )
        item = Item(
            matter_id=matter_id,
            category_id=category_id,
            room_id=room_id or None,
            line_number=max_line + 1,
            description=description.strip(),
            brand=brand.strip() or None,
            model=model_num.strip() or None,
            quantity=max(1, quantity),
            age_years=max(0.0, age_years),
            condition=condition,
            retail_unit_cents=_parse_cents(retail_unit_dollars),
            shipping_cents=_parse_cents(shipping_dollars),
            notes=notes.strip(),
            confirmed=True,  # manually entered items start confirmed; Vision drafts use False
        )
        item.item_group_id = _resolve_item_group_id(
            db, matter_id, item_group_id, new_item_group_name
        )
        _compute_and_set_totals(item, cat)
        db.add(item)
        db.commit()
        db.refresh(item)
        item_id = item.id
        categories, rooms, item_groups = _get_context(matter_id, db)
        row_html = _item_row_html(item, categories, rooms, item_groups)
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
        matter_id=matter_id,
        ip_address=get_client_ip(request),
    )
    # Use HX-Trigger to nudge the client to refresh totals + drop empty-state row.
    headers = {"HX-Trigger": "item-created"}
    return HTMLResponse(row_html, headers=headers, status_code=200)


@router.get("/api/items/{item_id}/edit", response_class=HTMLResponse)
def item_edit_form(
    item_id: str, user: CurrentUser = Depends(require_matter_role("editor"))
) -> HTMLResponse:
    db = SessionLocal()
    try:
        item = db.query(Item).options(selectinload(Item.crops)).filter(Item.id == item_id).first()
        if item is None:
            raise HTTPException(status_code=404)
        categories, rooms, item_groups = _get_context(item.matter_id, db)

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
    item_id: str, user: CurrentUser = Depends(require_matter_role("viewer"))
) -> HTMLResponse:
    db = SessionLocal()
    try:
        item = db.query(Item).options(selectinload(Item.crops)).filter(Item.id == item_id).first()
        if item is None:
            raise HTTPException(status_code=404)
        categories, rooms, item_groups = _get_context(item.matter_id, db)
        html = _item_row_html(item, categories, rooms, item_groups)
    finally:
        db.close()
    return HTMLResponse(html)


@router.patch("/api/items/{item_id}", response_class=HTMLResponse)
def update_item(
    request: Request,
    item_id: str,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_matter_role("editor")),
    description: str = Form(""),
    category_id: int = Form(...),
    room_id: str = Form(""),
    quantity: int = Form(1),
    age_years: float = Form(0.0),
    condition: str = Form("average"),
    retail_unit_dollars: str = Form("0"),
    shipping_dollars: str = Form("0"),
    brand: str = Form(""),
    model_num: str = Form(""),
    notes: str = Form(""),
    source_retailer: str = Form(""),
    source_url: str = Form(""),
    match_type: str = Form("exact"),
    acv_override_dollars: str = Form(""),
    acv_override_reason: str = Form(""),
    confirmed: bool = Form(False),
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

        item.confirmed = confirmed
        item.description = description.strip()
        item.category_id = category_id
        item.room_id = room_id or None
        item.quantity = max(1, quantity)
        item.age_years = max(0.0, age_years)
        item.condition = condition
        item.retail_unit_cents = _parse_cents(retail_unit_dollars)
        item.shipping_cents = _parse_cents(shipping_dollars)
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
            db, item.matter_id, item_group_id, new_item_group_name
        )

        _compute_and_set_totals(item, cat)
        db.commit()
        db.refresh(item)
        matter_id = item.matter_id
        categories, rooms, item_groups = _get_context(matter_id, db)
        html = _item_row_html(item, categories, rooms, item_groups)
    finally:
        db.close()
    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="item.update",
        resource_type="item",
        resource_id=item_id,
        matter_id=matter_id,
        ip_address=get_client_ip(request),
    )
    return HTMLResponse(html)


@router.post("/api/items/{item_id}/toggle-confirm", response_class=HTMLResponse)
def toggle_confirm(
    request: Request,
    item_id: str,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_matter_role("manager")),
) -> HTMLResponse:
    db = SessionLocal()
    try:
        item = db.query(Item).options(selectinload(Item.crops)).filter(Item.id == item_id).first()
        if item is None:
            raise HTTPException(status_code=404)
        item.confirmed = not item.confirmed
        if item.confirmed:
            item.confirmed_by_id = user.id
            item.confirmed_at = datetime.now(tz=timezone.utc)
        else:
            item.confirmed_by_id = None
            item.confirmed_at = None
        db.commit()
        db.refresh(item)
        matter_id = item.matter_id
        categories, rooms, item_groups = _get_context(matter_id, db)
        html = _item_row_html(item, categories, rooms, item_groups)
    finally:
        db.close()
    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="item.update",
        resource_type="item",
        resource_id=item_id,
        matter_id=matter_id,
        ip_address=get_client_ip(request),
    )
    return HTMLResponse(html)


@router.post("/api/items/{item_id}/toggle-exclude", response_class=HTMLResponse)
def toggle_exclude(
    request: Request,
    item_id: str,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_matter_role("manager")),
) -> HTMLResponse:
    db = SessionLocal()
    try:
        item = db.query(Item).options(selectinload(Item.crops)).filter(Item.id == item_id).first()
        if item is None:
            raise HTTPException(status_code=404)
        item.excluded = not item.excluded
        db.commit()
        db.refresh(item)
        matter_id = item.matter_id
        categories, rooms, item_groups = _get_context(matter_id, db)
        html = _item_row_html(item, categories, rooms, item_groups)
    finally:
        db.close()
    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="item.update",
        resource_type="item",
        resource_id=item_id,
        matter_id=matter_id,
        ip_address=get_client_ip(request),
    )
    return HTMLResponse(html)


@router.delete("/api/items/{item_id}", response_class=HTMLResponse)
def delete_item(
    request: Request,
    item_id: str,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_matter_role("manager")),
) -> HTMLResponse:
    db = SessionLocal()
    try:
        item = db.get(Item, item_id)
        if item is None:
            raise HTTPException(status_code=404)
        matter_id = item.matter_id
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
        matter_id=matter_id,
        ip_address=get_client_ip(request),
    )
    return HTMLResponse("", status_code=200)
