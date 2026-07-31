# Custom CSV Export Templates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let any group member define named, group-shared CSV export templates (chosen columns, order, renamed headers, static columns, row-scope toggles) and run them from the export tab, alongside the existing PDF and Xactimate exports.

**Architecture:** Two new tables (`export_templates` + ordered `export_template_columns`) hold the configuration. A pure, unit-tested field registry (`services/export_fields.py`) owns value extraction/formatting. `services/csv_export.py` gains `generate_custom_csv`. A thin service (`services/export_templates.py`) owns validation + CRUD. A new router exposes template CRUD + a builder page; `routers/exports.py` gains one custom-export endpoint. The builder UI reorders columns with ↑/↓ buttons via a delegated `app.js` listener (no inline JS, no drag library, CSP-clean).

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.x, Alembic, Jinja2, HTMX, Tailwind (CDN), pytest, ruff. Package manager `uv`.

## Global Constraints

- **Never modify the Xactimate export or its 13 immutable headers.** Custom exports are an entirely separate code path.
- **Currency is integer cents everywhere; format to dollars only at the export layer** (`cents/100:.2f`). Never store or compute currency as a float.
- **Every custom CSV writes the Confidential comment line first:** `# Confidential — Attorney Work Product | Matter: {policyholder_name} | Generated: {YYYY-MM-DD}`. Not configurable.
- **Templates are group-scoped.** Scope always derives from `matter.owner_group_id`, never from a client-supplied group id. All template queries filter on both `id` and `group_id` (prevents cross-group IDOR).
- **RBAC (via `require_matter_role`, hierarchy viewer<editor<contributor<manager):** list templates + builder page = `viewer`; create/update/delete templates = `contributor`; run a custom export = `manager` (parity with the existing PDF/CSV export endpoints, which use `manager`).
- **No inline JS event handlers** (`onclick=` etc.). CSP `script-src` has no `unsafe-inline`. Wire interactivity via `data-*` attributes + a delegated `document.addEventListener('click', …)` listener in `src/cvp/static/app.js` (existing pattern at lines ~346–370).
- **Type hints everywhere; modern syntax** (`list[str]`, `X | None`). UUIDs as strings. Timestamps as tz-aware UTC.
- **Run `uv run ruff format .` then `uv run ruff format --check .` before every commit** (CI enforces; line length 100). Run `uv run ruff check .` too.
- **Tests live under `tests/` mirroring `src/cvp/`.** Vision is always mocked; these tasks touch no vision code.
- Commands: `uv run pytest`, `uv run alembic revision --autogenerate -m "msg"`, `uv run alembic upgrade head`.

---

## File Structure

- Create `src/cvp/services/export_fields.py` — pure field registry (`RowContext`, `ExportField`, `FIELD_REGISTRY`, `field_groups`, `_dollars`).
- Modify `src/cvp/models.py` — add `ExportTemplate`, `ExportTemplateColumn`.
- Create `migrations/versions/<rev>_export_templates.py` — Alembic migration for the two tables.
- Modify `src/cvp/services/csv_export.py` — add `generate_custom_csv`.
- Create `src/cvp/services/export_templates.py` — `ColumnSpec`, validation, CRUD helpers, `xactimate_default_columns`.
- Create `src/cvp/routers/export_templates.py` — CRUD + builder page + HTMX partials.
- Modify `src/cvp/routers/exports.py` — add `POST …/exports/custom`.
- Modify `src/cvp/main.py` — register the new router.
- Create `src/cvp/templates/export_templates_builder.html` — builder page.
- Create `src/cvp/templates/_export_template_row.html` — a single column-row partial (used as a `<template>` clone source and for server renders).
- Modify `src/cvp/templates/_tab_export.html` — add the "Custom Export" card (dropdown + Export button + Manage link).
- Modify `src/cvp/static/app.js` — delegated add/move/remove/serialize listeners for the builder.
- Tests: `tests/services/test_export_fields.py`, `tests/services/test_csv_export_custom.py`, `tests/services/test_export_templates_service.py`, `tests/routers/test_export_templates.py`.

---

### Task 1: Data model + migration

**Files:**
- Modify: `src/cvp/models.py` (add two classes near the other models, after `Item`)
- Create: `migrations/versions/<rev>_export_templates.py` (via autogenerate)
- Test: none new (schema exercised by later tasks); verify via `alembic upgrade head`

**Interfaces:**
- Produces: `ExportTemplate(id, group_id, name, description, created_by_id, include_needs_review, include_excluded, sort_field, created_at, updated_at, columns: list[ExportTemplateColumn])`; `ExportTemplateColumn(id, template_id, position, field_key, header_label, static_value)`. `ExportTemplate.columns` is ordered by `position` and cascades delete.

- [ ] **Step 1: Add the models**

In `src/cvp/models.py`, after the `Item` class, add:

```python
class ExportTemplate(Base):
    """A group-shared custom CSV export layout."""

    __tablename__ = "export_templates"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    group_id: Mapped[str] = mapped_column(String, ForeignKey("groups.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, default="")
    created_by_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id"), nullable=True
    )
    include_needs_review: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="0"
    )
    include_excluded: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="0"
    )
    sort_field: Mapped[str] = mapped_column(
        String, default="line_number", nullable=False, server_default="line_number"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    columns: Mapped[list["ExportTemplateColumn"]] = relationship(
        "ExportTemplateColumn",
        back_populates="template",
        cascade="all, delete-orphan",
        order_by="ExportTemplateColumn.position",
    )


class ExportTemplateColumn(Base):
    """One ordered column in an ExportTemplate. Either a registry field or a static value."""

    __tablename__ = "export_template_columns"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    template_id: Mapped[str] = mapped_column(
        String, ForeignKey("export_templates.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    field_key: Mapped[str | None] = mapped_column(String, nullable=True)
    header_label: Mapped[str | None] = mapped_column(String, nullable=True)
    static_value: Mapped[str | None] = mapped_column(String, nullable=True)

    template: Mapped["ExportTemplate"] = relationship(
        "ExportTemplate", back_populates="columns"
    )
```

- [ ] **Step 2: Autogenerate the migration**

Run: `uv run alembic revision --autogenerate -m "export templates"`
Then open the new file in `migrations/versions/` and confirm `upgrade()` creates both tables with the FKs, the `server_default` values, and `ondelete="CASCADE"` on `export_template_columns.template_id`. If autogenerate omitted the `ondelete`, add `ondelete="CASCADE"` to that `ForeignKeyConstraint` by hand. Confirm `downgrade()` drops both tables (columns table first).

