"""Xactimate-compatible CSV export."""

import csv
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import selectinload

from cvp.config import settings
from cvp.db import SessionLocal
from cvp.models import Category, ExportTemplate, Item, ItemGroup, Matter
from cvp.services.export_fields import FIELD_REGISTRY, RowContext
from cvp.services.serp import build_crop_url

# Exact column names required for Xactimate import compatibility
CSV_HEADERS = [
    "LineItem",
    "Description",
    "Qty",
    "Unit",
    "UnitPrice",
    "Total",
    "Depreciation",
    "ACV",
    "Category",
    "Room",
    "Age",
    "Condition",
    "Notes",
]


def _dollars(cents: int) -> str:
    return f"{cents / 100:.2f}"


def generate_csv(matter_id: str) -> Path:
    """Write the Xactimate CSV and return the output path."""
    db = SessionLocal()
    try:
        matter = (
            db.query(Matter)
            .options(selectinload(Matter.items), selectinload(Matter.rooms))
            .filter(Matter.id == matter_id)
            .first()
        )
        if matter is None:
            raise ValueError(f"Matter {matter_id} not found")

        room_map = {r.id: r.name for r in matter.rooms}

        all_categories = db.query(Category).order_by(Category.id).all()
        cat_map = {c.id: c.name for c in all_categories}

        confirmed_items = sorted(
            [i for i in matter.items if i.confirmed and not i.excluded],
            key=lambda i: i.line_number,
        )

        export_dir = Path(settings.export_dir) / matter_id
        export_dir.mkdir(parents=True, exist_ok=True)
        datestamp = datetime.now().strftime("%Y%m%d")
        out_path = export_dir / f"contents_xactimate_{datestamp}.csv"

        with open(out_path, "w", newline="", encoding="utf-8") as f:
            # Attorney work product header
            f.write(
                f"# Confidential — Attorney Work Product | "
                f"Matter: {matter.policyholder_name} | "
                f"Generated: {datetime.now().strftime('%Y-%m-%d')}\n"
            )
            writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
            writer.writeheader()

            for item in confirmed_items:
                dep_cents = item.rcv_total_cents - item.acv_total_cents
                note_parts = [
                    item.source_retailer or "",
                    item.source_url or "",
                    item.match_type or "",
                ]
                if item.shipping_cents:
                    note_parts.append(f"Shipping: ${_dollars(item.shipping_cents)}")
                source_notes = " | ".join(filter(None, note_parts))
                writer.writerow(
                    {
                        "LineItem": item.line_number,
                        "Description": item.description,
                        "Qty": item.quantity,
                        "Unit": "EA",
                        "UnitPrice": _dollars(item.retail_unit_cents),
                        "Total": _dollars(item.rcv_total_cents),
                        "Depreciation": _dollars(dep_cents),
                        "ACV": _dollars(item.acv_total_cents),
                        "Category": cat_map.get(item.category_id, ""),
                        "Room": room_map.get(item.room_id or "", "Unassigned"),
                        "Age": int(round(item.age_years)),
                        "Condition": item.condition,
                        "Notes": source_notes,
                    }
                )
    finally:
        db.close()

    return out_path


def _slugify(name: str) -> str:
    keep = [c.lower() if c.isalnum() else "-" for c in name.strip()]
    slug = "".join(keep).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "export"


def generate_custom_csv(matter_id: str, template_id: str) -> Path:
    """Write a custom-template CSV and return the output path."""
    db = SessionLocal()
    try:
        matter = (
            db.query(Matter)
            .options(
                selectinload(Matter.items).selectinload(Item.crops),
                selectinload(Matter.rooms),
            )
            .filter(Matter.id == matter_id)
            .first()
        )
        if matter is None:
            raise ValueError(f"Matter {matter_id} not found")

        template = db.query(ExportTemplate).filter(ExportTemplate.id == template_id).first()
        if template is None:
            raise ValueError(f"Template {template_id} not found")
        if template.group_id != matter.owner_group_id:
            raise ValueError("Template does not belong to this matter's group")

        columns = sorted(template.columns, key=lambda c: c.position)

        room_map = {r.id: r.name for r in matter.rooms}
        cat_map = {c.id: c.name for c in db.query(Category).all()}
        group_map = {
            g.id: g.name for g in db.query(ItemGroup).filter(ItemGroup.matter_id == matter_id)
        }

        def _keep(item: Item) -> bool:
            if not item.confirmed:
                return False
            if item.excluded and not template.include_excluded:
                return False
            if item.needs_review and not template.include_needs_review:
                return False
            return True

        rows = [i for i in matter.items if _keep(i)]
        sort_key = {
            "line_number": lambda i: i.line_number,
            "room": lambda i: room_map.get(i.room_id or "", "").lower(),
            "category": lambda i: cat_map.get(i.category_id, "").lower(),
            "description": lambda i: (i.description or "").lower(),
        }[template.sort_field]
        rows.sort(key=sort_key)

        export_dir = Path(settings.export_dir) / matter_id
        export_dir.mkdir(parents=True, exist_ok=True)
        # Include time (HHMM) so multiple exports on the same day don't clobber each other.
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        out_path = export_dir / f"contents_{_slugify(template.name)}_{timestamp}.csv"

        headers = [
            (c.header_label or (FIELD_REGISTRY[c.field_key].default_header if c.field_key else ""))
            for c in columns
        ]

        with open(out_path, "w", newline="", encoding="utf-8") as f:
            f.write(
                f"# Confidential — Attorney Work Product | "
                f"Matter: {matter.policyholder_name} | "
                f"Generated: {datetime.now().strftime('%Y-%m-%d')}\n"
            )
            writer = csv.writer(f)
            writer.writerow(headers)
            for item in rows:
                crop_url = ""
                for crop in item.crops:
                    url = build_crop_url(crop)
                    if url:
                        crop_url = url
                        break
                ctx = RowContext(
                    item=item,
                    room_name=room_map.get(item.room_id or "", "Unassigned"),
                    category_name=cat_map.get(item.category_id, ""),
                    item_group_name=group_map.get(item.item_group_id or "", ""),
                    matter=matter,
                    crop_image_url=crop_url,
                )
                writer.writerow(
                    [
                        c.static_value
                        if c.field_key is None
                        else FIELD_REGISTRY[c.field_key].render(ctx)
                        for c in columns
                    ]
                )
    finally:
        db.close()

    return out_path
