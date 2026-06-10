# Item Groups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add optional "Group" metadata to items so on-site placards (numbered cards in photos that group multiple items) are first-class. Specialists manage groups in the Rooms tab, pin a group per evidence image, and the vision scan auto-detects placards while excluding the placard from extracted items.

**Architecture:** New `ItemGroup` model (table `item_groups`) scoped to a matter, with case-insensitive trim dedupe on name. `items.item_group_id` records membership; `evidence_files.pinned_item_group_id` records the per-image dropdown choice. The vision prompt is changed from a JSON array to a JSON object that carries both `items` and a separate `placard_text` field so the placard can never be misclassified as an item. The worker picks the effective group as `pinned_item_group_id ?? find_or_create(placard_text) ?? NULL`.

**Tech Stack:** FastAPI, Jinja2, HTMX, SQLAlchemy 2.x, Alembic, pytest, ruff. Tailwind via CDN. Existing patterns: routers under `src/cvp/routers/`, services under `src/cvp/services/`, templates under `src/cvp/templates/`, tests mirroring `src/cvp/`.

**Spec:** `docs/superpowers/specs/2026-06-09-item-groups-design.md`

**Naming reminder:** The `Group` class and `groups` table are already taken by `models_auth.py` (matter ownership / RBAC). Use **`ItemGroup`** / **`item_groups`** at the data layer. UX label stays "Group".

**Working branch:** `feat/item-groups-spec` (already created with the spec commit). Do not switch off it. Push at the end.

**Conventions to follow throughout:**
- Run `uv run ruff format .` and `uv run ruff format --check .` before every commit. CI enforces format.
- No inline JS event handlers (`onclick=`, `onchange=`, etc.). Wire interactivity via `data-*` attributes and delegated listeners in `src/cvp/static/app.js` (see lines 225–275 for the existing pattern).
- UUIDs as strings. Timestamps timezone-aware UTC.
- All currency operations are integer cents; not relevant to this feature but don't break that invariant.
- Type hints everywhere using modern syntax (`list[str]`, `X | None`).
- Pure functions stay in services; routers stay thin and under ~200 lines.
- Frequent small commits — one per task minimum.

---

## File Structure

**New files:**
- `src/cvp/services/item_groups.py` — `find_or_create(session, matter_id, name) -> ItemGroup`
- `src/cvp/routers/item_groups.py` — CRUD + per-evidence pinning endpoints
- `src/cvp/templates/_item_group_li.html` — single-group row partial
- `src/cvp/templates/_groups_panel.html` — Groups panel (create form + list) used inside `_tab_rooms.html`
- `src/cvp/templates/_evidence_group_select.html` — per-image dropdown partial used inside `_evidence_grid.html`
- `migrations/versions/<date>_<hash>_add_item_groups.py` — single Alembic revision
- `tests/test_item_groups_service.py` — unit tests for `find_or_create`
- `tests/test_item_groups_router.py` — CRUD + evidence pin endpoint tests
- `tests/test_items_group_assignment.py` — item edit form group_id + new_group_name
- `tests/test_vision_worker_item_groups.py` — group application during scan
- `tests/test_vision_prompts_placard.py` — prompt + parser tests for placard_text

**Modified files:**
- `src/cvp/models.py` — add `ItemGroup`; add `item_group_id` to `Item`; add `pinned_item_group_id` to `EvidenceFile`
- `src/cvp/main.py` — register `item_groups.router`
- `src/cvp/services/vision_prompts.py` — switch to JSON object output, add placard instruction, bump `SCAN_PROMPT_VERSION`
- `src/cvp/services/vision.py` — `_parse_response` returns `(list[dict], str)`; worker applies effective `item_group_id`
- `src/cvp/routers/items.py` — `update_item` accepts `item_group_id` + `new_item_group_name`; `_get_context` returns item groups; pass to edit template
- `src/cvp/routers/evidence.py` — load matter's item groups for the grid template
- `src/cvp/routers/rooms.py` (or its callers) — render path that produces `_tab_rooms.html` now also passes `item_groups`
- `src/cvp/templates/_item_row_edit.html` — add Group field
- `src/cvp/templates/_tab_rooms.html` — include `_groups_panel.html`, update header copy
- `src/cvp/templates/_evidence_grid.html` — include `_evidence_group_select.html`
- `src/cvp/templates/matter_detail.html` — rename tab label `Rooms` → `Rooms & Groups`
- `src/cvp/static/app.js` — delegated listener for `+ New group…` sentinel + inline create flow

---

## Task 1: Add `ItemGroup` model