- [ ] **Step 3: Apply and verify**

Run: `uv run alembic upgrade head`
Expected: no error. Then run: `uv run alembic downgrade -1 && uv run alembic upgrade head`
Expected: clean down + up (proves `downgrade()` works).

- [ ] **Step 4: Format + lint**

Run: `uv run ruff format . && uv run ruff format --check . && uv run ruff check .`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/cvp/models.py migrations/versions/
git commit -m "feat(exports): export_templates + export_template_columns models and migration"
```

---

### Task 2: Field registry (pure, TDD)

**Files:**
- Create: `src/cvp/services/export_fields.py`
- Test: `tests/services/test_export_fields.py`

**Interfaces:**
- Consumes: `cvp.models.Item`, `cvp.models_auth`-independent (no DB).
- Produces:
  - `RowContext` dataclass: `item: Item`, `room_name: str`, `category_name: str`, `item_group_name: str`, `matter` (the `Matter` ORM object).
  - `ExportField` dataclass (frozen): `key: str`, `default_header: str`, `group: str`, `render: Callable[[RowContext], str]`.
  - `FIELD_REGISTRY: dict[str, ExportField]` keyed by `field.key`.
  - `field_groups() -> dict[str, list[ExportField]]` — insertion-ordered groups (`"Item"`, `"Money"`, `"Source"`, `"Context"`, `"Matter"`) each mapping to its fields, for UI catalog rendering.
  - `_dollars(cents: int) -> str`.

- [ ] **Step 1: Write the failing test**

Create `tests/services/test_export_fields.py`:

```python
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
        "line_number", "description", "brand", "model", "quantity", "unit", "age",
        "condition", "unit_price", "shipping", "rcv_total", "depreciation", "acv_total",
        "match_type", "source_retailer", "source_url", "source_captured_at",
        "needs_review", "confirmed_at", "source_notes", "item_notes",
        "category", "room", "item_group",
        "policyholder_name", "firm_name", "attorney_name", "carrier",
        "claim_number", "policy_number", "loss_date",
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/services/test_export_fields.py -v`
Expected: FAIL (module `cvp.services.export_fields` not found).

- [ ] **Step 3: Implement the registry**

Create `src/cvp/services/export_fields.py`:

```python
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


@dataclass(frozen=True)
class ExportField:
    key: str
    default_header: str
    group: str
    render: Callable[[RowContext], str]


def _dollars(cents: int) -> str:
    return f"{(cents or 0) / 100:.2f}"


