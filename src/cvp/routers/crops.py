"""Crop adjustment and re-crop endpoints."""

import json as _json
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from PIL import Image
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import selectinload

from cvp.config import settings
from cvp.db import SessionLocal
from cvp.dependencies import CurrentUser, require_active_user
from cvp.models import EvidenceFile, ItemCrop
from cvp.services.crop import recrop_item_crop

BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")

router = APIRouter()


class BboxBody(BaseModel):
    left: int
    upper: int
    right: int
    lower: int


@router.post("/api/item-crops/{crop_id}/adjust-bbox")
def adjust_bbox(
    crop_id: str, body: BboxBody, user: CurrentUser = Depends(require_active_user)
) -> JSONResponse:
    db = SessionLocal()
    try:
        crop = db.get(ItemCrop, crop_id)
        if crop is None:
            return JSONResponse({"error": "not found"}, status_code=404)

        ef = db.get(EvidenceFile, crop.evidence_file_id)
        if ef is None:
            return JSONResponse({"error": "evidence file not found"}, status_code=404)

        upload_base = Path(settings.upload_dir).resolve()
        with Image.open((upload_base / ef.stored_path).resolve()) as img:
            img_w, img_h = img.size

        if body.left >= body.right or body.upper >= body.lower:
            return JSONResponse(
                {"error": "left must be < right and upper must be < lower"}, status_code=422
            )
        if not (0 <= body.left <= img_w and 0 <= body.right <= img_w):
            return JSONResponse(
                {"error": f"x coordinates out of range [0, {img_w}]"}, status_code=422
            )
        if not (0 <= body.upper <= img_h and 0 <= body.lower <= img_h):
            return JSONResponse(
                {"error": f"y coordinates out of range [0, {img_h}]"}, status_code=422
            )

        crop.adjusted_bbox_left = body.left
        crop.adjusted_bbox_upper = body.upper
        crop.adjusted_bbox_right = body.right
        crop.adjusted_bbox_lower = body.lower
        db.commit()
    finally:
        db.close()
    return JSONResponse({"ok": True})


@router.delete("/api/item-crops/{crop_id}/adjust-bbox")
def clear_bbox(crop_id: str, user: CurrentUser = Depends(require_active_user)) -> JSONResponse:
    db = SessionLocal()
    try:
        crop = db.get(ItemCrop, crop_id)
        if crop is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        crop.adjusted_bbox_left = None
        crop.adjusted_bbox_upper = None
        crop.adjusted_bbox_right = None
        crop.adjusted_bbox_lower = None
        db.commit()
    finally:
        db.close()
    return JSONResponse({"ok": True})


@router.get("/api/evidence/{file_id}/crop-editor", response_class=HTMLResponse)
def crop_editor(
    request: Request, file_id: str, user: CurrentUser = Depends(require_active_user)
) -> HTMLResponse:
    db = SessionLocal()
    try:
        ef = db.get(EvidenceFile, file_id)
        if ef is None:
            return HTMLResponse("Evidence file not found", status_code=404)

        crops = (
            db.query(ItemCrop)
            .filter(ItemCrop.evidence_file_id == file_id)
            .options(selectinload(ItemCrop.item))
            .all()
        )

        upload_base = Path(settings.upload_dir).resolve()
        with Image.open((upload_base / ef.stored_path).resolve()) as img:
            img_w, img_h = img.size

        crops_json = _json.dumps(
            [
                {
                    "id": c.id,
                    "description": (c.item.description if c.item else None) or f"Item {i + 1}",
                    "bbox": list(c.effective_bbox),
                    "claude_bbox": [c.bbox_left, c.bbox_upper, c.bbox_right, c.bbox_lower],
                    "adjusted": all(
                        v is not None
                        for v in (
                            c.adjusted_bbox_left,
                            c.adjusted_bbox_upper,
                            c.adjusted_bbox_right,
                            c.adjusted_bbox_lower,
                        )
                    ),
                }
                for i, c in enumerate(crops)
            ]
        )

        stored_path = ef.stored_path
    finally:
        db.close()

    return templates.TemplateResponse(
        request=request,
        name="_crop_editor.html",
        context={
            "evidence_file": ef,
            "img_w": img_w,
            "img_h": img_h,
            "crops_json": crops_json,
            "stored_path": stored_path,
        },
    )


@router.post("/api/evidence/{file_id}/recrop")
def recrop_evidence(file_id: str, user: CurrentUser = Depends(require_active_user)) -> JSONResponse:
    db = SessionLocal()
    try:
        ef = db.get(EvidenceFile, file_id)
        if ef is None:
            return JSONResponse({"error": "not found"}, status_code=404)

        crops = (
            db.query(ItemCrop)
            .filter(
                ItemCrop.evidence_file_id == file_id,
                or_(
                    ItemCrop.adjusted_bbox_left.isnot(None),
                    ItemCrop.adjusted_bbox_upper.isnot(None),
                    ItemCrop.adjusted_bbox_right.isnot(None),
                    ItemCrop.adjusted_bbox_lower.isnot(None),
                ),
            )
            .all()
        )

        upload_base = Path(settings.upload_dir).resolve()
        crop_base = Path(settings.crop_dir).resolve()
        recropped_ids = []

        for crop in crops:
            crop.crop_path = recrop_item_crop(crop, ef, upload_base, crop_base)
            recropped_ids.append(crop.id)

        db.commit()
    finally:
        db.close()

    return JSONResponse({"recropped": recropped_ids})
