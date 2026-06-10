"""System-admin page for runtime-configurable settings stored in app_setting."""

from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from cvp.db import get_db
from cvp.dependencies import CurrentUser, require_system_admin
from cvp.services import runtime_config

BASE_DIR = Path(__file__).parent.parent.parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")

router = APIRouter(prefix="/admin/system/runtime-config")

_KNOBS = (
    "evidence_upload_concurrency",
    "evidence_upload_max_file_mb",
    "evidence_upload_max_batch_count",
)


@router.get("", response_class=HTMLResponse)
def index(
    request: Request,
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    rows = [{"key": k, "value": runtime_config.get_int(db, k)} for k in _KNOBS]
    return templates.TemplateResponse(
        request,
        "admin/system/runtime_config.html",
        {
            "user": user,
            "rows": rows,
            "bounds": runtime_config._BOUNDS,
            "panel_title": "System Admin",
            "breadcrumbs": [
                {"label": "System Admin", "url": "/admin/system/"},
                {"label": "Runtime Config", "url": "/admin/system/runtime-config"},
            ],
        },
    )


@router.post("", response_class=HTMLResponse)
def update(
    request: Request,
    evidence_upload_concurrency: int | None = Form(None),
    evidence_upload_max_file_mb: int | None = Form(None),
    evidence_upload_max_batch_count: int | None = Form(None),
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    submitted = {
        "evidence_upload_concurrency": evidence_upload_concurrency,
        "evidence_upload_max_file_mb": evidence_upload_max_file_mb,
        "evidence_upload_max_batch_count": evidence_upload_max_batch_count,
    }
    for key, value in submitted.items():
        if value is None:
            continue
        try:
            runtime_config.set_value(db, key, value, updated_by_user_id=user.id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
    return RedirectResponse(url="/admin/system/runtime-config", status_code=303)