def _date(value) -> str:
    return value.date().isoformat() if hasattr(value, "date") and value else (
        value.isoformat() if value else ""
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
    ("Source", "source_captured_at", "SourceCapturedAt", lambda c: _date(c.item.source_captured_at)),
    ("Source", "needs_review", "NeedsReview", lambda c: "yes" if c.item.needs_review else "no"),
    ("Source", "confirmed_at", "ConfirmedAt", lambda c: _date(c.item.confirmed_at)),
    ("Source", "source_notes", "Notes", _source_notes),
    ("Source", "item_notes", "ItemNotes", lambda c: c.item.notes or ""),
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
```

Note: `_date` handles both `datetime` (has `.date()`) and `date` (isoformat directly). For a `date`, `hasattr(value, "date")` is False, so it falls to `value.isoformat()`. Verify this against `test_scalar_and_context_fields` (`loss_date` is a `date`) and `source_captured_at` (a `datetime`).

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/services/test_export_fields.py -v`
Expected: PASS (all 7 tests).

- [ ] **Step 5: Format, lint, commit**

```bash
uv run ruff format . && uv run ruff format --check . && uv run ruff check .
git add src/cvp/services/export_fields.py tests/services/test_export_fields.py
git commit -m "feat(exports): pure field registry for custom CSV exports"
```

---

### Task 3: Template service — validation + CRUD + Xactimate defaults (TDD)

**Files:**
- Create: `src/cvp/services/export_templates.py`
- Test: `tests/services/test_export_templates_service.py`

**Interfaces:**
- Consumes: `FIELD_REGISTRY` (Task 2), `ExportTemplate`/`ExportTemplateColumn` (Task 1).
- Produces:
  - `ColumnSpec` dataclass: `field_key: str | None`, `header_label: str | None`, `static_value: str | None`.
  - `SORT_FIELDS: tuple[str, ...] = ("line_number", "room", "category", "description")`.
  - `validate(name: str, sort_field: str, columns: list[ColumnSpec]) -> None` — raises `ValueError` on bad input.
  - `list_templates(db, group_id: str) -> list[ExportTemplate]`.
  - `get_template(db, template_id: str, group_id: str) -> ExportTemplate | None`.
  - `create_template(db, *, group_id, created_by_id, name, description, include_needs_review, include_excluded, sort_field, columns: list[ColumnSpec]) -> ExportTemplate`.
  - `update_template(db, template, *, name, description, include_needs_review, include_excluded, sort_field, columns: list[ColumnSpec]) -> ExportTemplate`.
  - `delete_template(db, template) -> None`.
  - `xactimate_default_columns() -> list[ColumnSpec]`.

- [ ] **Step 1: Write the failing test**

Create `tests/services/test_export_templates_service.py`:

```python
import pytest

from cvp.services import export_templates as svc


def test_validate_rejects_empty_name():
    with pytest.raises(ValueError):
        svc.validate("", "line_number", [svc.ColumnSpec("description", None, None)])


def test_validate_rejects_no_columns():
    with pytest.raises(ValueError):
        svc.validate("T", "line_number", [])


def test_validate_rejects_unknown_field_key():
    with pytest.raises(ValueError):
        svc.validate("T", "line_number", [svc.ColumnSpec("nope", None, None)])


def test_validate_rejects_bad_sort_field():
    with pytest.raises(ValueError):
        svc.validate("T", "bogus", [svc.ColumnSpec("description", None, None)])


def test_validate_rejects_column_with_both_field_and_static():
    with pytest.raises(ValueError):
        svc.validate("T", "line_number", [svc.ColumnSpec("description", None, "x")])


def test_validate_rejects_static_without_header():
    with pytest.raises(ValueError):
        svc.validate("T", "line_number", [svc.ColumnSpec(None, "", "x")])


def test_validate_accepts_valid_mix():
    svc.validate(
        "Carrier packet",
        "room",
        [
            svc.ColumnSpec("line_number", None, None),
            svc.ColumnSpec("description", "Item", None),
            svc.ColumnSpec(None, "Firm", "Roe LLP"),
        ],
    )


def test_xactimate_defaults_are_valid_and_ordered():
    cols = svc.xactimate_default_columns()
    assert [c.field_key for c in cols][:3] == ["line_number", "description", "quantity"]
    svc.validate("Xactimate", "line_number", cols)  # must not raise


def test_create_update_delete_roundtrip(db_session):
    group_id = "g1"
    t = svc.create_template(
        db_session,
        group_id=group_id,
        created_by_id="u1",
        name="Packet",
        description="",
        include_needs_review=False,
        include_excluded=False,
        sort_field="line_number",
        columns=[svc.ColumnSpec("description", None, None), svc.ColumnSpec(None, "Firm", "Roe")],
    )
    assert t.id
    assert [c.position for c in t.columns] == [0, 1]

    got = svc.get_template(db_session, t.id, group_id)
    assert got is not None
    assert svc.get_template(db_session, t.id, "other-group") is None  # cross-group isolation

    svc.update_template(
        db_session,
        t,
        name="Packet v2",
        description="d",
        include_needs_review=True,
        include_excluded=True,
        sort_field="room",
        columns=[svc.ColumnSpec("room", None, None)],
    )
    got = svc.get_template(db_session, t.id, group_id)
    assert got.name == "Packet v2"
    assert got.include_needs_review is True
    assert [c.field_key for c in got.columns] == ["room"]  # old columns replaced

    svc.delete_template(db_session, got)
    assert svc.get_template(db_session, t.id, group_id) is None
```

If a `db_session` fixture does not already exist in `tests/conftest.py`, check first: run `grep -rn "def db_session\|@pytest.fixture" tests/conftest.py`. If absent, add this fixture to `tests/conftest.py` (in-memory SQLite, all tables created from `Base.metadata`):

```python
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from cvp.models import Base
import cvp.models_auth  # noqa: F401  ensure auth tables register on Base


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
```
(If `models_auth` uses a different `Base`, import whichever `Base` both models share; the `groups`/`users` FKs must exist for `create_all` to succeed. Confirm with `grep -n "class Base\|Base)" src/cvp/models_auth.py`.)

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/services/test_export_templates_service.py -v`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement the service**

Create `src/cvp/services/export_templates.py`:

```python
"""Validation and CRUD for custom CSV export templates."""

from dataclasses import dataclass

from sqlalchemy.orm import Session, selectinload

from cvp.models import ExportTemplate, ExportTemplateColumn
from cvp.services.export_fields import FIELD_REGISTRY

SORT_FIELDS: tuple[str, ...] = ("line_number", "room", "category", "description")


@dataclass
class ColumnSpec:
    field_key: str | None
    header_label: str | None
    static_value: str | None


def validate(name: str, sort_field: str, columns: list[ColumnSpec]) -> None:
    if not name or not name.strip():
        raise ValueError("Template name is required.")
    if sort_field not in SORT_FIELDS:
        raise ValueError(f"Invalid sort field: {sort_field!r}")
    if not columns:
        raise ValueError("A template needs at least one column.")
    for i, col in enumerate(columns):
        is_field = col.field_key is not None
        is_static = col.static_value is not None
        if is_field == is_static:
            raise ValueError(f"Column {i}: set exactly one of field_key / static_value.")
        if is_field and col.field_key not in FIELD_REGISTRY:
            raise ValueError(f"Column {i}: unknown field {col.field_key!r}.")
        if is_static and not (col.header_label and col.header_label.strip()):
            raise ValueError(f"Column {i}: static columns require a header label.")


def list_templates(db: Session, group_id: str) -> list[ExportTemplate]:
    return (
        db.query(ExportTemplate)
        .options(selectinload(ExportTemplate.columns))
        .filter(ExportTemplate.group_id == group_id)
        .order_by(ExportTemplate.name)
        .all()
    )


def get_template(db: Session, template_id: str, group_id: str) -> ExportTemplate | None:
    return (
        db.query(ExportTemplate)
        .options(selectinload(ExportTemplate.columns))
        .filter(ExportTemplate.id == template_id, ExportTemplate.group_id == group_id)
        .first()
    )


def _apply_columns(template: ExportTemplate, columns: list[ColumnSpec]) -> None:
    template.columns.clear()  # orphan-delete removes old rows
    for pos, spec in enumerate(columns):
        template.columns.append(
            ExportTemplateColumn(
                position=pos,
                field_key=spec.field_key,
                header_label=(spec.header_label or None),
                static_value=spec.static_value,
            )
        )


def create_template(
    db: Session,
    *,
    group_id: str,
    created_by_id: str | None,
    name: str,
    description: str,
    include_needs_review: bool,
    include_excluded: bool,
    sort_field: str,
    columns: list[ColumnSpec],
) -> ExportTemplate:
    validate(name, sort_field, columns)
    template = ExportTemplate(
        group_id=group_id,
        created_by_id=created_by_id,
        name=name.strip(),
        description=description or "",
        include_needs_review=include_needs_review,
        include_excluded=include_excluded,
        sort_field=sort_field,
    )
    _apply_columns(template, columns)
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


def update_template(
    db: Session,
    template: ExportTemplate,
    *,
    name: str,
    description: str,
    include_needs_review: bool,
    include_excluded: bool,
    sort_field: str,
    columns: list[ColumnSpec],
) -> ExportTemplate:
    validate(name, sort_field, columns)
    template.name = name.strip()
    template.description = description or ""
    template.include_needs_review = include_needs_review
    template.include_excluded = include_excluded
    template.sort_field = sort_field
    _apply_columns(template, columns)
    db.commit()
    db.refresh(template)
    return template


def delete_template(db: Session, template: ExportTemplate) -> None:
    db.delete(template)
    db.commit()


def xactimate_default_columns() -> list[ColumnSpec]:
    """Column layout mirroring the fixed Xactimate CSV, as a starting point."""
    keys = [
        "line_number", "description", "quantity", "unit", "unit_price", "rcv_total",
        "depreciation", "acv_total", "category", "room", "age", "condition", "source_notes",
    ]
    return [ColumnSpec(field_key=k, header_label=None, static_value=None) for k in keys]
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/services/test_export_templates_service.py -v`
Expected: PASS (all tests, including the `db_session` roundtrip).

- [ ] **Step 5: Format, lint, commit**

```bash
uv run ruff format . && uv run ruff format --check . && uv run ruff check .
git add src/cvp/services/export_templates.py tests/services/test_export_templates_service.py tests/conftest.py
git commit -m "feat(exports): export template validation + CRUD service"
```

---

### Task 4: Custom CSV generation (TDD)

**Files:**
- Modify: `src/cvp/services/csv_export.py` (add `generate_custom_csv`; do NOT touch `generate_csv` or `CSV_HEADERS`)
- Test: `tests/services/test_csv_export_custom.py`

**Interfaces:**
- Consumes: `FIELD_REGISTRY`, `RowContext` (Task 2); `ExportTemplate` + `get_template` semantics; `ColumnSpec` unused here (columns read from ORM).
- Produces: `generate_custom_csv(matter_id: str, template_id: str) -> Path`.

- [ ] **Step 1: Write the failing test**

Create `tests/services/test_csv_export_custom.py`:

```python
import csv

from cvp.models import (
    Category,
    ExportTemplate,
    ExportTemplateColumn,
    Item,
    Matter,
    Room,
)
from cvp.services import csv_export


def _seed(db, tmp_path, monkeypatch, *, include_excluded=False, include_needs_review=False,
          sort_field="line_number"):
    monkeypatch.setattr(csv_export.settings, "export_dir", str(tmp_path))
    db.add(Category(id=1, name="Furniture"))
    matter = Matter(id="m1", policyholder_name="Jane Roe", firm_name="Roe LLP",
                    owner_group_id="g1")
    room = Room(id="r1", matter_id="m1", name="Den")
    db.add_all([matter, room])
    db.add_all([
        Item(id="i1", matter_id="m1", room_id="r1", category_id=1, line_number=1,
             description="Sofa", quantity=1, retail_unit_cents=100000, rcv_total_cents=100000,
             acv_total_cents=60000, confirmed=True, excluded=False, needs_review=False),
        Item(id="i2", matter_id="m1", room_id="r1", category_id=1, line_number=2,
             description="Lamp", quantity=1, retail_unit_cents=5000, rcv_total_cents=5000,
             acv_total_cents=3000, confirmed=True, excluded=True, needs_review=False),
        Item(id="i3", matter_id="m1", room_id="r1", category_id=1, line_number=3,
             description="Rug", quantity=1, retail_unit_cents=20000, rcv_total_cents=20000,
             acv_total_cents=12000, confirmed=True, excluded=False, needs_review=True),
    ])
    t = ExportTemplate(id="t1", group_id="g1", name="Packet", sort_field=sort_field,
                       include_excluded=include_excluded,
                       include_needs_review=include_needs_review)
    t.columns = [
        ExportTemplateColumn(position=0, field_key="line_number", header_label=None),
        ExportTemplateColumn(position=1, field_key="description", header_label="Item"),
        ExportTemplateColumn(position=2, field_key="acv_total", header_label=None),
        ExportTemplateColumn(position=3, field_key=None, header_label="Firm", static_value="Roe LLP"),
    ]
    db.add(t)
    db.commit()


def _read(path):
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    assert lines[0].startswith("# Confidential — Attorney Work Product")
    reader = csv.reader(lines[1:])
    return list(reader)


def test_custom_csv_columns_headers_and_default_filter(db_session, tmp_path, monkeypatch):
    _seed(db_session, tmp_path, monkeypatch)
    monkeypatch.setattr(csv_export, "SessionLocal", lambda: db_session)
    path = csv_export.generate_custom_csv("m1", "t1")
    rows = _read(path)
    assert rows[0] == ["LineItem", "Item", "ACV", "Firm"]
    # default filter: confirmed & not excluded & not needs_review -> only Sofa (i1)
    assert rows[1] == ["1", "Sofa", "600.00", "Roe LLP"]
    assert len(rows) == 2


def test_include_toggles_add_rows(db_session, tmp_path, monkeypatch):
    _seed(db_session, tmp_path, monkeypatch, include_excluded=True, include_needs_review=True)
    monkeypatch.setattr(csv_export, "SessionLocal", lambda: db_session)
    rows = _read(csv_export.generate_custom_csv("m1", "t1"))
    descriptions = [r[1] for r in rows[1:]]
    assert descriptions == ["Sofa", "Lamp", "Rug"]  # all three now included


def test_sort_by_description(db_session, tmp_path, monkeypatch):
    _seed(db_session, tmp_path, monkeypatch, include_excluded=True, include_needs_review=True,
          sort_field="description")
    monkeypatch.setattr(csv_export, "SessionLocal", lambda: db_session)
    rows = _read(csv_export.generate_custom_csv("m1", "t1"))
    assert [r[1] for r in rows[1:]] == ["Lamp", "Rug", "Sofa"]


def test_wrong_group_template_rejected(db_session, tmp_path, monkeypatch):
    _seed(db_session, tmp_path, monkeypatch)
    monkeypatch.setattr(csv_export, "SessionLocal", lambda: db_session)
    db_session.query(Matter).filter_by(id="m1").update({"owner_group_id": "other"})
    db_session.commit()
    try:
        csv_export.generate_custom_csv("m1", "t1")
        assert False, "expected ValueError"
    except ValueError:
        pass
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/services/test_csv_export_custom.py -v`
Expected: FAIL (`generate_custom_csv` not defined).

- [ ] **Step 3: Implement `generate_custom_csv`**

Add to `src/cvp/services/csv_export.py` (new imports at top, new function at end; leave existing code untouched):

```python
# add to imports
from cvp.models import Category, ExportTemplate, Item, ItemGroup, Matter, Room  # noqa: F811
from cvp.services.export_fields import FIELD_REGISTRY, RowContext


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
            .options(selectinload(Matter.items), selectinload(Matter.rooms))
            .filter(Matter.id == matter_id)
            .first()
        )
        if matter is None:
            raise ValueError(f"Matter {matter_id} not found")

        template = (
            db.query(ExportTemplate).filter(ExportTemplate.id == template_id).first()
        )
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
        datestamp = datetime.now().strftime("%Y%m%d")
        out_path = export_dir / f"contents_{_slugify(template.name)}_{datestamp}.csv"

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
                ctx = RowContext(
                    item=item,
                    room_name=room_map.get(item.room_id or "", "Unassigned"),
                    category_name=cat_map.get(item.category_id, ""),
                    item_group_name=group_map.get(item.item_group_id or "", ""),
                    matter=matter,
                )
                writer.writerow(
                    [
                        c.static_value if c.field_key is None
                        else FIELD_REGISTRY[c.field_key].render(ctx)
                        for c in columns
                    ]
                )
    finally:
        db.close()

    return out_path
