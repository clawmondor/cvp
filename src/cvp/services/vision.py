"""Vision scan service — sequential image processing via OpenRouter."""

import io
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
from PIL import Image
from sqlalchemy import func as sqlfunc
from sqlalchemy.orm import Session

from cvp.config import settings
from cvp.db import SessionLocal
from cvp.models import (
    Category,
    EvidenceFile,
    Item,
    ItemCrop,
    ItemGroup,
    VisionJob,
    VisionJobImage,
    VisionRun,
)
from cvp.models_vision import VisionModel
from cvp.services import openrouter
from cvp.services.crop import recrop_item_crop
from cvp.services.item_groups import find_or_create
from cvp.services.vision_adapters import resolve as resolve_adapter
from cvp.services.vision_prompts import SCAN_PROMPT_VERSION, build_scan_prompt

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Image downscaling
# ---------------------------------------------------------------------------


def _downscale(image_bytes: bytes) -> tuple[bytes, str]:
    """Resize long-edge to ≤1568px, re-encode as JPEG quality 85."""
    with Image.open(io.BytesIO(image_bytes)) as img:
        w, h = img.size
        max_side = max(w, h)
        if max_side > 1568:
            scale = 1568 / max_side
            to_save = img.resize((round(w * scale), round(h * scale)), Image.LANCZOS)
        else:
            to_save = img
        buf = io.BytesIO()
        to_save.convert("RGB").save(buf, "JPEG", quality=85)
    return buf.getvalue(), "image/jpeg"


# ---------------------------------------------------------------------------
# Category matching
# ---------------------------------------------------------------------------


def _match_category_id(hint: str | None, categories: list[Category]) -> int:
    if not hint or not categories:
        return categories[-1].id if categories else 1
    hint_lower = hint.lower()
    for cat in categories:
        if hint_lower in cat.name.lower() or cat.name.lower() in hint_lower:
            return cat.id
    hint_words = set(hint_lower.split())
    best_id, best_score = categories[-1].id, 0
    for cat in categories:
        cat_words = set(cat.name.lower().split(",")[0].split())
        score = len(hint_words & cat_words)
        if score > best_score:
            best_score, best_id = score, cat.id
    return best_id


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def _parse_response(text: str) -> tuple[list[dict], str]:
    """Parse a vision response into ``(items, placard_text)``.

    Accepts both the v4 object shape ``{"items": [...], "placard_text": "..."}``
    and the v3 legacy shape (bare JSON array of item objects). The legacy case
    returns ``placard_text=""`` so downstream code can stay branch-free.
    """
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    def _coerce(parsed: object) -> tuple[list[dict], str]:
        if isinstance(parsed, dict):
            items_raw = parsed.get("items")
            items = items_raw if isinstance(items_raw, list) else []
            placard = parsed.get("placard_text")
            return ([i for i in items if isinstance(i, dict)], str(placard or ""))
        if isinstance(parsed, list):
            return ([i for i in parsed if isinstance(i, dict)], "")
        return ([], "")

    try:
        return _coerce(json.loads(text))
    except json.JSONDecodeError:
        pass

    # Last-ditch: recover an embedded JSON object or array.
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return _coerce(json.loads(m.group()))
        except json.JSONDecodeError:
            pass
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if m:
        try:
            return _coerce(json.loads(m.group()))
        except json.JSONDecodeError:
            pass
    return [], ""


# ---------------------------------------------------------------------------
# Item-group resolution
# ---------------------------------------------------------------------------


def _resolve_effective_item_group_id(
    db: Session, ef: EvidenceFile, placard_text: str
) -> str | None:
    """Return the item_group_id to apply to items extracted from ``ef``.

    Rule:
      1. If ``ef.pinned_item_group_id`` is set, the dropdown wins. A
         conflicting placard reading is logged at INFO and ignored.
      2. Otherwise, if ``placard_text`` is non-empty, find-or-create a group
         on the matter using normalize-and-dedupe matching.
      3. Otherwise, return ``None``.
    """
    pinned_id = ef.pinned_item_group_id
    text = (placard_text or "").strip()

    if pinned_id is not None:
        if text:
            pinned = db.get(ItemGroup, pinned_id)
            if pinned is not None and pinned.name_normalized != text.lower():
                logger.info(
                    "vision: placard mismatch — pinned group %s (%r),"
                    " detected %r on evidence_file %s",
                    pinned_id,
                    pinned.name,
                    text,
                    ef.id,
                )
        return pinned_id

    if not text:
        return None

    group = find_or_create(db, ef.matter_id, text)
    return group.id