**Files:**
- Modify: `src/cvp/models.py` (add new class after `Room`)
- Modify: `tests/conftest.py` (no change expected; verify model autoloads through `cvp.models` import)
- Test: `tests/test_item_groups_service.py` (created in Task 2; for now we'll add a sanity model test inline in conftest-style)

- [ ] **Step 1: Write a failing test that asserts the `ItemGroup` model exists with the right columns**

Create `tests/test_item_groups_model.py`:

```python
"""Sanity tests for the ItemGroup ORM model."""

import pytest
from sqlalchemy.exc import IntegrityError

from cvp.db import SessionLocal
from cvp.models import ItemGroup, Matter


@pytest.fixture
def matter_id() -> str:
    db = SessionLocal()
    try:
        m = Matter(firm_name="Test Firm")
        db.add(m)
        db.commit()
        db.refresh(m)
        return m.id
    finally:
        db.close()


def test_item_group_can_be_created(matter_id: str) -> None:
    db = SessionLocal()
    try:
        g = ItemGroup(matter_id=matter_id, name="12", name_normalized="12")
        db.add(g)
        db.commit()
        db.refresh(g)
        assert g.id
        assert g.matter_id == matter_id
        assert g.name == "12"
        assert g.name_normalized == "12"
        assert g.created_at is not None
    finally:
        db.close()


def test_item_group_unique_constraint(matter_id: str) -> None:
    db = SessionLocal()
    try:
        db.add(ItemGroup(matter_id=matter_id, name="Box A", name_normalized="box a"))
        db.commit()
        db.add(ItemGroup(matter_id=matter_id, name="box a", name_normalized="box a"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    finally:
        db.close()
```

- [ ] **Step 2: Run the test — expect ImportError**

Run: `uv run pytest tests/test_item_groups_model.py -v`
Expected: FAIL with `ImportError: cannot import name 'ItemGroup' from 'cvp.models'`.

- [ ] **Step 3: Add the `ItemGroup` model**

In `src/cvp/models.py`, add this class *after* the `Room` class and *before* the `Category` class:

```python
class ItemGroup(Base):
    """An on-site organizational group (e.g. items grouped under a numbered placard).

    Named `ItemGroup` to avoid collision with the auth/RBAC `Group` model
    (`src/cvp/models_auth.py`). The user-facing label in the UI is "Group".
    """

    __tablename__ = "item_groups"
    __table_args__ = (
        Index("ix_item_groups_matter_id", "matter_id"),
        Index(
            "uq_item_groups_matter_name_normalized",
            "matter_id",
            "name_normalized",
            unique=True,
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    matter_id: Mapped[str] = mapped_column(String, ForeignKey("matters.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    name_normalized: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
```

- [ ] **Step 4: Run the test — expect PASS**

Run: `uv run pytest tests/test_item_groups_model.py -v`
Expected: both tests pass. The `Base.metadata.create_all(engine)` line in `conftest.py` creates the new table automatically for the test DB.

- [ ] **Step 5: Format and commit**

Run: `uv run ruff format . && uv run ruff format --check .`
Expected: "X file(s) already formatted" (i.e., zero would be reformatted).

```bash
git add src/cvp/models.py tests/test_item_groups_model.py
git commit -m "feat: add ItemGroup model with per-matter unique-name constraint"
```

---

## Task 2: `find_or_create` service helper

**Files:**
- Create: `src/cvp/services/item_groups.py`
- Test: `tests/test_item_groups_service.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_item_groups_service.py`:

```python
"""Unit tests for cvp.services.item_groups.find_or_create."""

import pytest

from cvp.db import SessionLocal
from cvp.models import ItemGroup, Matter
from cvp.services.item_groups import find_or_create


@pytest.fixture
def matter_id() -> str:
    db = SessionLocal()
    try:
        m = Matter(firm_name="Test")
        db.add(m)
        db.commit()
        db.refresh(m)
        return m.id
    finally:
        db.close()


def test_creates_when_missing(matter_id: str) -> None:
    db = SessionLocal()
    try:
        g = find_or_create(db, matter_id, "12")
        db.commit()
        assert g.id
        assert g.name == "12"
        assert g.name_normalized == "12"
    finally:
        db.close()


def test_reuses_exact_match(matter_id: str) -> None:
    db = SessionLocal()
    try:
        g1 = find_or_create(db, matter_id, "Box A")
        db.commit()
        g2 = find_or_create(db, matter_id, "Box A")
        db.commit()
        assert g1.id == g2.id
    finally:
        db.close()


@pytest.mark.parametrize(
    "first,second",
    [
        ("12", " 12 "),
        ("12", "12 "),
        ("Box A", "box a"),
        ("Box A", "BOX A"),
        ("  Garage shelf 2  ", "garage shelf 2"),
    ],
)
def test_dedupes_case_and_whitespace(matter_id: str, first: str, second: str) -> None:
    db = SessionLocal()
    try:
        g1 = find_or_create(db, matter_id, first)
        db.commit()
        g2 = find_or_create(db, matter_id, second)
        db.commit()
        assert g1.id == g2.id
    finally:
        db.close()


def test_rejects_empty_name(matter_id: str) -> None:
    db = SessionLocal()
    try:
        with pytest.raises(ValueError):
            find_or_create(db, matter_id, "")
        with pytest.raises(ValueError):
            find_or_create(db, matter_id, "   ")
    finally:
        db.close()


def test_scoped_per_matter(matter_id: str) -> None:
    db = SessionLocal()
    try:
        other = Matter(firm_name="Other")
        db.add(other)
        db.commit()
        db.refresh(other)
        g1 = find_or_create(db, matter_id, "12")
        g2 = find_or_create(db, other.id, "12")
        db.commit()
        assert g1.id != g2.id
        assert (
            db.query(ItemGroup).filter(ItemGroup.name_normalized == "12").count() == 2
        )
    finally:
        db.close()
```

- [ ] **Step 2: Run tests — expect ImportError**

Run: `uv run pytest tests/test_item_groups_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cvp.services.item_groups'`.

- [ ] **Step 3: Implement the service**

Create `src/cvp/services/item_groups.py`:

```python
"""Service helpers for the ItemGroup entity (per-matter on-site placards)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cvp.models import ItemGroup


def _normalize(name: str) -> str:
    return name.strip().lower()


def find_or_create(session: Session, matter_id: str, name: str) -> ItemGroup:
    """Return the ItemGroup matching ``name`` for ``matter_id``, creating it if absent.

    Names are matched case-insensitively after whitespace trimming. The unique
    index on ``(matter_id, name_normalized)`` is the source of truth for
    dedupe; this function catches an IntegrityError race and re-queries.
    """
    normalized = _normalize(name)
    if not normalized:
        raise ValueError("group name cannot be empty")
    existing = session.execute(
        select(ItemGroup).where(
            ItemGroup.matter_id == matter_id,
            ItemGroup.name_normalized == normalized,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    group = ItemGroup(
        matter_id=matter_id,
        name=name.strip(),
        name_normalized=normalized,
    )
    session.add(group)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        # Re-query after a concurrent insert won the race.
        return session.execute(
            select(ItemGroup).where(
                ItemGroup.matter_id == matter_id,
                ItemGroup.name_normalized == normalized,
            )
        ).scalar_one()
    return group
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `uv run pytest tests/test_item_groups_service.py -v`
Expected: all tests pass.

- [ ] **Step 5: Format and commit**

```bash
uv run ruff format . && uv run ruff format --check .
git add src/cvp/services/item_groups.py tests/test_item_groups_service.py
git commit -m "feat: add item_groups.find_or_create with case/whitespace dedupe"
```

---

## Task 3: Add FK columns to `Item` and `EvidenceFile`

**Files:**
- Modify: `src/cvp/models.py` (add fields to `Item` and `EvidenceFile`)
- Test: `tests/test_item_group_assignment.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_item_group_assignment.py`:

```python
"""Tests confirming Item.item_group_id and EvidenceFile.pinned_item_group_id exist."""

import pytest

from cvp.db import SessionLocal
from cvp.models import Category, EvidenceFile, Item, ItemGroup, Matter


@pytest.fixture
def matter_id() -> str:
    db = SessionLocal()
    try:
        m = Matter(firm_name="Test")
        db.add(m)
        # Make sure at least one category exists for Item creation.
        if db.query(Category).count() == 0:
            db.add(Category(id=1, name="Misc", useful_life_years=10, acv_floor_pct=0.2))
        db.commit()
        db.refresh(m)
        return m.id
    finally:
        db.close()


def test_item_can_reference_item_group(matter_id: str) -> None:
    db = SessionLocal()
    try:
        g = ItemGroup(matter_id=matter_id, name="12", name_normalized="12")
        db.add(g)
        db.commit()
        db.refresh(g)
        cat = db.query(Category).first()
        item = Item(matter_id=matter_id, category_id=cat.id, item_group_id=g.id)
        db.add(item)
        db.commit()
        db.refresh(item)
        assert item.item_group_id == g.id
    finally:
        db.close()


def test_item_group_id_nullable(matter_id: str) -> None:
    db = SessionLocal()
    try:
        cat = db.query(Category).first()
        item = Item(matter_id=matter_id, category_id=cat.id)
        db.add(item)
        db.commit()
        db.refresh(item)
        assert item.item_group_id is None
    finally:
        db.close()


def test_evidence_file_pinned_item_group_id(matter_id: str) -> None:
    db = SessionLocal()
    try:
        g = ItemGroup(matter_id=matter_id, name="A", name_normalized="a")
        db.add(g)
        db.commit()
        ef = EvidenceFile(
            matter_id=matter_id,
            filename="x.jpg",
            stored_path="x.jpg",
            pinned_item_group_id=g.id,
        )
        db.add(ef)
        db.commit()
        db.refresh(ef)
        assert ef.pinned_item_group_id == g.id
    finally:
        db.close()
```

- [ ] **Step 2: Run tests — expect failure on `item_group_id` attribute**

Run: `uv run pytest tests/test_item_group_assignment.py -v`
Expected: FAIL with `TypeError: 'item_group_id' is an invalid keyword argument for Item`.

- [ ] **Step 3: Add the FK columns**

In `src/cvp/models.py`, inside class `Item`, add right after the existing `room_id` line (around line 121):

```python
    item_group_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("item_groups.id", ondelete="SET NULL"), nullable=True
    )
```

In the same class, after the existing `room` / `category` relationships block, add:

```python
    item_group: Mapped["ItemGroup | None"] = relationship("ItemGroup")
```

In class `EvidenceFile`, add right after the existing `kind` line (around line 173):

```python
    pinned_item_group_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("item_groups.id", ondelete="SET NULL"), nullable=True
    )
```

And, in the EvidenceFile relationships block, add:

```python
    pinned_item_group: Mapped["ItemGroup | None"] = relationship("ItemGroup")
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `uv run pytest tests/test_item_group_assignment.py -v`
Expected: all three tests pass. Conftest creates the new columns when it calls `Base.metadata.create_all(engine)`.

- [ ] **Step 5: Format and commit**

```bash
uv run ruff format . && uv run ruff format --check .
git add src/cvp/models.py tests/test_item_group_assignment.py
git commit -m "feat: add Item.item_group_id and EvidenceFile.pinned_item_group_id"
```

---

## Task 4: Alembic migration

**Files:**
- Create: `migrations/versions/<date>_<hash>_add_item_groups.py` (autogenerated; hand-reviewed)

- [ ] **Step 1: Generate the migration**

Run: `uv run alembic revision --autogenerate -m "add item groups"`
Expected: a new file appears under `migrations/versions/` with three operations: `create_table('item_groups', ...)`, `add_column('items', 'item_group_id', ...)`, `add_column('evidence_files', 'pinned_item_group_id', ...)`.

- [ ] **Step 2: Open the generated file and edit it**

