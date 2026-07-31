from datetime import date, datetime

from cvp.models import Item, Matter
from cvp.services import export_fields as ef


def _ctx() -> ef.RowContext:
    item = Item(
        line_number=7,
        description="Oak dining table",
        brand="Ashley",
        model="D480",
        quantity=2,
        age_years=3.6,
        condition="average",
        retail_unit_cents=125000,
        shipping_cents=4500,
        rcv_total_cents=250000,
        acv_total_cents=180000,
        match_type="exact",
        source_retailer="Wayfair",
        source_url="https://wayfair.com/x",
        source_captured_at=datetime(2026, 5, 1, 12, 0, 0),
        needs_review=True,
        confirmed_at=datetime(2026, 5, 2, 9, 0, 0),
        notes="corner chipped",
    )
    matter = Matter(
        policyholder_name="Jane Roe",
        firm_name="Roe LLP",
        attorney_name="A. Attorney",
        carrier="StateCo",
        claim_number="CLM-1",
        policy_number="POL-9",
        loss_date=date(2025, 1, 7),
    )
    return ef.RowContext(
        item=item,
        room_name="Dining Room",
        category_name="Furniture",
        item_group_name="Placard 4",
        matter=matter,
    )


def test_registry_covers_all_expected_keys():
    expected = {
        "line_number",
        "description",
        "brand",
        "model",
        "quantity",
        "unit",
        "age",
        "condition",
        "unit_price",
        "shipping",
        "rcv_total",
        "depreciation",
        "acv_total",
        "match_type",
        "source_retailer",
        "source_url",
        "source_captured_at",
        "needs_review",
        "confirmed_at",
        "source_notes",
        "item_notes",
        "category",
        "room",
        "item_group",
        "policyholder_name",
        "firm_name",
        "attorney_name",
        "carrier",
        "claim_number",
        "policy_number",
        "loss_date",
    }
    assert set(ef.FIELD_REGISTRY) == expected


def test_money_fields_format_from_cents():
    ctx = _ctx()
    assert ef.FIELD_REGISTRY["unit_price"].render(ctx) == "1250.00"
    assert ef.FIELD_REGISTRY["shipping"].render(ctx) == "45.00"
    assert ef.FIELD_REGISTRY["rcv_total"].render(ctx) == "2500.00"
    assert ef.FIELD_REGISTRY["acv_total"].render(ctx) == "1800.00"
    assert ef.FIELD_REGISTRY["depreciation"].render(ctx) == "700.00"


def test_scalar_and_context_fields():
    ctx = _ctx()
    assert ef.FIELD_REGISTRY["line_number"].render(ctx) == "7"
    assert ef.FIELD_REGISTRY["description"].render(ctx) == "Oak dining table"
    assert ef.FIELD_REGISTRY["unit"].render(ctx) == "EA"
    assert ef.FIELD_REGISTRY["age"].render(ctx) == "4"  # round(3.6)
    assert ef.FIELD_REGISTRY["needs_review"].render(ctx) == "yes"
    assert ef.FIELD_REGISTRY["room"].render(ctx) == "Dining Room"
    assert ef.FIELD_REGISTRY["category"].render(ctx) == "Furniture"
    assert ef.FIELD_REGISTRY["item_group"].render(ctx) == "Placard 4"
    assert ef.FIELD_REGISTRY["source_captured_at"].render(ctx) == "2026-05-01"
    assert ef.FIELD_REGISTRY["loss_date"].render(ctx) == "2025-01-07"
    assert ef.FIELD_REGISTRY["policyholder_name"].render(ctx) == "Jane Roe"


def test_source_notes_matches_xactimate_blob():
    ctx = _ctx()
    # retailer | url | match_type | Shipping: $45.00
    assert ef.FIELD_REGISTRY["source_notes"].render(ctx) == (
        "Wayfair | https://wayfair.com/x | exact | Shipping: $45.00"
    )


def test_empty_optionals_render_blank():
    ctx = _ctx()
    ctx.item.brand = None
    ctx.item.source_captured_at = None
    ctx.item.needs_review = False
    assert ef.FIELD_REGISTRY["brand"].render(ctx) == ""
    assert ef.FIELD_REGISTRY["source_captured_at"].render(ctx) == ""
    assert ef.FIELD_REGISTRY["needs_review"].render(ctx) == "no"


def test_field_groups_ordered_and_complete():
    groups = ef.field_groups()
    assert list(groups) == ["Item", "Money", "Source", "Context", "Matter"]
    flat = [f.key for fields in groups.values() for f in fields]
    assert set(flat) == set(ef.FIELD_REGISTRY)
