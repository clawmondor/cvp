import uuid
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import selectinload

from cvp.db import SessionLocal
from cvp.models import Matter

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
            .options(selectinload(Matter.items))
            .filter(Matter.id == matter_id)
            .first()
        )
        if matter is None:
            return HTMLResponse("Matter not found", status_code=404)
        items = matter.items
    finally:
        db.close()

    return templates.TemplateResponse(
        request=request,
        name="matter_detail.html",
        context={"matter": matter, "items": items},
    )