Replace the auto-generated body so it uses `batch_alter_table` for the two FK adds (needed because SQLite can't ALTER to add FKs without table-rebuild). The file's `upgrade()` and `downgrade()` should read:

```python
def upgrade() -> None:
    op.create_table(
        "item_groups",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("matter_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("name_normalized", sa.String(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.ForeignKeyConstraint(["matter_id"], ["matters.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_item_groups_matter_id", "item_groups", ["matter_id"])
    op.create_index(
        "uq_item_groups_matter_name_normalized",
        "item_groups",
        ["matter_id", "name_normalized"],
        unique=True,
    )

    with op.batch_alter_table("items") as batch_op:
        batch_op.add_column(sa.Column("item_group_id", sa.String(), nullable=True))
        batch_op.create_foreign_key(
            "fk_items_item_group_id",
            "item_groups",
            ["item_group_id"],
            ["id"],
            ondelete="SET NULL",
        )

    with op.batch_alter_table("evidence_files") as batch_op:
        batch_op.add_column(sa.Column("pinned_item_group_id", sa.String(), nullable=True))
        batch_op.create_foreign_key(
            "fk_evidence_files_pinned_item_group_id",
            "item_groups",
            ["pinned_item_group_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("evidence_files") as batch_op:
        batch_op.drop_constraint("fk_evidence_files_pinned_item_group_id", type_="foreignkey")
        batch_op.drop_column("pinned_item_group_id")

    with op.batch_alter_table("items") as batch_op:
        batch_op.drop_constraint("fk_items_item_group_id", type_="foreignkey")
        batch_op.drop_column("item_group_id")

    op.drop_index("uq_item_groups_matter_name_normalized", table_name="item_groups")
    op.drop_index("ix_item_groups_matter_id", table_name="item_groups")
    op.drop_table("item_groups")
```

- [ ] **Step 3: Apply the migration**

Run: `uv run alembic upgrade head`
Expected: "Running upgrade ... -> ..., add item groups" with no errors.

- [ ] **Step 4: Run the full test suite to confirm nothing regressed**

Run: `uv run pytest -q`
Expected: all tests pass (model + service tests we already added stay green; nothing else broken).

- [ ] **Step 5: Format and commit**

```bash
uv run ruff format . && uv run ruff format --check .
git add migrations/versions/
git commit -m "feat: alembic migration for item_groups table and FK columns"
```

---

## Task 5: `routers/item_groups.py` — create, rename, delete

**Files:**
- Create: `src/cvp/routers/item_groups.py`
- Modify: `src/cvp/main.py` (register router)
- Create: `src/cvp/templates/_item_group_li.html` (single-row partial; we'll flesh out UI in Task 7)
- Test: `tests/test_item_groups_router.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_item_groups_router.py`:

```python
"""HTTP tests for the item_groups router (CRUD on item groups)."""

from fastapi.testclient import TestClient

from cvp.db import SessionLocal
from cvp.main import app
from cvp.models import Item, ItemGroup, Matter, Category
from tests.test_auth_routes import _authed_client  # reuse existing helper


def _make_matter(role: str = "manager") -> tuple[TestClient, str]:
    """Returns (authenticated client, matter_id) where the test user holds ``role``."""
    client, user = _authed_client()
    db = SessionLocal()
    try:
        if db.query(Category).count() == 0:
            db.add(Category(id=1, name="Misc", useful_life_years=10, acv_floor_pct=0.2))
        m = Matter(firm_name="Test", created_by_id=user.id)
        db.add(m)
        db.commit()
        db.refresh(m)
        from cvp.models_access import MatterAccess
        db.add(MatterAccess(matter_id=m.id, user_id=user.id, role=role))
        db.commit()
        return client, m.id
    finally:
        db.close()


def test_create_group() -> None:
    client, matter_id = _make_matter()
    r = client.post(f"/api/matters/{matter_id}/item-groups", data={"name": "12"})
    assert r.status_code == 200
    db = SessionLocal()
    try:
        groups = db.query(ItemGroup).filter(ItemGroup.matter_id == matter_id).all()
        assert len(groups) == 1
        assert groups[0].name == "12"
        assert groups[0].name_normalized == "12"
    finally:
        db.close()


def test_create_duplicate_returns_existing() -> None:
    client, matter_id = _make_matter()
    r1 = client.post(f"/api/matters/{matter_id}/item-groups", data={"name": "Box A"})
    assert r1.status_code == 200
    r2 = client.post(f"/api/matters/{matter_id}/item-groups", data={"name": "box a"})
    assert r2.status_code == 200
    db = SessionLocal()
    try:
        groups = db.query(ItemGroup).filter(ItemGroup.matter_id == matter_id).all()
        assert len(groups) == 1
    finally:
        db.close()


def test_create_rejects_empty_name() -> None:
    client, matter_id = _make_matter()
    r = client.post(f"/api/matters/{matter_id}/item-groups", data={"name": "   "})
    assert r.status_code == 400


def test_rename_group() -> None:
    client, matter_id = _make_matter()
    r = client.post(f"/api/matters/{matter_id}/item-groups", data={"name": "old"})
    db = SessionLocal()
    try:
        gid = db.query(ItemGroup).filter(ItemGroup.matter_id == matter_id).first().id
    finally:
        db.close()
    r = client.patch(
        f"/api/matters/{matter_id}/item-groups/{gid}",
        data={"name": "new"},
    )
    assert r.status_code == 200
    db = SessionLocal()
    try:
        g = db.get(ItemGroup, gid)
        assert g.name == "new"
        assert g.name_normalized == "new"
    finally:
        db.close()


def test_delete_group_nulls_item_group_id() -> None:
    client, matter_id = _make_matter()
    client.post(f"/api/matters/{matter_id}/item-groups", data={"name": "tmp"})
    db = SessionLocal()
    try:
        cat = db.query(Category).first()
        g = db.query(ItemGroup).filter(ItemGroup.matter_id == matter_id).first()
        item = Item(matter_id=matter_id, category_id=cat.id, item_group_id=g.id)
        db.add(item)
        db.commit()
        item_id = item.id
        gid = g.id
    finally:
        db.close()
    r = client.delete(f"/api/matters/{matter_id}/item-groups/{gid}")
    assert r.status_code == 200
    db = SessionLocal()
    try:
        assert db.get(ItemGroup, gid) is None
        assert db.get(Item, item_id).item_group_id is None
    finally:
        db.close()


def test_create_requires_role() -> None:
    """A viewer cannot create groups."""
    client, matter_id = _make_matter(role="viewer")
    r = client.post(f"/api/matters/{matter_id}/item-groups", data={"name": "12"})
    assert r.status_code == 403
```

If `tests/test_auth_routes.py::_authed_client` doesn't exist or has a different signature, replace its import with whatever the existing test suite uses to build an authenticated `TestClient` and `CurrentUser` (look at `tests/test_rbac.py`, `tests/test_auth_routes.py`, `tests/test_admin_org.py`, or `tests/conftest.py` for the canonical helper). Do not invent a new helper — keep this test in the same style as the others in the repo.

- [ ] **Step 2: Run tests — expect 404 / import errors**

Run: `uv run pytest tests/test_item_groups_router.py -v`
Expected: FAIL — the router and endpoints don't exist.

- [ ] **Step 3: Create the single-row partial**

Create `src/cvp/templates/_item_group_li.html`:

```html
<li id="item-group-{{ group.id }}"
    class="group flex items-center justify-between rounded-md border border-gray-200 bg-white px-4 py-2.5 shadow-sm">
  <div class="flex items-center gap-3">
    <span id="item-group-name-{{ group.id }}" class="text-sm font-medium text-gray-800">{{ group.name }}</span>
    <span class="text-xs text-gray-400">{{ item_count }} item{{ "" if item_count == 1 else "s" }}</span>
  </div>
  <div class="flex items-center gap-2">
    <button
      data-rename-item-group-id="{{ group.id }}"
      data-rename-item-group-matter="{{ matter_id }}"
      class="hidden rounded px-2 py-0.5 text-xs text-gray-500 hover:bg-gray-100 group-hover:inline-flex">
      Rename
    </button>
    <button
      hx-delete="/api/matters/{{ matter_id }}/item-groups/{{ group.id }}"
      hx-target="#item-group-{{ group.id }}"
      hx-swap="outerHTML"
      hx-confirm="Delete group '{{ group.name }}'? Items in this group will become ungrouped."
      class="hidden rounded px-2 py-0.5 text-xs text-red-600 hover:bg-red-50 group-hover:inline-flex">
      Delete
    </button>
  </div>
</li>
```

- [ ] **Step 4: Create the router**

Create `src/cvp/routers/item_groups.py`:

```python
"""ItemGroup CRUD endpoints plus per-evidence pin endpoint."""

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, update

from cvp.db import SessionLocal
from cvp.dependencies import CurrentUser, require_matter_role
from cvp.models import EvidenceFile, Item, ItemGroup
from cvp.services.audit import get_client_ip, write_audit_log
from cvp.services.item_groups import find_or_create

BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")

router = APIRouter()


def _render_li(group: ItemGroup, matter_id: str, item_count: int) -> str:
    return templates.get_template("_item_group_li.html").render(
        group=group, matter_id=matter_id, item_count=item_count
    )


def _item_count(db, group_id: str) -> int:
    return db.query(func.count(Item.id)).filter(Item.item_group_id == group_id).scalar() or 0


@router.post("/api/matters/{matter_id}/item-groups", response_class=HTMLResponse)
def create_item_group(
    request: Request,
    matter_id: str,
    background_tasks: BackgroundTasks,
    name: str = Form(...),
    user: CurrentUser = Depends(require_matter_role("manager")),
) -> HTMLResponse:
    if not name.strip():
        raise HTTPException(status_code=400, detail="Group name required")
    db = SessionLocal()
    try:
        group = find_or_create(db, matter_id, name)
        db.commit()
        db.refresh(group)
        gid = group.id
        html = _render_li(group, matter_id, _item_count(db, gid))
    finally:
        db.close()
    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="item_group.create",
        resource_type="item_group",
        resource_id=gid,
        matter_id=matter_id,
        ip_address=get_client_ip(request),
    )
    return HTMLResponse(html)


@router.patch(
    "/api/matters/{matter_id}/item-groups/{group_id}", response_class=HTMLResponse
)
def rename_item_group(
    request: Request,
    matter_id: str,
    group_id: str,
    background_tasks: BackgroundTasks,
    name: str = Form(...),
    user: CurrentUser = Depends(require_matter_role("manager")),
) -> HTMLResponse:
    if not name.strip():
        raise HTTPException(status_code=400, detail="Group name required")
    db = SessionLocal()
    try:
        group = db.get(ItemGroup, group_id)
        if group is None or group.matter_id != matter_id:
            raise HTTPException(status_code=404, detail="Group not found")
        group.name = name.strip()
        group.name_normalized = name.strip().lower()
        db.commit()
        db.refresh(group)
        html = _render_li(group, matter_id, _item_count(db, group_id))
    finally:
        db.close()
    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="item_group.update",
        resource_type="item_group",
        resource_id=group_id,
        matter_id=matter_id,
        ip_address=get_client_ip(request),
    )
    return HTMLResponse(html)


@router.delete(
    "/api/matters/{matter_id}/item-groups/{group_id}", response_class=HTMLResponse
)
def delete_item_group(
    request: Request,
    matter_id: str,
    group_id: str,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_matter_role("manager")),
) -> HTMLResponse:
    db = SessionLocal()
    try:
        group = db.get(ItemGroup, group_id)
        if group is None or group.matter_id != matter_id:
            raise HTTPException(status_code=404, detail="Group not found")
        # SQLite's ON DELETE SET NULL only fires when PRAGMA foreign_keys=ON.
        # Be explicit so behaviour is identical in SQLite and Postgres.
        db.execute(update(Item).where(Item.item_group_id == group_id).values(item_group_id=None))
        db.execute(
            update(EvidenceFile)
            .where(EvidenceFile.pinned_item_group_id == group_id)
            .values(pinned_item_group_id=None)
        )
        db.delete(group)
        db.commit()
    finally:
        db.close()
    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="item_group.delete",
        resource_type="item_group",
        resource_id=group_id,
        matter_id=matter_id,
        ip_address=get_client_ip(request),
    )
    return HTMLResponse("", status_code=200)
```

- [ ] **Step 5: Register the router in `main.py`**

In `src/cvp/main.py`, add an import alongside the other router imports and an `include_router` line alongside the others. Place after the `rooms` block to keep them grouped:

```python
from cvp.routers import item_groups  # near the other "from cvp.routers import …" lines
```

```python
app.include_router(item_groups.router)  # right after app.include_router(rooms.router)
```

- [ ] **Step 6: Run tests — expect PASS**

Run: `uv run pytest tests/test_item_groups_router.py -v`
Expected: all six tests pass.

- [ ] **Step 7: Format and commit**

```bash
uv run ruff format . && uv run ruff format --check .
git add src/cvp/routers/item_groups.py src/cvp/main.py src/cvp/templates/_item_group_li.html tests/test_item_groups_router.py
git commit -m "feat: add item-groups CRUD endpoints"
```

---

## Task 6: PATCH endpoint to pin a group on an evidence file

**Files:**
- Modify: `src/cvp/routers/item_groups.py`
- Test: `tests/test_item_groups_router.py` (extend)

- [ ] **Step 1: Append the failing tests**

Append to `tests/test_item_groups_router.py`:

```python
def test_pin_evidence_to_group() -> None:
    client, matter_id = _make_matter()
    client.post(f"/api/matters/{matter_id}/item-groups", data={"name": "12"})
    db = SessionLocal()
    try:
        gid = db.query(ItemGroup).filter(ItemGroup.matter_id == matter_id).first().id
        ef = EvidenceFile(matter_id=matter_id, filename="a.jpg", stored_path="a.jpg")
        db.add(ef)
        db.commit()
        db.refresh(ef)
        ef_id = ef.id
    finally:
        db.close()

    r = client.patch(
        f"/api/matters/{matter_id}/evidence/{ef_id}/item-group",
        data={"item_group_id": gid},
    )
    assert r.status_code == 200
    db = SessionLocal()
    try:
        assert db.get(EvidenceFile, ef_id).pinned_item_group_id == gid
    finally:
        db.close()


def test_pin_evidence_clear_with_empty_value() -> None:
    client, matter_id = _make_matter()
    client.post(f"/api/matters/{matter_id}/item-groups", data={"name": "12"})
    db = SessionLocal()
    try:
        gid = db.query(ItemGroup).filter(ItemGroup.matter_id == matter_id).first().id
        ef = EvidenceFile(
            matter_id=matter_id, filename="a.jpg", stored_path="a.jpg",
            pinned_item_group_id=gid,
        )
        db.add(ef)
        db.commit()
        db.refresh(ef)
        ef_id = ef.id
    finally:
        db.close()

    r = client.patch(
        f"/api/matters/{matter_id}/evidence/{ef_id}/item-group",
        data={"item_group_id": ""},
    )
    assert r.status_code == 200
    db = SessionLocal()
    try:
        assert db.get(EvidenceFile, ef_id).pinned_item_group_id is None
    finally:
        db.close()


def test_pin_evidence_new_group_name_creates() -> None:
    client, matter_id = _make_matter()
    db = SessionLocal()
    try:
        ef = EvidenceFile(matter_id=matter_id, filename="a.jpg", stored_path="a.jpg")
        db.add(ef)
        db.commit()
        db.refresh(ef)
        ef_id = ef.id
    finally:
        db.close()
    r = client.patch(
        f"/api/matters/{matter_id}/evidence/{ef_id}/item-group",
        data={"new_item_group_name": "Box C"},
    )
    assert r.status_code == 200
    db = SessionLocal()
    try:
        groups = db.query(ItemGroup).filter(ItemGroup.matter_id == matter_id).all()
        assert len(groups) == 1 and groups[0].name == "Box C"
        assert db.get(EvidenceFile, ef_id).pinned_item_group_id == groups[0].id
    finally:
        db.close()
```

Make sure `EvidenceFile` is imported at the top of the test file.

- [ ] **Step 2: Run tests — expect 404 / 405**

Run: `uv run pytest tests/test_item_groups_router.py -v -k pin_evidence`
Expected: FAIL.

- [ ] **Step 3: Add the endpoint**

In `src/cvp/routers/item_groups.py`, append at the bottom (after `delete_item_group`):

```python
@router.patch(
    "/api/matters/{matter_id}/evidence/{file_id}/item-group",
    response_class=HTMLResponse,
)
def pin_evidence_to_group(
    request: Request,
    matter_id: str,
    file_id: str,
    background_tasks: BackgroundTasks,
    item_group_id: str = Form(""),
    new_item_group_name: str = Form(""),
    user: CurrentUser = Depends(require_matter_role("editor")),
) -> HTMLResponse:
    db = SessionLocal()
    try:
        ef = db.get(EvidenceFile, file_id)
        if ef is None or ef.matter_id != matter_id:
            raise HTTPException(status_code=404, detail="Evidence file not found")

        if new_item_group_name.strip():
            group = find_or_create(db, matter_id, new_item_group_name)
            db.commit()
            db.refresh(group)
            ef.pinned_item_group_id = group.id
        elif item_group_id:
            group = db.get(ItemGroup, item_group_id)
            if group is None or group.matter_id != matter_id:
                raise HTTPException(status_code=400, detail="Group not in matter")
            ef.pinned_item_group_id = group.id
        else:
            ef.pinned_item_group_id = None

        db.commit()
        db.refresh(ef)
    finally:
        db.close()
    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="evidence.pin_item_group",
        resource_type="evidence_file",
        resource_id=file_id,
        matter_id=matter_id,
        ip_address=get_client_ip(request),
    )
    return HTMLResponse("", status_code=200)
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `uv run pytest tests/test_item_groups_router.py -v`
Expected: all tests, including the three new ones, pass.

- [ ] **Step 5: Format and commit**

```bash
uv run ruff format . && uv run ruff format --check .
git add src/cvp/routers/item_groups.py tests/test_item_groups_router.py
git commit -m "feat: PATCH endpoint to pin evidence-file group"
```

---

## Task 7: Rooms & Groups tab UI

**Files:**
- Create: `src/cvp/templates/_groups_panel.html`
- Modify: `src/cvp/templates/_tab_rooms.html`
- Modify: `src/cvp/templates/matter_detail.html` (tab label)
- Modify: `src/cvp/routers/matters.py` *or* `src/cvp/routers/rooms.py` — whichever currently renders `_tab_rooms.html` must pass `item_groups` and per-group `item_count` into the template

- [ ] **Step 1: Identify the render path**

Run: `grep -rn "_tab_rooms.html\|_tab_rooms" src/cvp/`
Look for the route that renders the Rooms tab body. It is almost certainly in `src/cvp/routers/matters.py` (the matter-detail page). Note the exact handler and the template-context dict it builds.

- [ ] **Step 2: Add `item_groups` to the render context**

In the handler identified in Step 1, alongside the existing `rooms=` argument passed to `templates.TemplateResponse(...)`, load and pass:

```python
from sqlalchemy import func
from cvp.models import ItemGroup, Item

item_groups_q = (
    db.query(ItemGroup, func.count(Item.id))
    .outerjoin(Item, Item.item_group_id == ItemGroup.id)
    .filter(ItemGroup.matter_id == matter_id)
    .group_by(ItemGroup.id)
    .order_by(ItemGroup.created_at)
    .all()
)
item_groups = [(g, c) for g, c in item_groups_q]
```

…then add `item_groups=item_groups` to the template render call.

- [ ] **Step 3: Create the groups-panel partial**

Create `src/cvp/templates/_groups_panel.html`:

```html
<div class="space-y-4 mt-6">
  <div class="flex items-center justify-between">
    <h3 class="text-sm font-semibold text-gray-700">Groups ({{ item_groups | length }})</h3>
    <form id="add-item-group-form"
          hx-post="/api/matters/{{ matter.id }}/item-groups"
          hx-target="#item-groups-list"
          hx-swap="beforeend"
          class="flex items-center gap-2">
      <input name="name" placeholder="Group name (e.g. 12, Box A)" required maxlength="100"
             class="rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500">
      <button type="submit"
              class="rounded-md bg-indigo-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-indigo-500">
        Add group
      </button>
    </form>
  </div>

  <ul id="item-groups-list" class="space-y-2">
    {% for group, item_count in item_groups %}
      {% include "_item_group_li.html" %}
    {% else %}
    <li id="item-groups-empty" class="text-sm text-gray-400 italic">
      No groups yet — add one above or have a scan auto-detect a placard.
    </li>
    {% endfor %}
  </ul>
</div>
```

Note: `_item_group_li.html` expects `group` and `item_count`. The for-loop unpacks the tuple into exactly those names. `matter_id` is needed by that partial; pass it via a `with` block since Jinja's `include` inherits parent context, and `matter` is already in scope:

In `_item_group_li.html`, change `{{ matter_id }}` → `{{ matter.id }}` so it can read it from the parent context. Update **all** references in `_item_group_li.html` and the test fixtures accordingly. (No new test changes needed; the router-level tests only assert the response code and DB state.)

- [ ] **Step 4: Include the panel in `_tab_rooms.html`**

In `src/cvp/templates/_tab_rooms.html`, append after the closing `</div>` of the existing rooms block:

```html
{% include "_groups_panel.html" %}
```

- [ ] **Step 5: Rename the tab label**

In `src/cvp/templates/matter_detail.html`, replace:

```python
        ('rooms', 'Rooms'),
```

with:

```python
        ('rooms', 'Rooms & Groups'),
```

(Use Edit; the tab id and template filename stay the same.)

- [ ] **Step 6: Restart dev server and eyeball the tab**

Run: `uv run dev` (in another terminal — or kill any running instance first)
Open: `http://localhost:8000`, sign in, open a matter, click the **Rooms & Groups** tab.
Expected: existing Rooms block on top, new Groups block below, "Add group" form works, deleting a group via the hover button removes it from the list.

- [ ] **Step 7: Format and commit**

```bash
uv run ruff format . && uv run ruff format --check .
git add src/cvp/routers/matters.py src/cvp/templates/_groups_panel.html src/cvp/templates/_tab_rooms.html src/cvp/templates/_item_group_li.html src/cvp/templates/matter_detail.html
git commit -m "feat: Rooms & Groups tab — Groups panel and label rename"
```

---

## Task 8: Per-image group dropdown on the evidence grid

**Files:**
- Create: `src/cvp/templates/_evidence_group_select.html`
- Modify: `src/cvp/templates/_evidence_grid.html`
- Modify: `src/cvp/routers/evidence.py` (or wherever `_evidence_grid.html` is rendered — likely `routers/matters.py`)
- Modify: `src/cvp/static/app.js` — delegated listener for `+ New group…` sentinel
- Test: `tests/test_evidence_group_select.py` (new)

- [ ] **Step 1: Identify render path and add `item_groups` to context**

Run: `grep -rn "_evidence_grid.html" src/cvp/`
In each render path, add to the template context: `item_groups=db.query(ItemGroup).filter(ItemGroup.matter_id == matter_id).order_by(ItemGroup.created_at).all()`.

- [ ] **Step 2: Write the failing test**

Create `tests/test_evidence_group_select.py`:

```python
"""Verifies the per-image group dropdown renders and persists the selection."""

from fastapi.testclient import TestClient

from cvp.db import SessionLocal
from cvp.main import app
from cvp.models import EvidenceFile, ItemGroup, Matter
from tests.test_item_groups_router import _make_matter


def test_evidence_grid_includes_group_dropdown() -> None:
    client, matter_id = _make_matter()
    db = SessionLocal()
    try:
        ef = EvidenceFile(matter_id=matter_id, filename="a.jpg", stored_path="a.jpg", kind="image")
        db.add(ef)
        db.commit()
        db.refresh(ef)
        ef_id = ef.id
    finally:
        db.close()

    r = client.get(f"/matters/{matter_id}")  # matter detail page
    assert r.status_code == 200
    body = r.text
    # The select element appears for this file with at least Auto-detect + + New group...
    assert f'data-evidence-group-select="{ef_id}"' in body
    assert "Auto-detect" in body
    assert "+ New group" in body
```

If the matter-detail URL differs, replace it accordingly (check `routers/matters.py`).

- [ ] **Step 3: Run the test — expect FAIL**

Run: `uv run pytest tests/test_evidence_group_select.py -v`
Expected: FAIL (no select rendered yet).

- [ ] **Step 4: Create the dropdown partial**

Create `src/cvp/templates/_evidence_group_select.html`:

```html
{# Per-image group dropdown.
   Expects: f (EvidenceFile), item_groups (list[ItemGroup]), matter_id #}
<form class="mt-1"
      hx-patch="/api/matters/{{ matter_id }}/evidence/{{ f.id }}/item-group"
      hx-trigger="change from:select[name='item_group_id']"
      hx-swap="none">
  <label class="text-xs text-gray-500">Group</label>
  <select name="item_group_id"
          data-evidence-group-select="{{ f.id }}"
          class="mt-0.5 block w-full rounded border border-gray-300 px-1.5 py-0.5 text-xs focus:border-indigo-500 focus:outline-none">
    <option value="" {% if not f.pinned_item_group_id %}selected{% endif %}>Auto-detect</option>
    {% for g in item_groups %}
    <option value="{{ g.id }}" {% if f.pinned_item_group_id == g.id %}selected{% endif %}>{{ g.name }}</option>
    {% endfor %}
    <option value="__new__">+ New group…</option>
  </select>
</form>
```

- [ ] **Step 5: Include the partial in `_evidence_grid.html`**

In `src/cvp/templates/_evidence_grid.html`, insert this line *inside* the `<div class="px-2 py-1.5">` block, after the size paragraph and before the `{% if f.kind == "image" %}` block (so the dropdown shows for both scanned and unscanned images):

```html
{% if f.kind == "image" and item_groups is defined %}
  {% include "_evidence_group_select.html" %}
{% endif %}
```

- [ ] **Step 6: Add the delegated listener for `+ New group…`**

In `src/cvp/static/app.js`, append at the bottom (following the existing delegated-listener pattern at lines 225–275):

```javascript
// Delegated change: data-evidence-group-select → handle "+ New group…" sentinel.
// Selecting __new__ prompts for a name, posts via fetch, then refreshes the page
// so the new group is present in every dropdown.
document.addEventListener('change', function (e) {
    var sel = e.target;
    if (!sel.matches || !sel.matches('select[data-evidence-group-select]')) return;
    if (sel.value !== '__new__') return;
    var name = window.prompt('New group name:');
    if (!name || !name.trim()) {
        sel.value = '';
        sel.dispatchEvent(new Event('change', { bubbles: true }));
        return;
    }
    var fileId = sel.dataset.evidenceGroupSelect;
    var matterMatch = sel.closest('form').getAttribute('hx-patch') || '';
    // hx-patch is /api/matters/{matter_id}/evidence/{file_id}/item-group
    var matterId = matterMatch.split('/')[3];
    var fd = new FormData();
    fd.append('new_item_group_name', name.trim());
    fetch('/api/matters/' + matterId + '/evidence/' + fileId + '/item-group', {
        method: 'PATCH',
        body: fd,
        credentials: 'same-origin',
    }).then(function (r) {
        if (r.ok) window.location.reload();
        else { sel.value = ''; alert('Could not create group.'); }
    });
});
```

- [ ] **Step 7: Run tests — expect PASS**

Run: `uv run pytest tests/test_evidence_group_select.py -v`
Expected: PASS.

Also run: `uv run pytest tests/test_item_groups_router.py -v`
Expected: still PASS.

- [ ] **Step 8: Manual smoke check**

Restart `uv run dev`, open a matter, upload (or open) an image in Evidence. The dropdown reads `Auto-detect`, you can pick an existing group, or `+ New group…` to create one inline; selecting a group persists across reload.

- [ ] **Step 9: Format and commit**

```bash
uv run ruff format . && uv run ruff format --check .
git add src/cvp/templates/_evidence_grid.html src/cvp/templates/_evidence_group_select.html src/cvp/static/app.js src/cvp/routers/ tests/test_evidence_group_select.py
git commit -m "feat: per-image Group dropdown on the evidence grid"
```

---

## Task 9: Group field on the item edit form

**Files:**
- Modify: `src/cvp/routers/items.py` (`_get_context`, `_item_row_edit_html`, `update_item`)
- Modify: `src/cvp/templates/_item_row_edit.html`
- Modify: `src/cvp/templates/_item_row.html` (display the group name in view mode — optional, but the item count on the Groups panel depends on the assignment working, so verify here)
- Test: `tests/test_items_group_assignment.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_items_group_assignment.py`:

```python
"""Tests the item edit form's Group field (existing + create-new)."""

from cvp.db import SessionLocal
from cvp.models import Item, ItemGroup
from tests.test_item_groups_router import _make_matter


def _make_item(matter_id: str) -> str:
    db = SessionLocal()
    try:
        from cvp.models import Category
        cat = db.query(Category).first()
        item = Item(matter_id=matter_id, category_id=cat.id, description="thing")
        db.add(item)
        db.commit()
        db.refresh(item)
        return item.id
    finally:
        db.close()


def _base_form(category_id: int) -> dict:
    """Required fields for the PATCH /api/items/{id} endpoint."""
    return {
        "description": "thing",
        "category_id": str(category_id),
        "room_id": "",
        "quantity": "1",
        "age_years": "0",
        "condition": "average",
        "rcv_unit_dollars": "0",
        "brand": "",
        "model_num": "",
        "notes": "",
        "source_retailer": "",
        "source_url": "",
        "match_type": "exact",
        "acv_override_dollars": "",
        "acv_override_reason": "",
        "confirmed": "false",
    }


def test_assign_existing_group() -> None:
    client, matter_id = _make_matter(role="editor")
    item_id = _make_item(matter_id)
    db = SessionLocal()
    try:
        from cvp.models import Category
        cat = db.query(Category).first().id
        g = ItemGroup(matter_id=matter_id, name="12", name_normalized="12")
        db.add(g)
        db.commit()
        db.refresh(g)
        gid = g.id
    finally:
        db.close()

    form = _base_form(cat)
    form["item_group_id"] = gid
    r = client.patch(f"/api/items/{item_id}", data=form)
    assert r.status_code == 200
    db = SessionLocal()
    try:
        assert db.get(Item, item_id).item_group_id == gid
    finally:
        db.close()


def test_assign_creates_new_group() -> None:
    client, matter_id = _make_matter(role="editor")
    item_id = _make_item(matter_id)
    db = SessionLocal()
    try:
        from cvp.models import Category
        cat = db.query(Category).first().id
    finally:
        db.close()

    form = _base_form(cat)
    form["new_item_group_name"] = "Box B"
    r = client.patch(f"/api/items/{item_id}", data=form)
    assert r.status_code == 200
    db = SessionLocal()
    try:
        item = db.get(Item, item_id)
        groups = db.query(ItemGroup).filter(ItemGroup.matter_id == matter_id).all()
        assert len(groups) == 1
        assert groups[0].name == "Box B"
        assert item.item_group_id == groups[0].id
    finally:
        db.close()


def test_clear_group_with_empty() -> None:
    client, matter_id = _make_matter(role="editor")
    item_id = _make_item(matter_id)
    db = SessionLocal()
    try:
        from cvp.models import Category
        cat = db.query(Category).first().id
        g = ItemGroup(matter_id=matter_id, name="12", name_normalized="12")
        db.add(g)
        db.commit()
        db.refresh(g)
        item = db.get(Item, item_id)
        item.item_group_id = g.id
        db.commit()
    finally:
        db.close()

    form = _base_form(cat)
    form["item_group_id"] = ""
    r = client.patch(f"/api/items/{item_id}", data=form)
    assert r.status_code == 200
    db = SessionLocal()
    try:
        assert db.get(Item, item_id).item_group_id is None
    finally:
        db.close()
```

- [ ] **Step 2: Run tests — expect failure (the router doesn't read `item_group_id`)**

Run: `uv run pytest tests/test_items_group_assignment.py -v`
Expected: FAIL.

- [ ] **Step 3: Extend the items router**

In `src/cvp/routers/items.py`:

a. Update the imports to include `ItemGroup` and `find_or_create`:

```python
from cvp.models import Category, EvidenceFile, Item, ItemGroup, Room, SerpSearch  # add ItemGroup
from cvp.services.item_groups import find_or_create
```

(If `EvidenceFile` isn't already imported, leave that alone — only add `ItemGroup`.)

b. Replace `_get_context` to also return item groups:

```python
def _get_context(matter_id: str, db):
    categories = db.query(Category).order_by(Category.id).all()
    rooms = db.query(Room).filter(Room.matter_id == matter_id).order_by(Room.sort_order).all()
    item_groups = (
        db.query(ItemGroup)
        .filter(ItemGroup.matter_id == matter_id)
        .order_by(ItemGroup.created_at)
        .all()
    )
    return categories, rooms, item_groups
```

c. Update **every** call to `_get_context` in this file to unpack three values:

Search the file for `categories, rooms = _get_context(`. Each call site becomes:

```python
categories, rooms, item_groups = _get_context(matter_id, db)
```

…and where `_item_row_html` / `_item_row_edit_html` / `_items_tbody.html` is rendered, pass `item_groups=item_groups`. Update the helper signatures to accept it:

```python
def _item_row_html(item: Item, categories: list, rooms: list, item_groups: list) -> str:
    return templates.get_template("_item_row.html").render(
        item=item, categories=categories, rooms=rooms, item_groups=item_groups
    )


def _item_row_edit_html(
    item: Item,
    categories: list,
    rooms: list,
    item_groups: list,
    latest_by_crop: dict | None = None,
    display_by_crop: dict | None = None,
) -> str:
    return templates.get_template("_item_row_edit.html").render(
        item=item,
        categories=categories,
        rooms=rooms,
        item_groups=item_groups,
        conditions=CONDITIONS,
        public_base_url=settings.public_base_url,
        latest_by_crop=latest_by_crop or {},
        display_by_crop=display_by_crop or {},
    )


def _items_tbody_html(matter_id: str, db) -> str:
    items = (
        db.query(Item)
        .filter(Item.matter_id == matter_id)
        .options(selectinload(Item.crops))
        .order_by(Item.line_number)
        .all()
    )
    categories, rooms, item_groups = _get_context(matter_id, db)
    return templates.get_template("_items_tbody.html").render(
        items=items, categories=categories, rooms=rooms, item_groups=item_groups, conditions=CONDITIONS
    )
```

d. Add two `Form()` parameters to `update_item` and `create_item` and wire them:

In `update_item`, after `confirmed: bool = Form(False)` and before the function body:

```python
    item_group_id: str = Form(""),
    new_item_group_name: str = Form(""),
```

Then, inside the `try:` block of `update_item`, right after the existing room/category assignments, before `_compute_and_set_totals`, add:

```python
        if new_item_group_name.strip():
            ig = find_or_create(db, item.matter_id, new_item_group_name)
            db.flush()
            item.item_group_id = ig.id
        elif item_group_id:
            ig = db.get(ItemGroup, item_group_id)
            if ig is None or ig.matter_id != item.matter_id:
                raise HTTPException(status_code=400, detail="Group not in matter")
            item.item_group_id = ig.id
        else:
            item.item_group_id = None
```

In `create_item`, do the same: add the two form params and the same block right before `_compute_and_set_totals(item, cat)`. For `create_item` the matter id is the path param, so use `matter_id` instead of `item.matter_id` in the call to `find_or_create`.

- [ ] **Step 4: Update the edit-form template**

In `src/cvp/templates/_item_row_edit.html`, inside Row 1 (the 12-column grid), after the existing Room `<div class="col-span-2">` block (the one with the Room `<select>`), reduce the Category column-span from `col-span-2` to `col-span-1` (so Group fits) and **before** the Category block insert:

```html
        <div class="col-span-2">
          <label class="text-xs font-medium text-gray-600">Group</label>
          <select name="item_group_id"
                  data-item-group-select="{{ item.id }}"
                  class="mt-0.5 block w-full rounded border border-gray-300 px-2 py-1 text-sm focus:border-indigo-500 focus:outline-none">
            <option value="" {% if not item.item_group_id %}selected{% endif %}>— none —</option>
            {% for g in item_groups %}
            <option value="{{ g.id }}" {% if item.item_group_id == g.id %}selected{% endif %}>{{ g.name }}</option>
            {% endfor %}
            <option value="__new__">+ New group…</option>
          </select>
          <input type="hidden" name="new_item_group_name" value="" data-new-item-group-name="{{ item.id }}">
        </div>
```

Adjust the surrounding columns so the row still totals 12 columns: change Description from `col-span-4` to `col-span-3` and Category from `col-span-2` to `col-span-2` (totals: 3+2+2+2+2+1 = 12). Re-check the file after the edit to confirm.

- [ ] **Step 5: Add a delegated listener for the item-edit-form sentinel**

In `src/cvp/static/app.js`, append at the bottom:

```javascript
// Delegated change: data-item-group-select → handle "+ New group…" by prompting and
// stashing the name in the sibling hidden input. The form's PATCH then reads it.
document.addEventListener('change', function (e) {
    var sel = e.target;
    if (!sel.matches || !sel.matches('select[data-item-group-select]')) return;
    var itemId = sel.dataset.itemGroupSelect;
    var hidden = document.querySelector('input[data-new-item-group-name="' + itemId + '"]');
    if (sel.value === '__new__') {
        var name = window.prompt('New group name:');
        if (name && name.trim()) {
            if (hidden) hidden.value = name.trim();
            // Visually reset the select to empty so the post-save view doesn't
            // submit `__new__`; the hidden input is what creates the group.
            sel.value = '';
        } else {
            sel.value = '';
            if (hidden) hidden.value = '';
        }
    } else {
        if (hidden) hidden.value = '';
    }
});
```

- [ ] **Step 6: Run tests — expect PASS**

Run: `uv run pytest tests/test_items_group_assignment.py -v`
Expected: all three tests pass.

Also run the broader items suite to confirm no regressions:

Run: `uv run pytest tests/test_items_template.py tests/test_item_groups_router.py -v`
Expected: PASS.

- [ ] **Step 7: Format and commit**

```bash
uv run ruff format . && uv run ruff format --check .
git add src/cvp/routers/items.py src/cvp/templates/_item_row_edit.html src/cvp/static/app.js tests/test_items_group_assignment.py
git commit -m "feat: Group field on item edit form (assign existing or create new)"
```

---

## Task 10: Vision prompt + parser — placard_text field

**Files:**
- Modify: `src/cvp/services/vision_prompts.py`
- Modify: `src/cvp/services/vision.py` — `_parse_response`
- Test: `tests/test_vision_prompts_placard.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_vision_prompts_placard.py`:

```python
"""Tests for the placard-aware vision prompt and response parser."""

import json

from cvp.services.vision import _parse_response
from cvp.services.vision_prompts import SCAN_PROMPT_VERSION, build_scan_prompt


def test_prompt_version_bumped() -> None:
    assert SCAN_PROMPT_VERSION == "v4"


def test_prompt_mentions_placard_field() -> None:
    prompt = build_scan_prompt(800, 600)
    assert "placard_text" in prompt
    assert "placard" in prompt.lower()


def test_parse_response_object_with_items_and_placard() -> None:
    payload = json.dumps({
        "items": [{"description": "TV"}, {"description": "lamp"}],
        "placard_text": "12",
    })
    items, placard = _parse_response(payload)
    assert len(items) == 2
    assert placard == "12"


def test_parse_response_object_with_empty_placard() -> None:
    payload = json.dumps({"items": [{"description": "TV"}], "placard_text": ""})
    items, placard = _parse_response(payload)
    assert len(items) == 1
    assert placard == ""


def test_parse_response_legacy_array_returns_empty_placard() -> None:
    """Older prompt versions / non-compliant models still return a JSON array."""
    payload = json.dumps([{"description": "TV"}])
    items, placard = _parse_response(payload)
    assert len(items) == 1
    assert placard == ""


def test_parse_response_garbage_returns_empty() -> None:
    items, placard = _parse_response("not json")
    assert items == []
    assert placard == ""
```

- [ ] **Step 2: Run tests — expect FAIL**

Run: `uv run pytest tests/test_vision_prompts_placard.py -v`
Expected: FAIL — prompt version is v3, parser returns a list not a tuple.

- [ ] **Step 3: Update the prompt**

In `src/cvp/services/vision_prompts.py`:

- Change `SCAN_PROMPT_VERSION = "v3"` to `SCAN_PROMPT_VERSION = "v4"`.
- Rewrite `_SCAN_PROMPT_V3_TEMPLATE` (the format string body) so that instead of "Return ONLY a JSON array … Each object must have these exact keys", it returns a JSON object. Also rename the constant to `_SCAN_PROMPT_V4_TEMPLATE` (and update `build_scan_prompt` to reference it). The key change: ask for `{ "items": [...], "placard_text": "..." }` and add a placard-exclusion block. Insert this paragraph near the top of the template, just after the dimensions sentence:

```text
Sometimes the photo contains a numbered or labeled placard, sticky note, card, or
organizational marker placed in the frame by the photographer. This is metadata,
NOT a personal property item. Never include the placard, sticky note, or marker as
an item in the items array. Instead, return the raw text it shows in a separate
top-level field called "placard_text". If no placard is visible, return
"placard_text": "".
```

And replace the line "Return ONLY a JSON array with no preamble, explanation, or markdown fences. Each object must have these exact keys:" with:

```text
Return ONLY a JSON object with these exact top-level keys: "items" (array) and
"placard_text" (string, empty when no placard is visible). No preamble,
explanation, or markdown fences. Each object inside "items" must have these
exact keys:
```

Leave the rest of the per-item key list and the closing "Rules:" block unchanged. The final "Return ONLY" sentence should also be updated: replace "Return ONLY the JSON array." with "Return ONLY the JSON object."

- [ ] **Step 4: Update `_parse_response`**

In `src/cvp/services/vision.py`, replace the existing `_parse_response` with:

```python
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
            items = parsed.get("items") if isinstance(parsed.get("items"), list) else []
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
```

- [ ] **Step 5: Update the single caller in `vision.py`**

The caller currently does `parsed = _parse_response(raw_text)` then `for raw_item in parsed:`. Change it to unpack the tuple:

```python
        parsed_items, placard_text = _parse_response(raw_text)
        # … later …
        for raw_item in parsed_items:
```

Leave `placard_text` unused for now — Task 11 wires it up.

- [ ] **Step 6: Run tests — expect PASS**

Run: `uv run pytest tests/test_vision_prompts_placard.py tests/test_vision_prompts.py tests/test_vision_service.py -v`
Expected: all pass. If any pre-existing tests check the prompt version literal, they may need updating to `"v4"`. Update them in place — do not add a compatibility shim.

- [ ] **Step 7: Format and commit**

```bash
uv run ruff format . && uv run ruff format --check .
git add src/cvp/services/vision_prompts.py src/cvp/services/vision.py tests/test_vision_prompts_placard.py tests/test_vision_prompts.py tests/test_vision_service.py
git commit -m "feat: vision prompt v4 — placard_text field separate from items"
```

---

## Task 11: Vision worker applies the effective group

**Files:**
- Modify: `src/cvp/services/vision.py` (inside the per-image scan logic around lines 250–320)
- Test: `tests/test_vision_worker_item_groups.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_vision_worker_item_groups.py`:

```python
"""End-to-end tests for the vision worker's group-assignment logic.

OpenRouter is monkeypatched; the test exercises real parsing + worker.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from cvp.db import SessionLocal
from cvp.models import Category, EvidenceFile, Item, ItemGroup, Matter
from cvp.models_vision import VisionModel
from cvp.services.vision import _process_image  # may be a private helper — see below


def _setup_matter_with_file(pinned_group_name: str | None = None) -> tuple[str, str]:
    db = SessionLocal()
    try:
        if db.query(Category).count() == 0:
            db.add(Category(id=1, name="Misc", useful_life_years=10, acv_floor_pct=0.2))
        m = Matter(firm_name="T")
        db.add(m)
        db.commit()
        db.refresh(m)
        ef = EvidenceFile(matter_id=m.id, filename="x.jpg", stored_path="x.jpg", kind="image")
        db.add(ef)
        if pinned_group_name:
            g = ItemGroup(
                matter_id=m.id, name=pinned_group_name, name_normalized=pinned_group_name.lower()
            )
            db.add(g)
            db.commit()
            db.refresh(g)
            ef.pinned_item_group_id = g.id
        db.commit()
        db.refresh(ef)
        return m.id, ef.id
    finally:
        db.close()
```

The exact patch target / function name and test shape depend on how `_process_image` is structured. If `_process_image` does the full scan (image read + HTTP call + DB writes), monkeypatch `cvp.services.openrouter.call_vision` to return a canned JSON string and avoid touching disk by also stubbing `_downscale` / the image-bytes load. If that turns out to require excessive plumbing, write a smaller test that **directly exercises the group-resolution helper** (see Step 4) instead of running the whole worker.

Concretely, after Step 4 introduces `_resolve_effective_item_group_id`, structure the tests around that helper:

```python
from cvp.db import SessionLocal
from cvp.services.vision import _resolve_effective_item_group_id


def test_pinned_wins_over_placard() -> None:
    matter_id, ef_id = _setup_matter_with_file(pinned_group_name="A")
    db = SessionLocal()
    try:
        ef = db.get(EvidenceFile, ef_id)
        gid = _resolve_effective_item_group_id(db, ef, placard_text="99")
        assert gid is not None
        # Pinned A still applies, even though placard says 99.
        g = db.get(ItemGroup, gid)
        assert g.name == "A"
    finally:
        db.close()


def test_placard_creates_group_when_no_pin() -> None:
    matter_id, ef_id = _setup_matter_with_file()
    db = SessionLocal()
    try:
        ef = db.get(EvidenceFile, ef_id)
        gid = _resolve_effective_item_group_id(db, ef, placard_text="12")
        db.commit()
        assert gid is not None
        groups = db.query(ItemGroup).filter(ItemGroup.matter_id == matter_id).all()
        assert len(groups) == 1 and groups[0].name == "12"
        assert groups[0].id == gid
    finally:
        db.close()


def test_placard_reuses_existing_group() -> None:
    matter_id, ef_id = _setup_matter_with_file()
    db = SessionLocal()
    try:
        # Pre-seed the group with a different-case name.
        db.add(ItemGroup(matter_id=matter_id, name="Box A", name_normalized="box a"))
        db.commit()
        ef = db.get(EvidenceFile, ef_id)
        gid = _resolve_effective_item_group_id(db, ef, placard_text="box a")
        db.commit()
        assert (
            db.query(ItemGroup).filter(ItemGroup.matter_id == matter_id).count() == 1
        )
        assert db.get(ItemGroup, gid).name == "Box A"
    finally:
        db.close()


def test_no_pin_no_placard_yields_none() -> None:
    matter_id, ef_id = _setup_matter_with_file()
    db = SessionLocal()
    try:
        ef = db.get(EvidenceFile, ef_id)
        gid = _resolve_effective_item_group_id(db, ef, placard_text="")
        assert gid is None
    finally:
        db.close()


def test_pin_with_conflicting_placard_logs_at_info(caplog) -> None:
    matter_id, ef_id = _setup_matter_with_file(pinned_group_name="A")
    db = SessionLocal()
    try:
        ef = db.get(EvidenceFile, ef_id)
        with caplog.at_level("INFO", logger="cvp.services.vision"):
            _resolve_effective_item_group_id(db, ef, placard_text="99")
        # Mismatch is logged for auditability.
        assert any(
            "placard" in r.message.lower() and "99" in r.message
            for r in caplog.records
        )
    finally:
        db.close()
```

- [ ] **Step 2: Run tests — expect ImportError**

Run: `uv run pytest tests/test_vision_worker_item_groups.py -v`
Expected: FAIL — `_resolve_effective_item_group_id` doesn't exist.

- [ ] **Step 3: Add the helper to `vision.py`**

In `src/cvp/services/vision.py`:

a. Add `ItemGroup` to the existing top-of-file imports block from `cvp.models`:

```python
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
```

b. Add a new import beneath the existing service imports:

```python
from cvp.services.item_groups import find_or_create
```

c. Near the other module-level helpers (above `_process_image` or wherever the scan logic lives), add:

```python
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
                    "vision: placard mismatch — pinned group %s (%r), detected %r on evidence_file %s",
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
```

- [ ] **Step 4: Wire the helper into the per-image scan**

In the scan loop (around lines 250–295 of `vision.py`), right before the `for raw_item in parsed_items:` line introduced in Task 10, add:

```python
        effective_item_group_id = _resolve_effective_item_group_id(db, ef, placard_text)
```

Then inside the loop, on the `Item(` construction, add the field:

```python
            item = Item(
                matter_id=job.matter_id,
                category_id=cat_id,
                line_number=max_line,
                description=description,
                # ... existing fields ...
                item_group_id=effective_item_group_id,
                # ... existing fields ...
            )
```

- [ ] **Step 5: Run tests — expect PASS**

Run: `uv run pytest tests/test_vision_worker_item_groups.py -v`
Expected: all five tests pass.

Then run the broader vision tests to confirm no regressions:

Run: `uv run pytest tests/test_vision_service.py tests/test_vision_worker.py tests/test_vision_scan_all.py -v`
Expected: all pass.

- [ ] **Step 6: Format and commit**

```bash
uv run ruff format . && uv run ruff format --check .
git add src/cvp/services/vision.py tests/test_vision_worker_item_groups.py
git commit -m "feat: vision worker applies pinned-or-placard group to extracted items"
```

---

## Task 12: Final integration smoke + push

**Files:**
- None — verification only.

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest -q`
Expected: all green.

- [ ] **Step 2: Run lint and format check**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: both pass (`All checks passed!` and zero would-be-reformatted files).

- [ ] **Step 3: Manual smoke test — flip through the feature end-to-end**

Boot: `uv run dev`

In one browser tab, signed in as a manager-ish user:

a. Open a matter. The tab list shows **"Rooms & Groups"**.
b. Inside the Rooms & Groups tab, the new **Groups** panel is below the Rooms panel.
c. Add a group named `12`. It appears in the list with `0 items`.
d. Go to the **Evidence** tab. For each image card, an `Auto-detect` dropdown appears below the file name. Pick `12` for one image and reload — the choice persists.
e. Edit an existing item; the edit row shows a **Group** field with `(— none —)`, the existing groups, and `+ New group…`. Pick `12`, save. Reopen the row — `12` is still selected. Visit the Groups panel — the item count is now `1`.
f. From the edit form, pick `+ New group…`, type `Garage shelf 2`. After save, the new group is created and assigned. The dropdown on the evidence grid (refresh the page) now also lists `Garage shelf 2`.
g. Delete the `12` group from the Groups panel — confirm. The item that was tagged `12` goes back to ungrouped (verify in the item edit row). The image pinned to `12` reverts to `Auto-detect`.
h. If the test environment supports it: run a real vision scan against a sample image with a placard reading "Box 9" and verify (i) `Box 9` group is created, (ii) items from the scan are tagged with `Box 9`, (iii) no item description says "placard" or "Box 9".

- [ ] **Step 4: Push the branch**

```bash
git push -u origin feat/item-groups-spec
```

Confirm: the remote branch exists; the PR can be opened from the GitHub UI when ready. Do **not** open the PR from this plan — leave that to the user.

---

## Self-review against the spec

After all tasks complete, the engineer should verify the following spec items are implemented and tested:

- ✅ Group lives on the Matter (Task 1, FK to `matters.id`).
- ✅ Free-text name with optional sentinel "auto-detect" via `pinned_item_group_id IS NULL` (Tasks 1, 3, 8).
- ✅ Case + whitespace dedupe via `name_normalized` unique index (Task 1) and `find_or_create` (Task 2).
- ✅ Auto-create on placard detection (Tasks 10, 11).
- ✅ Pin-wins-over-placard conflict rule with INFO log on mismatch (Task 11).
- ✅ Selection persists on EvidenceFile (Task 3, 6, 8).
- ✅ Item edit form combobox (Task 9).
- ✅ Rooms tab renamed to "Rooms & Groups" with Groups panel (Task 7).
- ✅ Group delete `ON DELETE SET NULL` on both `items.item_group_id` and `evidence_files.pinned_item_group_id` (Tasks 3, 4, 5).
- ✅ Placard exclusion via dedicated JSON field, not item filter (Task 10).
- ✅ Group as `ItemGroup` to avoid collision with auth `Group` (Task 1).
- ✅ Migration uses `batch_alter_table` for SQLite compatibility (Task 4).
- ❎ Items tab Group column / filter — **deferred to backlog**, not in this plan.
- ❎ Group display in PDF / CSV exports — **deferred to backlog**, not in this plan.

Out-of-scope follow-ups (not implemented; add to `docs/BACKLOG.md` if not already present): Group merge/split tooling, multiple placards per image, per-room placard scope.
