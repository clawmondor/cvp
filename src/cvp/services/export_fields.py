"""Pure field registry for custom CSV exports. No DB access — values come from RowContext."""

from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class RowContext:
    """Everything needed to render one CSV row for one item."""

    item: object  # cvp.models.Item
    room_name: str
    category_name: str
    item_group_name: str
    matter: object  # cvp.models.Matter
    crop_image_url: str = ""  # precomputed public URL of the item's crop (blank if none)


@dataclass(frozen=True)
class ExportField:
    key: str
    default_header: str
    group: str
    render: Callable[[RowContext], str]


def _dollars(cents: int) -> str:
    return f"{(cents or 0) / 100:.2f}"


def _date(value) -> str:
    return (
        value.date().isoformat()
        if hasattr(value, "date") and value
        else (value.isoformat() if value else "")
    )


def _source_notes(ctx: RowContext) -> str:
    item = ctx.item
    parts = [item.source_retailer or "", item.source_url or "", item.match_type or ""]
    if item.shipping_cents:
        parts.append(f"Shipping: ${_dollars(item.shipping_cents)}")
    return " | ".join(p for p in parts if p)


# (group, key, default_header, render)
_FIELDS: list[tuple[str, str, str, Callable[[RowContext], str]]] = [
    ("Item", "line_number", "LineItem", lambda c: str(c.item.line_number)),
    ("Item", "description", "Description", lambda c: c.item.description or ""),
    ("Item", "brand", "Brand", lambda c: c.item.brand or ""),
    ("Item", "model", "Model", lambda c: c.item.model or ""),
    ("Item", "quantity", "Qty", lambda c: str(c.item.quantity)),
    ("Item", "unit", "Unit", lambda c: "EA"),
    ("Item", "age", "Age", lambda c: str(int(round(c.item.age_years)))),
    ("Item", "condition", "Condition", lambda c: c.item.condition or ""),
    ("Money", "unit_price", "UnitPrice", lambda c: _dollars(c.item.retail_unit_cents)),
    ("Money", "shipping", "Shipping", lambda c: _dollars(c.item.shipping_cents)),
    ("Money", "rcv_total", "Total", lambda c: _dollars(c.item.rcv_total_cents)),
    (
        "Money",
        "depreciation",
        "Depreciation",
        lambda c: _dollars(c.item.rcv_total_cents - c.item.acv_total_cents),
    ),
    ("Money", "acv_total", "ACV", lambda c: _dollars(c.item.acv_total_cents)),
    ("Source", "match_type", "MatchType", lambda c: c.item.match_type or ""),
    ("Source", "source_retailer", "Retailer", lambda c: c.item.source_retailer or ""),
    ("Source", "source_url", "SourceURL", lambda c: c.item.source_url or ""),
    (
        "Source",
        "source_captured_at",
        "SourceCapturedAt",
        lambda c: _date(c.item.source_captured_at),
    ),
    ("Source", "needs_review", "NeedsReview", lambda c: "yes" if c.item.needs_review else "no"),
    ("Source", "confirmed_at", "ConfirmedAt", lambda c: _date(c.item.confirmed_at)),
    ("Source", "source_notes", "Notes", _source_notes),
    ("Source", "item_notes", "ItemNotes", lambda c: c.item.notes or ""),
    ("Source", "crop_image_url", "CropImageURL", lambda c: c.crop_image_url),
    ("Context", "category", "Category", lambda c: c.category_name),
    ("Context", "room", "Room", lambda c: c.room_name),
    ("Context", "item_group", "Group", lambda c: c.item_group_name),
    ("Matter", "policyholder_name", "Policyholder", lambda c: c.matter.policyholder_name or ""),
    ("Matter", "firm_name", "Firm", lambda c: c.matter.firm_name or ""),
    ("Matter", "attorney_name", "Attorney", lambda c: c.matter.attorney_name or ""),
    ("Matter", "carrier", "Carrier", lambda c: c.matter.carrier or ""),
    ("Matter", "claim_number", "ClaimNumber", lambda c: c.matter.claim_number or ""),
    ("Matter", "policy_number", "PolicyNumber", lambda c: c.matter.policy_number or ""),
    ("Matter", "loss_date", "LossDate", lambda c: _date(c.matter.loss_date)),
]

FIELD_REGISTRY: dict[str, ExportField] = {
    key: ExportField(key=key, default_header=header, group=group, render=render)
    for (group, key, header, render) in _FIELDS
}


def field_groups() -> "OrderedDict[str, list[ExportField]]":
    """Registry fields grouped by UI section, preserving definition order."""
    groups: OrderedDict[str, list[ExportField]] = OrderedDict()
    for f in FIELD_REGISTRY.values():
        groups.setdefault(f.group, []).append(f)
    return groups