# ---------------------------------------------------------------------------
# Job status query
# ---------------------------------------------------------------------------


def get_job_data(job_id: str) -> dict:
    """Return progress dict compatible with _scan_progress.html template vars."""
    db = SessionLocal()
    try:
        job = db.get(VisionJob, job_id)
        if job is None:
            return {
                "status": "error",
                "progress": 0,
                "total": 0,
                "items_created": 0,
                "errors": ["Job not found"],
            }
        images = db.query(VisionJobImage).filter_by(job_id=job_id).all()
        total = len(images)
        progress = sum(1 for i in images if i.status in ("done", "error"))
        items_created = sum(i.items_created or 0 for i in images)
        errors = [i.error_message for i in images if i.status == "error" and i.error_message]
        return {
            "status": job.status,
            "progress": progress,
            "total": total,
            "items_created": items_created,
            "errors": errors,
        }
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Core scan logic — called by vision_worker per image
# ---------------------------------------------------------------------------


def _maybe_complete_job(db: Session, job_id: str) -> None:
    """Mark the VisionJob done/error when all images are in a terminal state."""
    pending = (
        db.query(VisionJobImage)
        .filter(
            VisionJobImage.job_id == job_id,
            VisionJobImage.status.in_(["pending", "running"]),
        )
        .count()
    )
    if pending > 0:
        return
    job = db.get(VisionJob, job_id)
    if job is None:
        return
    has_errors = db.query(VisionJobImage).filter_by(job_id=job_id, status="error").count()
    job.status = "error" if has_errors else "done"
    job.completed_at = datetime.now(timezone.utc)
    db.commit()


