"""Admin-only catalog management for vision models."""

import time
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.requests import Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from cvp.db import get_db
from cvp.dependencies import CurrentUser, require_system_admin
from cvp.models import VisionRun
from cvp.models_vision import VisionModel
from cvp.services import openrouter
from cvp.services.audit import get_client_ip, write_audit_log
from cvp.services.vision_models import is_recommended, suggest_adapter

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


# In-process catalog cache: (timestamp, list)
_catalog_cache: tuple[float, list[dict]] | None = None
_CATALOG_TTL_SECONDS = 3600.0


def _get_catalog() -> list[dict]:
    global _catalog_cache
    now = time.time()
    if _catalog_cache and (now - _catalog_cache[0]) < _CATALOG_TTL_SECONDS:
        return _catalog_cache[1]
    fresh = openrouter.fetch_models()
    _catalog_cache = (now, fresh)
    return fresh


@router.get("/add", response_class=HTMLResponse)
def add_modal(
    request: Request,
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    existing_slugs = {r.slug for r in db.query(VisionModel.slug).all()}
    catalog = [m for m in _get_catalog() if m["id"] not in existing_slugs]
    enriched = [
        {
            **m,
            "is_recommended": is_recommended(m["id"]),
            "suggested_adapter": suggest_adapter(m["id"]),
            "image_price": (m.get("pricing") or {}).get("image") or "",
        }
        for m in catalog
    ]
    return templates.TemplateResponse(
        request,
        "admin/_vision_models_add_modal.html",
        {"user": user, "catalog": enriched},
    )


@router.post("", response_class=HTMLResponse)
def add_model(
    request: Request,
    slug: str = Form(...),
    adapter: str = Form(...),
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    if db.query(VisionModel).filter_by(slug=slug).first():
        raise HTTPException(status_code=409, detail=f"slug {slug} already exists")
    if adapter not in ("pixel_passthrough", "gemini_normalized_1000", "none"):
        raise HTTPException(status_code=400, detail="invalid adapter")
    catalog_entry = next((m for m in _get_catalog() if m["id"] == slug), None)
    display_name = (catalog_entry or {}).get("name") or slug
    image_price = (catalog_entry or {}).get("pricing", {}).get("image")
    cost_cents = openrouter.parse_pricing_to_cents(image_price)
    context_length = (catalog_entry or {}).get("context_length")

    row = VisionModel(
        slug=slug,
        display_name=display_name,
        adapter=adapter,
        prompt_image_cost_cents=cost_cents,
        context_length=context_length,
        supports_bbox=(adapter != "none"),
        is_default=False,
        is_enabled=True,
        recommended=is_recommended(slug),
        added_by_user_id=user.id,
    )
    db.add(row)
    db.commit()
    write_audit_log(
        user_id=user.id,
        action="vision_model.add",
        resource_type="vision_model",
        resource_id=str(row.id),
        detail={"slug": slug, "adapter": adapter},
        ip_address=get_client_ip(request),
    )
    return RedirectResponse(url="/admin/vision-models", status_code=303)


@router.post("/{model_id}/set-default", response_class=HTMLResponse)
def set_default(
    request: Request,
    model_id: int,
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    target = db.query(VisionModel).filter_by(id=model_id).first()
    if target is None:
        raise HTTPException(404)
    if not target.is_enabled:
        raise HTTPException(400, "cannot make a disabled model the default")
    db.query(VisionModel).filter(VisionModel.is_default.is_(True)).update(
        {"is_default": False}
    )
    target.is_default = True
    db.commit()
    write_audit_log(
        user_id=user.id,
        action="vision_model.set_default",
        resource_type="vision_model",
        resource_id=str(model_id),
        detail={"slug": target.slug},
        ip_address=get_client_ip(request),
    )
    return RedirectResponse("/admin/vision-models", status_code=303)


@router.post("/{model_id}/disable", response_class=HTMLResponse)
def disable_model(
    request: Request,
    model_id: int,
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    row = db.query(VisionModel).filter_by(id=model_id).first()
    if row is None:
        raise HTTPException(404)
    if row.is_default:
        raise HTTPException(400, "cannot disable the default model")
    row.is_enabled = False
    db.commit()
    write_audit_log(
        user_id=user.id,
        action="vision_model.disable",
        resource_type="vision_model",
        resource_id=str(model_id),
        detail={"slug": row.slug},
        ip_address=get_client_ip(request),
    )
    return _render_row(request, row, user)


@router.post("/{model_id}/enable", response_class=HTMLResponse)
def enable_model(
    request: Request,
    model_id: int,
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    row = db.query(VisionModel).filter_by(id=model_id).first()
    if row is None:
        raise HTTPException(404)
    row.is_enabled = True
    db.commit()
    write_audit_log(
        user_id=user.id,
        action="vision_model.enable",
        resource_type="vision_model",
        resource_id=str(model_id),
        detail={"slug": row.slug},
        ip_address=get_client_ip(request),
    )
    return _render_row(request, row, user)


@router.post("/{model_id}/refresh-pricing", response_class=HTMLResponse)
def refresh_pricing(
    request: Request,
    model_id: int,
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    row = db.query(VisionModel).filter_by(id=model_id).first()
    if row is None:
        raise HTTPException(404)
    global _catalog_cache
    _catalog_cache = None  # bust cache
    catalog = _get_catalog()
    entry = next((m for m in catalog if m["id"] == row.slug), None)
    if entry is None:
        return _render_row(request, row, user, flash="not listed by OpenRouter")
    row.prompt_image_cost_cents = openrouter.parse_pricing_to_cents(
        (entry.get("pricing") or {}).get("image")
    )
    row.context_length = entry.get("context_length")
    db.commit()
    write_audit_log(
        user_id=user.id,
        action="vision_model.refresh_pricing",
        resource_type="vision_model",
        resource_id=str(model_id),
        detail={"slug": row.slug},
        ip_address=get_client_ip(request),
    )
    return _render_row(request, row, user)


@router.delete("/{model_id}", response_class=HTMLResponse)
def delete_model(
    request: Request,
    model_id: int,
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    row = db.query(VisionModel).filter_by(id=model_id).first()
    if row is None:
        raise HTTPException(404)
    if row.is_default:
        raise HTTPException(400, "cannot delete the default model — change default first")
    in_use = db.query(VisionRun).filter(VisionRun.model == row.slug).first() is not None
    if in_use:
        raise HTTPException(409, "model in use by historical scans — disable instead")
    slug = row.slug
    db.delete(row)
    db.commit()
    write_audit_log(
        user_id=user.id,
        action="vision_model.delete",
        resource_type="vision_model",
        resource_id=str(model_id),
        detail={"slug": slug},
        ip_address=get_client_ip(request),
    )
    return HTMLResponse("")


def _render_row(
    request: Request, row: VisionModel, user: CurrentUser, flash: str | None = None
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "admin/_vision_models_row.html",
        {"r": row, "user": user, "flash": flash},
    )
