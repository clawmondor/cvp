"""Admin-only catalog management for vision models."""

from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.requests import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from cvp.db import get_db
from cvp.dependencies import CurrentUser, require_system_admin
from cvp.models_vision import VisionModel

BASE_DIR = Path(__file__).parent.parent.parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")

router = APIRouter(prefix="/admin/vision-models")


@router.get("", response_class=HTMLResponse)
def index(
    request: Request,
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    rows = (
        db.query(VisionModel)
        .order_by(VisionModel.recommended.desc(), VisionModel.display_name.asc())
        .all()
    )
    return templates.TemplateResponse(
        request,
        "admin/vision_models.html",
        {"user": user, "rows": rows, "panel_title": "Vision Models"},
    )