```

Note: the `# noqa: F811` import line may duplicate names already imported at the top of `csv_export.py` (`Category`, `Matter`). If they are already imported, extend the existing import line to add `ExportTemplate`, `Item`, `ItemGroup`, `Room` instead of adding a second line — then drop the `noqa`. Check the current top-of-file imports before editing.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/services/test_csv_export_custom.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Guard against Xactimate regressions**

Run: `uv run pytest tests/ -k "csv" -v`
Expected: existing Xactimate CSV tests still PASS (proves `generate_csv` untouched).

- [ ] **Step 6: Format, lint, commit**

```bash
uv run ruff format . && uv run ruff format --check . && uv run ruff check .
git add src/cvp/services/csv_export.py tests/services/test_csv_export_custom.py
git commit -m "feat(exports): generate_custom_csv from a template"
```

---

### Task 5: Template CRUD router + builder page + custom export endpoint

**Files:**
- Create: `src/cvp/routers/export_templates.py`
- Create: `src/cvp/templates/export_templates_builder.html`
- Create: `src/cvp/templates/_export_template_row.html`
- Modify: `src/cvp/routers/exports.py` (add custom export endpoint)
- Modify: `src/cvp/main.py` (register router)
- Test: `tests/routers/test_export_templates.py`

**Interfaces:**
- Consumes: `export_templates` service (Task 3), `generate_custom_csv` (Task 4), `field_groups` (Task 2), `require_matter_role`, `CurrentUser`, `write_audit_log`, `get_client_ip`.
- Produces routes:
  - `GET  /matters/{matter_id}/export-templates` (viewer) → builder page HTML
  - `POST /api/matters/{matter_id}/export-templates` (contributor) → create, returns builder page (HX redirect/refresh)
  - `PUT  /api/matters/{matter_id}/export-templates/{tid}` (contributor) → update
  - `DELETE /api/matters/{matter_id}/export-templates/{tid}` (contributor) → delete
  - `POST /api/matters/{matter_id}/exports/custom` (manager, in `exports.py`) → run export
