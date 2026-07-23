"""Xactimate-compatible CSV export."""

import csv
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import selectinload

from cvp.config import settings
from cvp.db import SessionLocal
from cvp.models import Category, Matter

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
                source_notes = " | ".join(
                    filter(
                        None,
                        [
                            item.source_retailer or "",
                            item.source_url or "",
                            item.match_type or "",
                        ],
                    )
                )
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
