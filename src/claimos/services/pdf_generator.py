"""PDF generation via WeasyPrint — renders the same template as the HTML preview."""

from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import selectinload
from weasyprint import HTML

from claimos.config import settings
from claimos.db import SessionLocal
from claimos.models import Category, Claim


def _build_preview_context(claim: Claim, db) -> dict:
    """Build the same context dict used by the HTML preview route."""
    confirmed_items = sorted(
        [i for i in claim.items if i.confirmed and not i.excluded],
        key=lambda i: i.line_number,
    )
    total_rcv_cents = sum(i.rcv_total_cents for i in confirmed_items)
    total_acv_cents = sum(i.acv_total_cents for i in confirmed_items)

    room_map = {r.id: r.name for r in claim.rooms}

    all_categories = db.query(Category).order_by(Category.id).all()
    cat_map = {c.id: c.name for c in all_categories}
    cat_obj_map = {c.id: c for c in all_categories}

    cat_counts: Counter = Counter(i.category_id for i in confirmed_items)
    categories_used = sorted(
        [(cat_obj_map[cid], count) for cid, count in cat_counts.items() if cid in cat_obj_map],
        key=lambda x: x[0].id,
    )

    room_rcv: dict = defaultdict(int)
    room_acv: dict = defaultdict(int)
    room_count: Counter = Counter()
    for item in confirmed_items:
        key = item.room_id or "__unassigned__"
        room_rcv[key] += item.rcv_total_cents
        room_acv[key] += item.acv_total_cents
        room_count[key] += 1

    by_room = []
    for room in sorted(claim.rooms, key=lambda r: r.sort_order):
        if room.id in room_count:
            by_room.append(
                dict(
                    room_name=room.name,
                    count=room_count[room.id],
                    rcv=room_rcv[room.id],
                    acv=room_acv[room.id],
                )
            )
    if "__unassigned__" in room_count:
        by_room.append(
            dict(
                room_name="Unassigned",
                count=room_count["__unassigned__"],
                rcv=room_rcv["__unassigned__"],
                acv=room_acv["__unassigned__"],
            )
        )

    return {
        "claim": claim,
        "confirmed_items": confirmed_items,
        "total_items": len(confirmed_items),
        "total_rcv_cents": total_rcv_cents,
        "total_acv_cents": total_acv_cents,
        "evidence_files": claim.evidence_files,
        "room_map": room_map,
        "cat_map": cat_map,
        "categories_used": categories_used,
        "by_room": by_room,
        "report_date": datetime.now().strftime("%B %-d, %Y"),
        "company_name": settings.company_name,
        "company_address": settings.company_address,
        "company_email": settings.company_email,
        "company_phone": settings.company_phone,
    }


def generate_pdf(claim_id: str) -> Path:
    """Render the report to PDF and return the output path."""
    from jinja2 import Environment, FileSystemLoader

    template_dir = Path(__file__).parent.parent / "templates" / "report"
    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=True)

    db = SessionLocal()
    try:
        claim = (
            db.query(Claim)
            .options(
                selectinload(Claim.items),
                selectinload(Claim.evidence_files),
                selectinload(Claim.rooms),
            )
            .filter(Claim.id == claim_id)
            .first()
        )
        if claim is None:
            raise ValueError(f"Claim {claim_id} not found")

        context = _build_preview_context(claim, db)
    finally:
        db.close()

    html_str = env.get_template("pdf.html").render(**context)

    export_dir = Path(settings.export_dir) / claim_id
    export_dir.mkdir(parents=True, exist_ok=True)
    datestamp = datetime.now().strftime("%Y%m%d")
    out_path = export_dir / f"contents_report_{datestamp}.pdf"

    HTML(string=html_str, base_url=str(template_dir)).write_pdf(str(out_path))
    return out_path