- Form contract: templates POST/PUT send `name`, `description`, `include_needs_review` (checkbox), `include_excluded` (checkbox), `sort_field`, and `columns_json` (a JSON array of `{"field_key": str|null, "header_label": str|null, "static_value": str|null}` in display order). The custom-export POST sends `template_id`.

- [ ] **Step 1: Write the failing test**

Create `tests/routers/test_export_templates.py`. First check how existing router tests build an authed client: run `grep -rln "TestClient\|auth_client\|def client" tests/routers | head` and reuse that fixture/pattern. Assuming a `manager_client` (or similar) fixture that authenticates as a group member with manager access to a seeded matter `m1` in group `g1`, and a `db_session`:

```python
import json


def _payload(**over):
    cols = over.pop("columns", [{"field_key": "description", "header_label": None,
                                 "static_value": None}])
    data = {
        "name": "Packet", "description": "", "sort_field": "line_number",
        "columns_json": json.dumps(cols),
    }
    data.update(over)
    return data


def test_create_lists_and_delete(manager_client):
    r = manager_client.post("/api/matters/m1/export-templates", data=_payload())
    assert r.status_code in (200, 201)

    page = manager_client.get("/matters/m1/export-templates")
    assert "Packet" in page.text

    # find the id from the DB via a list endpoint or the page; here re-query the API list page
    # (the builder page embeds data-template-id attributes)
    import re
    tid = re.search(r'data-template-id="([^"]+)"', page.text).group(1)

    r = manager_client.request("DELETE", f"/api/matters/m1/export-templates/{tid}")
    assert r.status_code == 200
    page = manager_client.get("/matters/m1/export-templates")
    assert "Packet" not in page.text


def test_cross_group_template_404(manager_client, db_session):
    from cvp.models import ExportTemplate, ExportTemplateColumn
    other = ExportTemplate(id="tX", group_id="other-group", name="Nope",
                           sort_field="line_number")
    other.columns = [ExportTemplateColumn(position=0, field_key="description")]
    db_session.add(other)
    db_session.commit()
    r = manager_client.request(
        "DELETE", "/api/matters/m1/export-templates/tX"
    )
    assert r.status_code == 404


def test_invalid_payload_400(manager_client):
    r = manager_client.post("/api/matters/m1/export-templates",
                            data=_payload(columns=[]))
    assert r.status_code == 400


def test_custom_export_runs(manager_client, db_session, tmp_path, monkeypatch):
    from cvp.services import csv_export
    monkeypatch.setattr(csv_export.settings, "export_dir", str(tmp_path))
    create = manager_client.post("/api/matters/m1/export-templates", data=_payload())
    page = manager_client.get("/matters/m1/export-templates")
    import re
    tid = re.search(r'data-template-id="([^"]+)"', page.text).group(1)
    r = manager_client.post("/api/matters/m1/exports/custom", data={"template_id": tid})
    assert r.status_code == 200
    assert "generated successfully" in r.text
```

Adapt fixture names to whatever `tests/routers/` already uses. If a manager fixture doesn't exist, model it on the fixture used by `tests/routers/test_exports*.py` (the existing export endpoints are `manager`-gated, so that test file already sets up exactly the right auth level and a seeded matter).

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/routers/test_export_templates.py -v`
Expected: FAIL (routes 404 / module not found).

- [ ] **Step 3: Implement the router**

Create `src/cvp/routers/export_templates.py`:

```python
"""Custom export template CRUD + builder page."""

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
        specs.append(
            svc.ColumnSpec(
                field_key=(c.get("field_key") or None),
                header_label=(c.get("header_label") or None),
                static_value=(c.get("static_value") if c.get("field_key") in (None, "") else None),
            )
        )
    return specs


