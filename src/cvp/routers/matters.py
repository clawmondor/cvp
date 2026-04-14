import uuid
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import selectinload

from cvp.db import SessionLocal
from cvp.models import Category, Matter

BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")

router = APIRouter()

LOSS_TYPES = ["total_loss", "partial_loss", "smoke", "water", "theft", "other"]
LOSS_EVENTS = ["Palisades Fire", "Eaton Fire", "Other"]


@router.get("/matters/new", response_class=HTMLResponse)
def new_matter_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="matter_new.html",
        context={"loss_types": LOSS_TYPES, "loss_events": LOSS_EVENTS},
    )


@router.post("/matters")
def create_matter(
    request: Request,
    firm_name: str = Form(default=""),
    attorney_name: str = Form(default=""),
    attorney_email: str = Form(default=""),
    policyholder_name: str = Form(default=""),
    loss_location: str = Form(default=""),
    loss_type: str = Form(default="total_loss"),
    loss_event: str = Form(default=""),
    loss_date: str = Form(default=""),
    carrier: str = Form(default=""),
    policy_number: str = Form(default=""),
    claim_number: str = Form(default=""),
    coverage_c_limit_dollars: str = Form(default="0"),
    firm_file_number: str = Form(default=""),
    target_delivery_date: str = Form(default=""),
) -> RedirectResponse:
    db = SessionLocal()
    try:
        matter = Matter(
            id=str(uuid.uuid4()),
            firm_name=firm_name,
            attorney_name=attorney_name,
            attorney_email=attorney_email,
            policyholder_name=policyholder_name,
            loss_location=loss_location,
            loss_type=loss_type,
            loss_event=loss_event,
            loss_date=date.fromisoformat(loss_date) if loss_date else None,
            carrier=carrier,
            policy_number=policy_number,
            claim_number=claim_number,
            coverage_c_limit=int(float(coverage_c_limit_dollars or 0) * 100),
            firm_file_number=firm_file_number,
            target_delivery_date=(
                date.fromisoformat(target_delivery_date) if target_delivery_date else None
            ),
        )
        db.add(matter)
        db.commit()
        db.refresh(matter)
        matter_id = matter.id
    finally:
        db.close()

    return RedirectResponse(url=f"/matters/{matter_id}", status_code=303)


@router.get("/matters/{matter_id}", response_class=HTMLResponse)
def matter_detail(request: Request, matter_id: str) -> HTMLResponse:
    db = SessionLocal()
    try:
        matter = (
            db.query(Matter)
            .options(
                selectinload(Matter.items),
                selectinload(Matter.evidence_files),
                selectinload(Matter.rooms),
            )
            .filter(Matter.id == matter_id)
            .first()
        )
        if matter is None:
            return HTMLResponse("Matter not found", status_code=404)
        items = sorted(matter.items, key=lambda i: i.line_number)
        confirmed = [i for i in items if i.confirmed and not i.excluded]
        total_rcv_cents = sum(i.rcv_total_cents for i in confirmed)
        total_acv_cents = sum(i.acv_total_cents for i in confirmed)
        unconfirmed_count = sum(1 for i in items if not i.confirmed)
        missing_price_count = sum(1 for i in confirmed if i.rcv_unit_cents == 0)
        evidence_files = sorted(matter.evidence_files, key=lambda f: f.created_at, reverse=True)
        rooms = sorted(matter.rooms, key=lambda r: r.sort_order)
        categories = db.query(Category).order_by(Category.id).all()
    finally:
        db.close()

    return templates.TemplateResponse(
        request=request,
        name="matter_detail.html",
        context={
            "matter": matter,
            "items": items,
            "evidence_files": evidence_files,
            "rooms": rooms,
            "categories": categories,
            "total_rcv_cents": total_rcv_cents,
            "total_acv_cents": total_acv_cents,
            "unconfirmed_count": unconfirmed_count,
            "missing_price_count": missing_price_count,
            "loss_types": LOSS_TYPES,
            "loss_events": LOSS_EVENTS,
        },
    )


@router.post("/matters/{matter_id}/update")
def update_matter(
    matter_id: str,
    firm_name: str = Form(default=""),
    attorney_name: str = Form(default=""),
    attorney_email: str = Form(default=""),
    policyholder_name: str = Form(default=""),
    loss_location: str = Form(default=""),
    loss_type: str = Form(default="total_loss"),
    loss_event: str = Form(default=""),
    loss_date: str = Form(default=""),
    carrier: str = Form(default=""),
    policy_number: str = Form(default=""),
    claim_number: str = Form(default=""),
    coverage_c_limit_dollars: str = Form(default="0"),
    firm_file_number: str = Form(default=""),
    target_delivery_date: str = Form(default=""),
    internal_notes: str = Form(default=""),
) -> RedirectResponse:
    db = SessionLocal()
    try:
        matter = db.get(Matter, matter_id)
        if matter is None:
            return HTMLResponse("Matter not found", status_code=404)
        matter.firm_name = firm_name
        matter.attorney_name = attorney_name
        matter.attorney_email = attorney_email
        matter.policyholder_name = policyholder_name
        matter.loss_location = loss_location
        matter.loss_type = loss_type
        matter.loss_event = loss_event
        matter.loss_date = date.fromisoformat(loss_date) if loss_date else None
        matter.carrier = carrier
        matter.policy_number = policy_number
        matter.claim_number = claim_number
        matter.coverage_c_limit = int(float(coverage_c_limit_dollars or 0) * 100)
        matter.firm_file_number = firm_file_number
        matter.target_delivery_date = (
            date.fromisoformat(target_delivery_date) if target_delivery_date else None
        )
        matter.internal_notes = internal_notes
        db.commit()
    finally:
        db.close()
    return RedirectResponse(url=f"/matters/{matter_id}#overview", status_code=303)


@router.post("/api/matters/{matter_id}/status")
def update_matter_status(
    matter_id: str,
    status: str = Form(...),
) -> RedirectResponse:
    valid = {"draft", "in_review", "delivered", "archived"}
    if status not in valid:
        return HTMLResponse("Invalid status", status_code=400)
    db = SessionLocal()
    try:
        matter = db.get(Matter, matter_id)
        if matter is None:
            return HTMLResponse("Matter not found", status_code=404)
        matter.status = status
        if status == "delivered":
            from datetime import date as date_cls

            matter.delivered_date = date_cls.today()
        db.commit()
    finally:
        db.close()
    return RedirectResponse(url=f"/matters/{matter_id}#overview", status_code=303)
