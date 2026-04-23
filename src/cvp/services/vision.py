"""Vision scan service — sequential image processing via Anthropic API."""

import base64
import json
import re
import threading
import time
import uuid
from pathlib import Path

import anthropic
from PIL import Image

from cvp.config import settings
from cvp.db import SessionLocal
from cvp.models import Category, EvidenceFile, Item, ItemCrop, VisionRun
from cvp.services.vision_prompts import SCAN_PROMPT_VERSION, build_scan_prompt

# ---------------------------------------------------------------------------
# In-memory job registry (single-user local app — no persistence needed)
# ---------------------------------------------------------------------------

_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def create_job(file_ids: list[str]) -> str:
    job_id = str(uuid.uuid4())[:8]
    with _lock:
        _jobs[job_id] = {
            "status": "running",  # running | done | error
            "progress": 0,
            "total": len(file_ids),
            "items_created": 0,
            "errors": [],
        }
    return job_id


def get_job(job_id: str) -> dict | None:
    return _jobs.get(job_id)


def _update_job(job_id: str, **kwargs) -> None:
    with _lock:
        _jobs[job_id].update(kwargs)


# ---------------------------------------------------------------------------
# Category matching
# ---------------------------------------------------------------------------

def _match_category_id(hint: str | None, categories: list[Category]) -> int:
    """Best-effort fuzzy match of Vision's category_hint to a DB category id."""
    if not hint:
        return categories[-1].id  # Miscellaneous household goods

    hint_lower = hint.lower()
    # Exact or substring match
    for cat in categories:
        if hint_lower in cat.name.lower() or cat.name.lower() in hint_lower:
            return cat.id
    # Word-level match
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

def _parse_response(text: str) -> list[dict]:
    """Extract a JSON array from the model response, tolerating markdown fences."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group())
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass
    return []


# ---------------------------------------------------------------------------
# Bounding box helpers
# ---------------------------------------------------------------------------

def _parse_bbox(raw: object, img_width: int, img_height: int) -> tuple[int, int, int, int] | None:
    """
    Parse and validate a bounding_box value from the Vision response.

    Returns (left, upper, right, lower) clamped to image bounds with 15% padding,
    or None if the bbox is missing or malformed.
    """
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        left, upper, right, lower = (int(v) for v in raw)
    except (TypeError, ValueError):
        return None

    # Apply 15% generous padding
    pad_x = round((right - left) * 0.15)
    pad_y = round((lower - upper) * 0.15)
    left = max(0, left - pad_x)
    upper = max(0, upper - pad_y)
    right = min(img_width, right + pad_x)
    lower = min(img_height, lower + pad_y)

    if left >= right or upper >= lower:
        return None
    return left, upper, right, lower


# ---------------------------------------------------------------------------
# Core scan logic (called from BackgroundTasks thread)
# ---------------------------------------------------------------------------

def run_scan(job_id: str, matter_id: str, file_ids: list[str]) -> None:
    """Process each evidence file sequentially, creating Item + ItemCrop rows."""
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    upload_base = Path(settings.upload_dir).resolve()
    crop_base = Path(settings.crop_dir).resolve()

    db = SessionLocal()
    try:
        categories = db.query(Category).order_by(Category.id).all()

        for idx, file_id in enumerate(file_ids):
            try:
                ef = db.get(EvidenceFile, file_id)
                if ef is None or ef.kind != "image":
                    _update_job(job_id, progress=idx + 1)
                    continue

                image_path = (upload_base / ef.stored_path).resolve()
                if not image_path.exists():
                    _update_job(job_id, progress=idx + 1)
                    continue

                # Read image dimensions for the prompt
                with Image.open(image_path) as img:
                    img_width, img_height = img.size

                mime = ef.mime_type or "image/jpeg"
                image_data = base64.standard_b64encode(image_path.read_bytes()).decode()

                response = client.messages.create(
                    model=settings.vision_model,
                    max_tokens=4096,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": mime,
                                        "data": image_data,
                                    },
                                },
                                {"type": "text", "text": build_scan_prompt(img_width, img_height)},
                            ],
                        }
                    ],
                )

                raw_text = response.content[0].text if response.content else ""
                parsed = _parse_response(raw_text)
                items_this_file = 0

                from sqlalchemy import func as sqlfunc

                max_line = (
                    db.query(sqlfunc.max(Item.line_number))
                    .filter(Item.matter_id == matter_id)
                    .scalar()
                    or 0
                )

                # Prepare crop output directory
                crop_dir = crop_base / file_id
                crop_dir.mkdir(parents=True, exist_ok=True)

                for raw_item in parsed:
                    if not isinstance(raw_item, dict):
                        continue
                    description = str(raw_item.get("description") or "").strip()
                    if not description:
                        continue

                    cat_id = _match_category_id(raw_item.get("category_hint"), categories)
                    qty = int(raw_item.get("quantity") or 1)
                    if qty < 1:
                        qty = 1
                    condition = str(raw_item.get("condition") or "average")
                    if condition not in ("excellent", "above_average", "average", "below_average"):
                        condition = "average"

                    search_hint = str(raw_item.get("search_hint") or "").strip() or None

                    max_line += 1
                    item = Item(
                        matter_id=matter_id,
                        category_id=cat_id,
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
                    db.flush()  # get item.id before creating ItemCrop

                    # Attempt crop
                    bbox = _parse_bbox(raw_item.get("bounding_box"), img_width, img_height)
                    if bbox:
                        left, upper, right, lower = bbox
                        crop_filename = f"{item.id}.jpg"
                        crop_dest = crop_dir / crop_filename
                        with Image.open(image_path) as img:
                            cropped = img.crop((left, upper, right, lower)).convert("RGB")
                            cropped.save(crop_dest, "JPEG", quality=85)
                        crop_path = f"{file_id}/{crop_filename}"
                        item_crop = ItemCrop(
                            item_id=item.id,
                            evidence_file_id=file_id,
                            bbox_left=left,
                            bbox_upper=upper,
                            bbox_right=right,
                            bbox_lower=lower,
                            crop_path=crop_path,
                        )
                        db.add(item_crop)

                    items_this_file += 1

                vr = VisionRun(
                    matter_id=matter_id,
                    evidence_file_id=file_id,
                    model=settings.vision_model,
                    prompt_version=SCAN_PROMPT_VERSION,
                    raw_response=raw_text,
                    items_created=items_this_file,
                )
                db.add(vr)
                ef.scanned = True
                db.commit()

                with _lock:
                    _jobs[job_id]["progress"] = idx + 1
                    _jobs[job_id]["items_created"] += items_this_file

            except anthropic.APIError as exc:
                db.rollback()
                with _lock:
                    _jobs[job_id]["errors"].append(f"File {file_id}: API error — {exc}")
                    _jobs[job_id]["progress"] = idx + 1
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                with _lock:
                    _jobs[job_id]["errors"].append(f"File {file_id}: {exc}")
                    _jobs[job_id]["progress"] = idx + 1

            if idx < len(file_ids) - 1:
                time.sleep(0.5)

    finally:
        db.close()

    _update_job(job_id, status="done" if not _jobs[job_id]["errors"] else "error")


# ---------------------------------------------------------------------------
# Cost estimate (rough — shown in UI before scan)
# ---------------------------------------------------------------------------

_COST_PER_IMAGE_USD = 0.025


def estimate_cost(n_images: int) -> str:
    total = n_images * _COST_PER_IMAGE_USD
    return f"~${total:.2f}"