def _render_builder(request: Request, db, matter_id: str, group_id: str) -> HTMLResponse:
    tmpls = svc.list_templates(db, group_id)
    return templates.TemplateResponse(
        request,
        "export_templates_builder.html",
        {
            "matter_id": matter_id,
            "templates_list": tmpls,
            "field_groups": field_groups(),
            "sort_fields": svc.SORT_FIELDS,
            "xactimate_defaults": svc.xactimate_default_columns(),
        },
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
        return _render_builder(request, db, matter_id, group_id)
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
                f'<p class="text-sm text-red-600">{exc}</p>', status_code=400
            )
        return _render_builder(request, db, matter_id, group_id)
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
                f'<p class="text-sm text-red-600">{exc}</p>', status_code=400
            )
        return _render_builder(request, db, matter_id, group_id)
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
        return _render_builder(request, db, matter_id, group_id)
    finally:
        db.close()
```

- [ ] **Step 4: Add the custom export endpoint to `exports.py`**

In `src/cvp/routers/exports.py`, add (mirror the existing `export_csv` handler, `manager`-gated):

```python
from fastapi import Form  # add to existing fastapi import line


@router.post("/api/matters/{matter_id}/exports/custom", response_class=HTMLResponse)
def export_custom(
    request: Request,
    matter_id: str,
    background_tasks: BackgroundTasks,
    template_id: str = Form(...),
    user: CurrentUser = Depends(require_matter_role("manager")),
) -> HTMLResponse:
    try:
        out_path = csv_export.generate_custom_csv(matter_id, template_id)
    except Exception as exc:
        return HTMLResponse(
            f'<p class="text-sm text-red-600">Custom export failed: {exc}</p>',
            status_code=500,
        )
    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="export.download",
        resource_type="matter",
        resource_id=matter_id,
        matter_id=matter_id,
        detail={"format": "custom", "template_id": template_id},
        ip_address=get_client_ip(request),
    )
    return HTMLResponse(_export_result_html("Custom CSV", out_path))
```

- [ ] **Step 5: Register the router in `main.py`**

Add `export_templates` to the `from cvp.routers import (...)` block (keep alphabetical: after `exports`), and add `app.include_router(export_templates.router)` next to `app.include_router(exports.router)`.

- [ ] **Step 6: Minimal builder templates so the page renders**

Create `src/cvp/templates/_export_template_row.html` (a single column row; used server-side and cloned by JS — see Task 6 for the JS). For now a static structural version:

```html
<li class="col-row flex items-center gap-2 rounded border border-gray-200 bg-white p-2"
    data-field-key="{{ field_key or '' }}"
    data-static="{{ '1' if field_key is none else '0' }}">
  <span class="flex-1 text-xs">
    {% if field_key is none %}
      <span class="font-semibold text-gray-500">Static:</span>
      <input type="text" class="col-static ml-1 rounded border px-1 text-xs"
             value="{{ static_value or '' }}" placeholder="fixed value">
    {% else %}
      <span class="font-mono text-gray-700">{{ field_key }}</span>
    {% endif %}
  </span>
  <input type="text" class="col-header w-36 rounded border px-1 text-xs"
         value="{{ header_label or '' }}" placeholder="{{ default_header }}">
  <button type="button" class="text-gray-400 hover:text-gray-700" data-action="move-col-up">↑</button>
  <button type="button" class="text-gray-400 hover:text-gray-700" data-action="move-col-down">↓</button>
  <button type="button" class="text-red-400 hover:text-red-700" data-action="remove-col">✕</button>
</li>
```

Create `src/cvp/templates/export_templates_builder.html`. Keep it structural for this task (the full interactive form is finished in Task 6); it MUST render existing templates with `data-template-id` attributes (the router tests assert on that):

```html
{% extends "base.html" %}
{% block content %}
<div class="mx-auto max-w-4xl space-y-6 p-6">
  <a href="/matters/{{ matter_id }}" class="text-sm text-indigo-600">← Back to matter</a>
  <h1 class="text-lg font-semibold text-gray-800">Custom Export Templates</h1>

  <section class="space-y-2">
    <h2 class="text-sm font-semibold text-gray-700">Existing templates</h2>
    {% if templates_list %}
    <ul class="space-y-1">
      {% for t in templates_list %}
      <li class="flex items-center justify-between rounded border border-gray-200 bg-white p-2 text-sm"
          data-template-id="{{ t.id }}">
        <span>{{ t.name }} <span class="text-xs text-gray-400">({{ t.columns|length }} cols)</span></span>
        <button type="button"
                hx-delete="/api/matters/{{ matter_id }}/export-templates/{{ t.id }}"
                hx-target="#builder-root" hx-swap="innerHTML"
                class="text-xs text-red-500 hover:text-red-700">Delete</button>
      </li>
      {% endfor %}
    </ul>
    {% else %}
    <p class="text-xs text-gray-400">No templates yet.</p>
    {% endif %}
  </section>
  <!-- Task 6 fills in the catalog + builder form here -->
</div>
{% endblock %}
```

Wrap the page body that HTMX swaps in an `id="builder-root"` container. To keep delete/create swaps simple, structure the template so `_render_builder` can return the whole page and HTMX targets `#builder-root`; for this task returning the full page for the create/delete responses is acceptable (the tests only check status + presence/absence of the name). Confirm `base.html` exists and provides a `content` block: run `grep -n "block content" src/cvp/templates/base.html`. If the block name differs, match it.

- [ ] **Step 7: Run the router tests**

Run: `uv run pytest tests/routers/test_export_templates.py -v`
Expected: PASS. If the auth fixture differs, fix the test's fixture usage (not the app) until green.

- [ ] **Step 8: Full suite + format + lint + commit**

```bash
uv run pytest
uv run ruff format . && uv run ruff format --check . && uv run ruff check .
git add src/cvp/routers/export_templates.py src/cvp/routers/exports.py src/cvp/main.py \
        src/cvp/templates/export_templates_builder.html src/cvp/templates/_export_template_row.html \
        tests/routers/test_export_templates.py
git commit -m "feat(exports): template CRUD router, builder page, custom export endpoint"
```

---

### Task 6: Builder UI interactivity + export-tab card

**Files:**
- Modify: `src/cvp/templates/export_templates_builder.html` (catalog + builder form + hidden `columns_json` + `<template>` clone source)
- Modify: `src/cvp/static/app.js` (delegated add/move/remove/serialize listeners)
- Modify: `src/cvp/templates/_tab_export.html` (Custom Export card)
- Test: manual verification (JS/UI); no new pytest. Existing suite must stay green.

**Interfaces:**
- Consumes: builder routes + custom-export endpoint (Task 5), `field_groups`, `xactimate_defaults`, `sort_fields` passed to the template (Task 5).
- Produces: a working builder form that serializes columns into a hidden `#columns-json` input matching the `_parse_columns` contract, and an export-tab dropdown that POSTs `template_id` to `/exports/custom`.