def process_one_image(job_image_id: str) -> None:
    """Process one VisionJobImage. Opens its own DB session. Marks status done or error."""
    upload_base = Path(settings.upload_dir).resolve()
    crop_base = Path(settings.crop_dir).resolve()

    db = SessionLocal()
    try:
        job_image = db.get(VisionJobImage, job_image_id)
        if job_image is None:
            return

        job_id = job_image.job_id
        job = db.get(VisionJob, job_id)
        if job is None:
            return

        ef = db.get(EvidenceFile, job_image.evidence_file_id)

        if ef is None or ef.kind != "image":
            job_image.status = "done"
            job_image.completed_at = datetime.now(timezone.utc)
            db.commit()
            _maybe_complete_job(db, job_id)
            return

        # Restart recovery: already successfully scanned in a prior run.
        if ef.scanned:
            job_image.status = "done"
            job_image.completed_at = datetime.now(timezone.utc)
            db.commit()
            _maybe_complete_job(db, job_id)
            return

        job_image.started_at = datetime.now(timezone.utc)
        db.commit()

        vm = db.query(VisionModel).filter_by(slug=job.model_slug, is_enabled=True).first()
        if vm is None:
            job_image.status = "error"
            job_image.error_message = f"unknown or disabled model: {job.model_slug}"
            job_image.completed_at = datetime.now(timezone.utc)
            db.commit()
            _maybe_complete_job(db, job_id)
            return

        adapter_fn = resolve_adapter(vm.adapter)
        categories = db.query(Category).order_by(Category.id).all()

        image_path = Path(ef.stored_path)
        if not image_path.is_absolute():
            image_path = (upload_base / ef.stored_path).resolve()
        if not image_path.exists():
            job_image.status = "error"
            job_image.error_message = "image file not found on disk"
            job_image.completed_at = datetime.now(timezone.utc)
            db.commit()
            _maybe_complete_job(db, job_id)
            return

        with Image.open(image_path) as img:
            orig_w, orig_h = img.size

        mime = ef.mime_type or "image/jpeg"
        image_bytes = image_path.read_bytes()

        # Downscale only if >1 MB.
        scan_w, scan_h = orig_w, orig_h
        if len(image_bytes) > 1_000_000:
            image_bytes, mime = _downscale(image_bytes)
            with Image.open(io.BytesIO(image_bytes)) as small:
                scan_w, scan_h = small.size

        # Release the pooled DB connection back to the pool before the
        # multi-second OpenRouter HTTP call; otherwise each in-flight scan pegs
        # a connection for the full API duration, exhausting the pool on bulk
        # scans. Capture scalar fields we need now; ORM objects auto-refresh
        # on attribute access after the commit.
        scan_model_slug = job.model_slug
        db.commit()

        raw_text = openrouter.call_vision(
            model_slug=scan_model_slug,
            image_bytes=image_bytes,
            mime_type=mime,
            prompt=build_scan_prompt(scan_w, scan_h),
        )
        parsed_items, placard_text = _parse_response(raw_text)

        max_line = (
            db.query(sqlfunc.max(Item.line_number)).filter(Item.matter_id == job.matter_id).scalar()
            or 0
        )
        effective_item_group_id = _resolve_effective_item_group_id(db, ef, placard_text)
        items_this_file = 0

        for raw_item in parsed_items:
            if not isinstance(raw_item, dict):
                continue
            description = str(raw_item.get("description") or "").strip()
            if not description:
                continue

            cat_id = _match_category_id(raw_item.get("category_hint"), categories)
            qty = max(1, int(raw_item.get("quantity") or 1))
            condition = str(raw_item.get("condition") or "average")
            if condition not in ("excellent", "above_average", "average", "below_average"):
                condition = "average"
            search_hint = str(raw_item.get("search_hint") or "").strip() or None

            max_line += 1
            item = Item(
                matter_id=job.matter_id,
                category_id=cat_id,
                item_group_id=effective_item_group_id,
                line_number=max_line,
                description=description,
                brand=str(raw_item.get("brand") or "").strip() or None,
                model=str(raw_item.get("model") or "").strip() or None,
                quantity=qty,
                age_years=0.0,
                condition=condition,
                rcv_unit_cents=0,
                rcv_total_cents=0,
                acv_total_cents=0,
                confirmed=False,
                search_hint=search_hint,
                notes=(
                    f"room_hint:{raw_item.get('room_hint') or ''}"
                    f"|confidence:{raw_item.get('confidence') or 'medium'}"
                ),
            )
            db.add(item)
            db.flush()

            # Scale bbox from downscaled coords back to original image coords.
            bbox = adapter_fn(raw_item.get("bounding_box"), scan_w, scan_h)
            if bbox is not None:
                left, upper, right, lower = bbox
                if scan_w != orig_w:
                    sx = orig_w / scan_w
                    sy = orig_h / scan_h
                    left = round(left * sx)
                    upper = round(upper * sy)
                    right = round(right * sx)
                    lower = round(lower * sy)
                item_crop = ItemCrop(
                    id=str(uuid.uuid4()),
                    item_id=item.id,
                    evidence_file_id=ef.id,
                    bbox_left=left,
                    bbox_upper=upper,
                    bbox_right=right,
                    bbox_lower=lower,
                )
                item_crop.crop_path = recrop_item_crop(item_crop, ef, upload_base, crop_base)
                db.add(item_crop)

            items_this_file += 1

        vr = VisionRun(
            matter_id=job.matter_id,
            evidence_file_id=ef.id,
            model=job.model_slug,
            prompt_version=SCAN_PROMPT_VERSION,
            raw_response=raw_text,
            items_created=items_this_file,
            adapter=vm.adapter,
            cost_cents_estimated=vm.prompt_image_cost_cents,
        )
        db.add(vr)
        ef.scanned = True
        job_image.status = "done"
        job_image.items_created = items_this_file
        job_image.completed_at = datetime.now(timezone.utc)
        db.commit()
        _maybe_complete_job(db, job_id)

    except openrouter.OpenRouterError as exc:
        db.rollback()
        ji = db.get(VisionJobImage, job_image_id)
        if ji:
            ji.status = "error"
            ji.error_message = f"API error — {exc.status} {exc.message}"
            ji.completed_at = datetime.now(timezone.utc)
            db.commit()
            _maybe_complete_job(db, ji.job_id)
    except httpx.TimeoutException:
        db.rollback()
        ji = db.get(VisionJobImage, job_image_id)
        if ji:
            ji.status = "error"
            ji.error_message = "timeout"
            ji.completed_at = datetime.now(timezone.utc)
            db.commit()
            _maybe_complete_job(db, ji.job_id)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception("vision scan failure for job_image %s", job_image_id)
        ji = db.get(VisionJobImage, job_image_id)
        if ji:
            ji.status = "error"
            ji.error_message = str(exc)[:500]
            ji.completed_at = datetime.now(timezone.utc)
            db.commit()
            _maybe_complete_job(db, ji.job_id)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Cost estimate (unchanged)
# ---------------------------------------------------------------------------


def estimate_cost(n_images: int, model_slug: str) -> str:
    db = SessionLocal()
    try:
        vm = db.query(VisionModel).filter_by(slug=model_slug).first()
    finally:
        db.close()
    if vm is None or vm.prompt_image_cost_cents is None:
        return "~$?"
    total_cents = n_images * vm.prompt_image_cost_cents
    return f"~${total_cents / 100:.2f}"
