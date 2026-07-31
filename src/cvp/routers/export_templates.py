"""Custom export template CRUD + builder page."""

import html
import json
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from cvp.db import SessionLocal
from cvp.dependencies import CurrentUser, require_matter_role
from cvp.models import Matter
from cvp.services import export_templates as svc
from cvp.services.export_fields import field_groups

BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")

router = APIRouter()


def _matter_group_id(db, matter_id: str) -> str:
    matter = db.get(Matter, matter_id)
    if matter is None or not matter.owner_group_id:
        raise HTTPException(status_code=404, detail="Matter not found")
    return matter.owner_group_id


def _parse_columns(columns_json: str) -> list[svc.ColumnSpec]:
    try:
        raw = json.loads(columns_json or "[]")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Malformed columns") from exc
    if not isinstance(raw, list):
        raise HTTPException(status_code=400, detail="Malformed columns")
    specs: list[svc.ColumnSpec] = []
    for c in raw:
        if not isinstance(c, dict):
            raise HTTPException(status_code=400, detail="Malformed columns")
        specs.append(
            svc.ColumnSpec(
                field_key=(c.get("field_key") or None),
                header_label=(c.get("header_label") or None),
                static_value=(c.get("static_value") if c.get("field_key") in (None, "") else None),
            )
        )
    return specs


def _builder_context(
    request: Request, db, matter_id: str, group_id: str, user: CurrentUser
) -> dict:
    tmpls = svc.list_templates(db, group_id)
    return {
        "request": request,
        "user": user,
        "matter_id": matter_id,
        "templates_list": tmpls,
        "field_groups": field_groups(),
        "sort_fields": svc.SORT_FIELDS,
        "xactimate_defaults": svc.xactimate_default_columns(),
    }


def _render_page(
    request: Request, db, matter_id: str, group_id: str, user: CurrentUser
) -> HTMLResponse:
    """Full page (extends base.html) — used by the GET builder page."""
    return templates.TemplateResponse(
        request,
        "export_templates_builder.html",
        _builder_context(request, db, matter_id, group_id, user),
    )


def _render_body(
    request: Request, db, matter_id: str, group_id: str, user: CurrentUser
) -> HTMLResponse:
    """Swappable ``#builder-root`` fragment only — used by create/update/delete."""
    return templates.TemplateResponse(
        request,
        "_export_templates_body.html",
        _builder_context(request, db, matter_id, group_id, user),
    )


@router.get("/matters/{matter_id}/export-templates", response_class=HTMLResponse)
def builder_page(
    request: Request,
    matter_id: str,
    user: CurrentUser = Depends(require_matter_role("viewer")),
) -> HTMLResponse:
    db = SessionLocal()
    try:
        group_id = _matter_group_id(db, matter_id)
        return _render_page(request, db, matter_id, group_id, user)
    finally:
        db.close()


@router.post("/api/matters/{matter_id}/export-templates", response_class=HTMLResponse)
def create(
    request: Request,
    matter_id: str,
    name: str = Form(...),
    description: str = Form(""),
    sort_field: str = Form("line_number"),
    include_needs_review: bool = Form(False),
    include_excluded: bool = Form(False),
    columns_json: str = Form("[]"),
    user: CurrentUser = Depends(require_matter_role("contributor")),
) -> HTMLResponse:
    db = SessionLocal()
    try:
        group_id = _matter_group_id(db, matter_id)
        try:
            svc.create_template(
                db,
                group_id=group_id,
                created_by_id=user.id,
                name=name,
                description=description,
                include_needs_review=include_needs_review,
                include_excluded=include_excluded,
                sort_field=sort_field,
                columns=_parse_columns(columns_json),
            )
        except ValueError as exc:
            return HTMLResponse(
                f'<p class="text-sm text-red-600">{html.escape(str(exc))}</p>', status_code=400
            )
        return _render_body(request, db, matter_id, group_id, user)
    finally:
        db.close()


@router.put("/api/matters/{matter_id}/export-templates/{tid}", response_class=HTMLResponse)
def update(
    request: Request,
    matter_id: str,
    tid: str,
    name: str = Form(...),
    description: str = Form(""),
    sort_field: str = Form("line_number"),
    include_needs_review: bool = Form(False),
    include_excluded: bool = Form(False),
    columns_json: str = Form("[]"),
    user: CurrentUser = Depends(require_matter_role("contributor")),
) -> HTMLResponse:
    db = SessionLocal()
    try:
        group_id = _matter_group_id(db, matter_id)
        template = svc.get_template(db, tid, group_id)
        if template is None:
            raise HTTPException(status_code=404, detail="Template not found")
        try:
            svc.update_template(
                db,
                template,
                name=name,
                description=description,
                include_needs_review=include_needs_review,
                include_excluded=include_excluded,
                sort_field=sort_field,
                columns=_parse_columns(columns_json),
            )
        except ValueError as exc:
            return HTMLResponse(
                f'<p class="text-sm text-red-600">{html.escape(str(exc))}</p>', status_code=400
            )
        return _render_body(request, db, matter_id, group_id, user)
    finally:
        db.close()


@router.delete("/api/matters/{matter_id}/export-templates/{tid}", response_class=HTMLResponse)
def delete(
    request: Request,
    matter_id: str,
    tid: str,
    user: CurrentUser = Depends(require_matter_role("contributor")),
) -> HTMLResponse:
    db = SessionLocal()
    try:
        group_id = _matter_group_id(db, matter_id)
        template = svc.get_template(db, tid, group_id)
        if template is None:
            raise HTTPException(status_code=404, detail="Template not found")
        svc.delete_template(db, template)
        return _render_body(request, db, matter_id, group_id, user)
    finally:
        db.close()