- [ ] **Step 1: Add the Custom Export card to the export tab**

In `src/cvp/templates/_tab_export.html`, add a third card after the Xactimate CSV card (before the Preview link), following the existing `hx-post` + spinner + result pattern:

```html
  <!-- Custom CSV export -->
  <div class="rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
    <div class="flex items-start justify-between gap-4">
      <div>
        <h3 class="text-sm font-semibold text-gray-800">Custom CSV</h3>
        <p class="mt-1 text-xs text-gray-500">
          Export using one of your group's saved templates.
          <a href="/matters/{{ matter.id }}/export-templates"
             class="text-indigo-600 hover:underline">Manage templates →</a>
        </p>
      </div>
      <form hx-post="/api/matters/{{ matter.id }}/exports/custom"
            hx-target="#custom-result" hx-swap="innerHTML"
            hx-indicator="#custom-spinner"
            class="flex flex-shrink-0 items-center gap-2">
        <select name="template_id" required
                class="rounded-md border border-gray-300 px-2 py-1.5 text-sm">
          {% if custom_templates %}
            {% for t in custom_templates %}
            <option value="{{ t.id }}">{{ t.name }}</option>
            {% endfor %}
          {% else %}
            <option value="" disabled selected>No templates yet</option>
          {% endif %}
        </select>
        <button type="submit"
                class="rounded-md bg-slate-700 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-600 disabled:opacity-50"
                {% if not custom_templates %}disabled{% endif %}>
          Export
        </button>
      </form>
    </div>
    <span id="custom-spinner" class="htmx-indicator mt-2 block text-xs text-slate-600">Generating CSV…</span>
    <div id="custom-result" class="mt-3"></div>
  </div>
```

Then find where `_tab_export.html` is rendered and pass `custom_templates`: run `grep -rn "_tab_export\|tab_export\|export" src/cvp/routers/matters.py` (and wherever the matter tabs are assembled). Add `custom_templates = export_templates_svc.list_templates(db, matter.owner_group_id)` (guard `owner_group_id` None → empty list) to that view's context. Import the service as `from cvp.services import export_templates as export_templates_svc`.

- [ ] **Step 2: Flesh out the builder form**

Replace the `<!-- Task 6 fills in… -->` comment in `export_templates_builder.html` with the catalog + form. Include a hidden `<template id="col-row-template">` holding one empty `.col-row` (same markup as `_export_template_row.html` with empty values) for JS cloning, a catalog of Add buttons carrying `data-field-key` and `data-default-header`, the settings inputs, an `<ol id="col-list">`, a hidden `<input id="columns-json" name="columns_json">`, and a "Start from Xactimate layout" button carrying the default keys as JSON in a `data-` attribute:

```html
  <form id="builder-form"
        hx-post="/api/matters/{{ matter_id }}/export-templates"
        hx-target="#builder-root" hx-swap="innerHTML"
        class="space-y-4 rounded-lg border border-gray-200 bg-gray-50 p-4">
    <div class="grid grid-cols-2 gap-3">
      <label class="text-xs font-semibold text-gray-600">Name
        <input name="name" required class="mt-1 w-full rounded border px-2 py-1 text-sm">
      </label>
      <label class="text-xs font-semibold text-gray-600">Sort by
        <select name="sort_field" class="mt-1 w-full rounded border px-2 py-1 text-sm">
          {% for s in sort_fields %}<option value="{{ s }}">{{ s }}</option>{% endfor %}
        </select>
      </label>
    </div>
    <label class="text-xs font-semibold text-gray-600">Description
      <input name="description" class="mt-1 w-full rounded border px-2 py-1 text-sm">
    </label>
    <div class="flex gap-4 text-xs text-gray-600">
      <label><input type="checkbox" name="include_needs_review" value="true"> Include needs-review items</label>
      <label><input type="checkbox" name="include_excluded" value="true"> Include excluded items</label>
    </div>

    <div class="grid grid-cols-2 gap-4">
      <div>
        <p class="mb-1 text-xs font-semibold text-gray-600">Available fields</p>
        <button type="button" class="mb-2 rounded bg-indigo-50 px-2 py-1 text-xs text-indigo-700"
                data-action="load-xactimate"
                data-keys='{{ xactimate_defaults | map(attribute="field_key") | list | tojson }}'>
          Start from Xactimate layout
        </button>
        {% for group, fields in field_groups.items() %}
        <p class="mt-2 text-[11px] font-semibold uppercase text-gray-400">{{ group }}</p>
        <div class="flex flex-wrap gap-1">
          {% for f in fields %}
          <button type="button" class="rounded border border-gray-300 bg-white px-2 py-0.5 text-xs hover:bg-gray-100"
                  data-action="add-col" data-field-key="{{ f.key }}"
                  data-default-header="{{ f.default_header }}">+ {{ f.default_header }}</button>
          {% endfor %}
        </div>
        {% endfor %}
        <button type="button" class="mt-2 rounded border border-dashed border-gray-400 px-2 py-0.5 text-xs"
                data-action="add-static">+ Static column</button>
      </div>
      <div>
        <p class="mb-1 text-xs font-semibold text-gray-600">Columns (in order)</p>
        <ol id="col-list" class="space-y-1"></ol>
      </div>
    </div>

    <input type="hidden" id="columns-json" name="columns_json" value="[]">
    <button type="submit" class="rounded-md bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-500">
      Save template
    </button>
  </form>

  <template id="col-row-template">
    {% include "_export_template_row.html" with context %}
  </template>
```

For the `<template>` include to render an empty row, pass empty values: define them just above the include, e.g. wrap in `{% with field_key=None, header_label=None, static_value=None, default_header="" %}...{% endwith %}` — but Jinja `with` for the include needs the row markup to tolerate `field_key is none` meaning "static". Since the clone source must be able to become EITHER a field or static row, JS sets the row's content on clone. Simpler: make `col-row-template` hold the minimal shell and let JS fill `data-field-key`, the label span, and inputs. Replace the `{% include %}` with an inline minimal shell:

```html
  <template id="col-row-template">
    <li class="col-row flex items-center gap-2 rounded border border-gray-200 bg-white p-2">
      <span class="col-label flex-1 text-xs"></span>
      <input type="text" class="col-header w-36 rounded border px-1 text-xs" placeholder="header">
      <button type="button" data-action="move-col-up" class="text-gray-400 hover:text-gray-700">↑</button>
      <button type="button" data-action="move-col-down" class="text-gray-400 hover:text-gray-700">↓</button>
      <button type="button" data-action="remove-col" class="text-red-400 hover:text-red-700">✕</button>
    </li>
  </template>
```

(With this shell approach, `_export_template_row.html` from Task 5 is only used for any future server-side row rendering; the live builder clones this template. That's fine — leave the partial in place.)

- [ ] **Step 3: Wire the delegated JS in `app.js`**

Append to `src/cvp/static/app.js` (follows the existing delegated-listener pattern at lines ~346–370; no inline handlers):

```javascript
// ---- Custom export template builder ----
(function () {
  function colList() { return document.getElementById('col-list'); }

  function serialize() {
    var list = colList();
    var json = document.getElementById('columns-json');
    if (!list || !json) return;
    var cols = [];
    list.querySelectorAll('.col-row').forEach(function (row) {
      var fieldKey = row.dataset.fieldKey || null;
      var header = (row.querySelector('.col-header') || {}).value || '';
      var staticInput = row.querySelector('.col-static');
      cols.push({
        field_key: fieldKey,
        header_label: header || null,
        static_value: fieldKey ? null : ((staticInput && staticInput.value) || ''),
      });
    });
    json.value = JSON.stringify(cols);
  }

  function makeRow(fieldKey, defaultHeader, isStatic) {
    var tpl = document.getElementById('col-row-template');
    var row = tpl.content.firstElementChild.cloneNode(true);
    var label = row.querySelector('.col-label');
    if (isStatic) {
      row.dataset.fieldKey = '';
      label.innerHTML = '<span class="font-semibold text-gray-500">Static:</span> '
        + '<input type="text" class="col-static ml-1 rounded border px-1 text-xs" placeholder="fixed value">';
      row.querySelector('.col-header').placeholder = 'header (required)';
    } else {
      row.dataset.fieldKey = fieldKey;
      label.innerHTML = '<span class="font-mono text-gray-700"></span>';
      label.firstChild.textContent = fieldKey;
      row.querySelector('.col-header').placeholder = defaultHeader || 'header';
    }
    return row;
  }

  document.addEventListener('click', function (e) {
    var addBtn = e.target.closest('[data-action="add-col"]');
    if (addBtn) {
      colList().appendChild(makeRow(addBtn.dataset.fieldKey, addBtn.dataset.defaultHeader, false));
      serialize();
      return;
    }
    if (e.target.closest('[data-action="add-static"]')) {
      colList().appendChild(makeRow(null, '', true));
      serialize();
      return;
    }
    var load = e.target.closest('[data-action="load-xactimate"]');
    if (load) {
      var keys = JSON.parse(load.dataset.keys || '[]');
      colList().innerHTML = '';
      keys.forEach(function (k) {
        var src = document.querySelector('[data-action="add-col"][data-field-key="' + k + '"]');
        colList().appendChild(makeRow(k, src ? src.dataset.defaultHeader : '', false));
      });
      serialize();
      return;
    }
    var up = e.target.closest('[data-action="move-col-up"]');
    if (up) {
      var r = up.closest('.col-row');
      if (r.previousElementSibling) r.parentNode.insertBefore(r, r.previousElementSibling);
      serialize();
      return;
    }
    var down = e.target.closest('[data-action="move-col-down"]');
    if (down) {
      var rd = down.closest('.col-row');
      if (rd.nextElementSibling) rd.parentNode.insertBefore(rd.nextElementSibling, rd);
      serialize();
      return;
    }
    var rm = e.target.closest('[data-action="remove-col"]');
    if (rm) { rm.closest('.col-row').remove(); serialize(); return; }
  });

  // keep hidden JSON in sync when header/static text changes
  document.addEventListener('input', function (e) {
    if (e.target.closest('.col-header, .col-static')) serialize();
  });
})();
```

- [ ] **Step 4: Verify the app boots and the suite is green**

Run: `uv run pytest`
Expected: full suite PASS (no regressions).
Run: `uv run ruff format . && uv run ruff format --check . && uv run ruff check .`
Expected: pass.

- [ ] **Step 5: Manual smoke test (browser)**

Start the app: `uv run dev`. Follow the repo's browser-verify recipe if the checked-in dev DB is schema-drifted (fresh DB + `AUTO_LOGIN` + a `system_admin`, per project memory). Then, for a matter with an `owner_group_id`:
1. Open `/matters/{id}/export-templates`. Click "Start from Xactimate layout" → 13 rows appear. Reorder two with ↑/↓, rename a header, add a Static column with a value, click **Save template**. The template appears under "Existing templates".
2. Open the matter's Export tab → the "Custom CSV" card lists the template. Pick it → **Export** → a "generated successfully" download link appears.
3. Download and open the CSV: header row matches your column order/renames, the Confidential comment line is present, static column shows the fixed value, and only confirmed/non-excluded rows appear (unless you toggled the includes).

- [ ] **Step 6: Commit**

```bash
git add src/cvp/templates/export_templates_builder.html src/cvp/templates/_export_template_row.html \
        src/cvp/templates/_tab_export.html src/cvp/static/app.js src/cvp/routers/matters.py
git commit -m "feat(exports): custom export builder UI + export-tab dropdown"
```

---

## Final verification

- [ ] `uv run pytest` — full suite green.
- [ ] `uv run ruff format --check .` and `uv run ruff check .` — clean.
- [ ] Xactimate CSV export byte-for-byte unchanged (its tests still pass; `CSV_HEADERS` untouched).
- [ ] Manual browser smoke test (Task 6 Step 5) done end-to-end.
- [ ] Cross-group isolation: a template id from another group returns 404 on update/delete and `generate_custom_csv` raises on group mismatch.

## Notes for the reviewer

- **RBAC floors** are a judgment call encoded in Global Constraints: viewer (read/builder), contributor (create/edit/delete), manager (run export, matching existing exports). If the group prefers the literal "any user in the group" to also cover running exports, lower the custom-export endpoint to `contributor` or `viewer` — but note that would let non-managers produce full item exports, a privilege the current PDF/CSV exports reserve for managers.
- The builder returns the **whole page** on create/delete/update and HTMX-swaps `#builder-root`; ensure the swapped fragment and the initial page share that container id. If cleaner, split the swappable body into a partial later — not required for correctness.
```
