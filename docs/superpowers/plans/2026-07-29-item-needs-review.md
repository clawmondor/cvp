# Item "Needs review" Flag Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a manual `needs_review` boolean to items that flags them for a second look without removing them from previews or exports.

**Architecture:** `needs_review` is a third orthogonal boolean on `Item`, independent of `confirmed`/`excluded`. It never touches export membership (`confirmed and not excluded` stays the sole gate). Manual toggle only, surfaced as an amber pill in the row, an edit-form checkbox, a status-filter option, and a summary count.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.x, Alembic, Jinja2, HTMX, Tailwind (CDN), pytest.

## Global Constraints

- Currency is always integer cents; never floats. (Not touched by this feature.)
- Never use inline JS event handlers (`onclick=` etc.). Interactivity via HTMX attributes / `data-*` only. CSP has no `unsafe-inline`.
- Type hints everywhere; modern syntax (`X | None`).
- Run `uv run ruff format .` then `uv run ruff format --check .` before every commit; line length 100.
- Tests live in `tests/` mirroring `src/cvp/`.
- Do NOT change `csv_export.py`, `pdf_generator.py`, or any Xactimate CSV column.
- Every task's step uses `uv run` for pytest/ruff/alembic.
- Current Alembic head is `b0fd3df9f4a6` (`20260723_..._retail_value_shipping`).

---

### Task 1: Add `needs_review` column to the model + migration

**Files:**
- Modify: `src/cvp/models.py:174-175` (add column next to `confirmed`/`excluded`)
- Create: `migrations/versions/20260729_<rev>_add_needs_review_to_items.py`
- Test: `tests/test_item_needs_review_model.py`

**Interfaces:**
- Produces: `Item.needs_review: bool` — SQLAlchemy `Mapped[bool]` column, default `False`, NOT NULL, `server_default="0"`. Later tasks filter/read this attribute.

- [ ] **Step 1: Write the failing test**

Create `tests/test_item_needs_review_model.py`:

```python
"""The needs_review column defaults to False and is independent of confirmed."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cvp.models_vision  # noqa: F401
from cvp.models import Base, Category, Item, Matter

MATTER_ID = "m-nr"


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    s.add(Matter(id=MATTER_ID, policyholder_name="P", loss_type="total_loss"))
    s.add(Category(id=1, name="C", useful_life_years=5, acv_floor_pct=0.2))
    s.commit()
    yield s
    s.close()


def test_needs_review_defaults_false(db):
    it = Item(matter_id=MATTER_ID, category_id=1, description="x", confirmed=True)
    db.add(it)
    db.commit()
    db.refresh(it)
    assert it.needs_review is False


def test_needs_review_independent_of_confirmed(db):
    it = Item(
        matter_id=MATTER_ID,
        category_id=1,
        description="x",
        confirmed=True,
        needs_review=True,
    )
    db.add(it)
    db.commit()
    db.refresh(it)
    assert it.confirmed is True
    assert it.needs_review is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_item_needs_review_model.py -v`
Expected: FAIL — `TypeError`/`AttributeError` (`'needs_review' is an invalid keyword argument for Item`).

- [ ] **Step 3: Add the column to the model**

In `src/cvp/models.py`, immediately after the `excluded` column (line 175):

```python
    needs_review: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="0"
    )
```

(`Boolean` is already imported.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_item_needs_review_model.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Create the migration**

Create `migrations/versions/20260729_a1b2c3d4e5f6_add_needs_review_to_items.py`:

```python
"""add needs_review to items

Revision ID: a1b2c3d4e5f6
Revises: b0fd3df9f4a6
Create Date: 2026-07-29 00:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'b0fd3df9f4a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "items",
        sa.Column("needs_review", sa.Boolean(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    with op.batch_alter_table("items") as batch_op:
        batch_op.drop_column("needs_review")
```

- [ ] **Step 6: Verify the migration applies**

Run: `uv run alembic upgrade head && uv run alembic current`
Expected: no error; current revision is `a1b2c3d4e5f6 (head)`.

- [ ] **Step 7: Format and commit**

```bash
uv run ruff format . && uv run ruff format --check .
git add src/cvp/models.py migrations/versions/20260729_a1b2c3d4e5f6_add_needs_review_to_items.py tests/test_item_needs_review_model.py
git commit -m "feat(items): add needs_review column + migration"
```

---

### Task 2: Filter items by `needs_review`

**Files:**
- Modify: `src/cvp/routers/items.py:65` (`_STATUS_VALUES`), `src/cvp/routers/items.py:111-122` (`_apply_item_filters`)
- Modify: `src/cvp/templates/_items_controls.html:39-45` (status `<option>` list)
- Test: `tests/test_items_filter_sort.py` (add a test)

**Interfaces:**
- Consumes: `Item.needs_review` from Task 1.
- Produces: status value `"needs_review"` accepted by `_parse_item_filters` and applied by `_apply_item_filters`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_items_filter_sort.py`:

```python
def test_filter_status_needs_review(db):
    _add(db, line_number=1, description="flagged", needs_review=True)
    _add(db, line_number=2, description="clean", needs_review=False)
    f = ItemFilters(status="needs_review")
    assert _descs(_build_items_query(db, MATTER_ID, f).all()) == ["flagged"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_items_filter_sort.py::test_filter_status_needs_review -v`
Expected: FAIL — status coerced to `"all"` (not in `_STATUS_VALUES`), returns both rows.

- [ ] **Step 3: Add `needs_review` to allowed statuses**

`src/cvp/routers/items.py:65`:

```python
_STATUS_VALUES = {"all", "unconfirmed", "confirmed", "excluded", "missing_price", "needs_review"}
```

- [ ] **Step 4: Add the filter branch**

In `_apply_item_filters`, after the `missing_price` branch (after line 122):

```python
    elif f.status == "needs_review":
        query = query.filter(Item.needs_review.is_(True))
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_items_filter_sort.py::test_filter_status_needs_review -v`
Expected: PASS.

- [ ] **Step 6: Add the dropdown option**

In `src/cvp/templates/_items_controls.html`, add to the status list (after the `("missing_price", "Missing price")` tuple):

```jinja
        ("needs_review", "Needs review"),
```

- [ ] **Step 7: Run the full filter suite + format + commit**

```bash
uv run pytest tests/test_items_filter_sort.py -v
uv run ruff format . && uv run ruff format --check .
git add src/cvp/routers/items.py src/cvp/templates/_items_controls.html tests/test_items_filter_sort.py
git commit -m "feat(items): filter by needs_review status"
```

Expected: all filter tests PASS.

---

### Task 3: `needs_review_count` in the items summary

**Files:**
- Modify: `src/cvp/routers/items.py:241-248` (`compute_items_totals` return dict)
- Modify: `src/cvp/templates/_items_summary.html:6-10` (render the count)
- Test: `tests/test_items_summary.py` (add tests)

**Interfaces:**
- Consumes: `Item.needs_review` from Task 1.
- Produces: `compute_items_totals(...)["needs_review_count"]: int` — count of the matter's items with `needs_review is True` (independent of confirmed/excluded).

- [ ] **Step 1: Write the failing tests**

The `_add_item` helper in `tests/test_items_summary.py` builds `Item(...)` with fixed kwargs. Add a `needs_review` parameter with a default so existing calls keep working. Change the helper signature and body:

```python
def _add_item(
    db, *, line, confirmed, excluded, rcv_total, acv_total, rcv_unit, needs_review=False
):
    db.add(
        Item(
            matter_id=MATTER_ID,
            category_id=1,
            line_number=line,
            description=f"item {line}",
            quantity=1,
            age_years=0.0,
            condition="average",
            retail_unit_cents=rcv_unit,
            rcv_total_cents=rcv_total,
            acv_total_cents=acv_total,
            confirmed=confirmed,
            excluded=excluded,
            needs_review=needs_review,
        )
    )
```

Then append two tests:

```python
def test_needs_review_count(db_session):
    _add_item(
        db_session, line=1, confirmed=True, excluded=False,
        rcv_total=0, acv_total=0, rcv_unit=0, needs_review=True,
    )
    _add_item(
        db_session, line=2, confirmed=True, excluded=False,
        rcv_total=0, acv_total=0, rcv_unit=0, needs_review=False,
    )
    db_session.commit()
    totals = compute_items_totals(MATTER_ID, db_session)
    assert totals["needs_review_count"] == 1


def test_items_summary_renders_needs_review_count(client, db_session):
    _add_item(
        db_session, line=1, confirmed=True, excluded=False,
        rcv_total=10000, acv_total=8000, rcv_unit=10000, needs_review=True,
    )
    db_session.commit()
    resp = client.get(f"/api/matters/{MATTER_ID}/items-summary")
    assert resp.status_code == 200
    assert "Needs review" in resp.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_items_summary.py::test_needs_review_count tests/test_items_summary.py::test_items_summary_renders_needs_review_count -v`
Expected: FAIL — `KeyError: 'needs_review_count'` and missing "Needs review" text.

- [ ] **Step 3: Add the count to `compute_items_totals`**

The current query selects specific columns and lacks `needs_review`. Add `Item.needs_review` to the `db.query(...)` column list (after `Item.retail_unit_cents,` at line 235), then add the key to the returned dict (after `missing_price_count`, line 247):

```python
        "needs_review_count": sum(1 for r in rows if r.needs_review),
```

- [ ] **Step 4: Render the count in the summary**

In `src/cvp/templates/_items_summary.html`, inside the `flex` row (after the Confirmed span, line 7), add a conditional span so it only shows when there's something to review:

```jinja
    {% if needs_review_count and needs_review_count > 0 %}
    <span>Needs review: <strong class="text-amber-600">{{ needs_review_count }}</strong></span>
    {% endif %}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_items_summary.py -v`
Expected: all PASS (including the pre-existing summary tests, unchanged by the new optional key).

- [ ] **Step 6: Format and commit**

```bash
uv run ruff format . && uv run ruff format --check .
git add src/cvp/routers/items.py src/cvp/templates/_items_summary.html tests/test_items_summary.py
git commit -m "feat(items): show needs_review count in summary"
```

---

### Task 4: Toggle endpoint + amber pill in the row

**Files:**
- Modify: `src/cvp/routers/items.py` (add `toggle_needs_review` endpoint after `toggle_exclude`, ~line 689)
- Modify: `src/cvp/templates/_item_row.html:69-77` (add pill in the status cell)
- Test: `tests/test_item_needs_review_toggle.py`

**Interfaces:**
- Consumes: `Item.needs_review` from Task 1; `_item_row_html`, `require_matter_role`, `write_audit_log`, `get_client_ip`, `SessionLocal`, `_get_context` (already imported/defined in `items.py`).
- Produces: `POST /api/items/{item_id}/toggle-needs-review` → 200 with the re-rendered `<tr id="item-row-{item_id}">` HTML; flips `item.needs_review`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_item_needs_review_toggle.py` (mirrors the client fixture in `test_items_summary.py`):

```python
"""POST /api/items/{id}/toggle-needs-review flips the flag and re-renders the row."""

import inspect

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cvp.models_vision  # noqa: F401
from cvp.db import get_db
from cvp.dependencies import CurrentUser
from cvp.main import app
from cvp.models import Base, Category, Item, Matter
from cvp.models_auth import User
from cvp.services import access_cache

MATTER_ID = "m-nrt"
USER_ID = "u-nrt"


@pytest.fixture(autouse=True)
def _clear_access_cache():
    access_cache._cache.clear()
    yield
    access_cache._cache.clear()


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    s.add(Matter(id=MATTER_ID, policyholder_name="P", loss_type="total_loss"))
    s.add(Category(id=1, name="C", useful_life_years=5, acv_floor_pct=0.2))
    s.add(User(id=USER_ID, email="u@t.com", display_name="U", system_role="internal_user"))
    s.commit()
    yield s
    s.close()


@pytest.fixture
def client(db_session, monkeypatch):
    import cvp.routers.items as items_router

    async def mock_manager():
        return CurrentUser(
            id=USER_ID,
            email="u@t.com",
            system_role="internal_user",
            group_id=None,
            group_kind="internal",
        )

    def override_get_db():
        yield db_session

    dep = inspect.signature(items_router.toggle_needs_review).parameters["user"].default.dependency
    app.dependency_overrides[dep] = mock_manager
    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr("cvp.routers.items.SessionLocal", lambda: db_session)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _make_item(db, needs_review=False):
    it = Item(
        matter_id=MATTER_ID,
        category_id=1,
        description="thing",
        confirmed=True,
        needs_review=needs_review,
    )
    db.add(it)
    db.commit()
    db.refresh(it)
    return it


def test_toggle_needs_review_on(client, db_session):
    it = _make_item(db_session, needs_review=False)
    resp = client.post(f"/api/items/{it.id}/toggle-needs-review")
    assert resp.status_code == 200
    assert f'id="item-row-{it.id}"' in resp.text
    db_session.refresh(it)
    assert it.needs_review is True
    assert it.confirmed is True  # unchanged


def test_toggle_needs_review_off(client, db_session):
    it = _make_item(db_session, needs_review=True)
    resp = client.post(f"/api/items/{it.id}/toggle-needs-review")
    assert resp.status_code == 200
    db_session.refresh(it)
    assert it.needs_review is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_item_needs_review_toggle.py -v`
Expected: FAIL — `AttributeError: module 'cvp.routers.items' has no attribute 'toggle_needs_review'`.

- [ ] **Step 3: Add the endpoint**

In `src/cvp/routers/items.py`, immediately after the `toggle_exclude` function (which ends ~line 691), add — cloned from `toggle_exclude`:

```python
@router.post("/api/items/{item_id}/toggle-needs-review", response_class=HTMLResponse)
def toggle_needs_review(
    request: Request,
    item_id: str,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_matter_role("manager")),
) -> HTMLResponse:
    db = SessionLocal()
    try:
        item = db.query(Item).options(selectinload(Item.crops)).filter(Item.id == item_id).first()
        if item is None:
            raise HTTPException(status_code=404)
        item.needs_review = not item.needs_review
        db.commit()
        db.refresh(item)
        matter_id = item.matter_id
        categories, rooms, item_groups = _get_context(matter_id, db)
        html = _item_row_html(item, categories, rooms, item_groups)
    finally:
        db.close()
    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="item.update",
        resource_type="item",
        resource_id=item_id,
        matter_id=matter_id,
        ip_address=get_client_ip(request),
    )
    return HTMLResponse(html)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_item_needs_review_toggle.py -v`
Expected: both PASS.

- [ ] **Step 5: Add the amber pill to the row**

In `src/cvp/templates/_item_row.html`, inside the confirm-toggle `<td>` (the one at lines 69-77), add a second button after the existing confirm button (before the closing `</td>` at line 77). Wrap both in a flex container for spacing:

```jinja
    <div class="flex items-center gap-1 justify-center">
      <button hx-post="/api/items/{{ item.id }}/toggle-confirm"
              hx-target="#item-row-{{ item.id }}"
              hx-swap="outerHTML"
              title="{{ 'Confirmed — click to un-confirm' if item.confirmed else 'Draft — click to confirm' }}"
              class="rounded px-1.5 py-0.5 text-xs font-medium {% if item.confirmed %}bg-green-100 text-green-700 hover:bg-green-200{% else %}bg-gray-100 text-gray-500 hover:bg-gray-200{% endif %}">
        {{ "✓" if item.confirmed else "draft" }}
      </button>
      <button hx-post="/api/items/{{ item.id }}/toggle-needs-review"
              hx-target="#item-row-{{ item.id }}"
              hx-swap="outerHTML"
              title="{{ 'Flagged for review — click to clear' if item.needs_review else 'Click to flag for review' }}"
              class="rounded px-1.5 py-0.5 text-xs font-medium {% if item.needs_review %}bg-amber-100 text-amber-700 hover:bg-amber-200{% else %}bg-gray-100 text-gray-500 hover:bg-gray-200{% endif %}">
        {{ "⚑ review" if item.needs_review else "flag" }}
      </button>
    </div>
```

Replace the existing single-button block (lines 70-76) with the flex container above. Keep the surrounding `<td class="whitespace-nowrap px-3 py-2 text-center">...</td>`.

- [ ] **Step 6: Add a row-render assertion**

Append to `tests/test_item_needs_review_toggle.py`:

```python
def test_row_shows_amber_review_pill_when_flagged(client, db_session):
    it = _make_item(db_session, needs_review=True)
    resp = client.post(f"/api/items/{it.id}/toggle-needs-review")
    # After toggling a flagged item it becomes unflagged -> shows "flag"
    assert "flag" in resp.text
    # Flip back on and confirm the amber label renders
    resp2 = client.post(f"/api/items/{it.id}/toggle-needs-review")
    assert "⚑ review" in resp2.text
    assert "bg-amber-100" in resp2.text
```

- [ ] **Step 7: Prove exports are unaffected by the flag**

Append to the existing `tests/test_csv_export.py` (it already imports `Item` and defines the `matter_with_items` fixture that seeds a confirmed line-1 "65-inch Samsung TV" and monkeypatches `SessionLocal`):

```python
def test_needs_review_item_still_exported(matter_with_items, db_session):
    """A confirmed item flagged needs_review still appears in the CSV."""
    item = db_session.query(Item).filter(Item.line_number == 1).first()
    item.needs_review = True
    db_session.commit()
    out_path = generate_csv(item.matter_id)
    text = out_path.read_text(encoding="utf-8")
    assert "65-inch Samsung TV" in text
```

- [ ] **Step 8: Run the toggle + export tests, format, commit**

```bash
uv run pytest tests/test_item_needs_review_toggle.py tests/test_csv_export.py -v
uv run ruff format . && uv run ruff format --check .
git add src/cvp/routers/items.py src/cvp/templates/_item_row.html tests/test_item_needs_review_toggle.py tests/test_csv_export.py
git commit -m "feat(items): toggle-needs-review endpoint + amber row pill"
```

Expected: all PASS — the flagged item remains in the export.

---

### Task 5: `needs_review` checkbox in the edit form

**Files:**
- Modify: `src/cvp/templates/_item_row_edit.html:108-115` (add checkbox next to Confirmed)
- Modify: `src/cvp/routers/items.py` (`update_item` signature ~line 563 + body ~line 576)
- Test: `tests/test_item_needs_review_edit.py`

**Interfaces:**
- Consumes: `Item.needs_review` (Task 1); `update_item` endpoint form-handling pattern.
- Produces: `update_item` accepts `needs_review: bool = Form(False)` and persists `item.needs_review`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_item_needs_review_edit.py`. Reuse the client fixture pattern but target `update_item`'s dependency. It POSTs the full edit form (the handler requires the core fields):

```python
"""Editing an item persists the needs_review checkbox."""

import inspect

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cvp.models_vision  # noqa: F401
from cvp.db import get_db
from cvp.dependencies import CurrentUser
from cvp.main import app
from cvp.models import Base, Category, Item, Matter
from cvp.models_auth import User
from cvp.services import access_cache

MATTER_ID = "m-nre"
USER_ID = "u-nre"


@pytest.fixture(autouse=True)
def _clear_access_cache():
    access_cache._cache.clear()
    yield
    access_cache._cache.clear()


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    s.add(Matter(id=MATTER_ID, policyholder_name="P", loss_type="total_loss"))
    s.add(Category(id=1, name="C", useful_life_years=5, acv_floor_pct=0.2))
    s.add(User(id=USER_ID, email="u@t.com", display_name="U", system_role="internal_user"))
    s.commit()
    yield s
    s.close()


@pytest.fixture
def client(db_session, monkeypatch):
    import cvp.routers.items as items_router

    async def mock_manager():
        return CurrentUser(
            id=USER_ID, email="u@t.com", system_role="internal_user",
            group_id=None, group_kind="internal",
        )

    def override_get_db():
        yield db_session

    dep = inspect.signature(items_router.update_item).parameters["user"].default.dependency
    app.dependency_overrides[dep] = mock_manager
    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr("cvp.routers.items.SessionLocal", lambda: db_session)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _make_item(db):
    it = Item(matter_id=MATTER_ID, category_id=1, description="thing", confirmed=True)
    db.add(it)
    db.commit()
    db.refresh(it)
    return it


def _form(**overrides):
    data = {
        "description": "thing",
        "category_id": "1",
        "room_id": "",
        "quantity": "1",
        "age_years": "0",
        "condition": "average",
        "retail_unit_dollars": "0",
        "shipping_dollars": "0",
        "brand": "",
        "model_num": "",
        "notes": "",
        "source_retailer": "",
        "source_url": "",
        "match_type": "exact",
        "acv_override_dollars": "",
        "acv_override_reason": "",
        "confirmed": "true",
        "item_group_id": "",
        "new_item_group_name": "",
    }
    data.update(overrides)
    return data


def test_edit_sets_needs_review(client, db_session):
    it = _make_item(db_session)
    resp = client.post(f"/api/items/{it.id}", data=_form(needs_review="true"))
    assert resp.status_code == 200
    db_session.refresh(it)
    assert it.needs_review is True


def test_edit_clears_needs_review_when_unchecked(client, db_session):
    it = _make_item(db_session)
    it.needs_review = True
    db_session.commit()
    # An unchecked checkbox submits no field at all.
    resp = client.post(f"/api/items/{it.id}", data=_form())
    assert resp.status_code == 200
    db_session.refresh(it)
    assert it.needs_review is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_item_needs_review_edit.py -v`
Expected: FAIL — `test_edit_sets_needs_review` asserts `True` but the flag never changes (handler ignores the field).

- [ ] **Step 3: Add the form param + assignment**

In `src/cvp/routers/items.py`, add to the `update_item` signature after `confirmed: bool = Form(False),` (line 563):

```python
    needs_review: bool = Form(False),
```

And in the body, after `item.confirmed = confirmed` (line 576):

```python
        item.needs_review = needs_review
```

- [ ] **Step 4: Add the checkbox to the edit template**

In `src/cvp/templates/_item_row_edit.html`, after the "Confirmed" checkbox block (the `<div class="col-span-1 ...">` ending line 115), add a matching block:

```jinja
        <div class="col-span-1 flex flex-col justify-end pb-0.5">
          <label class="flex items-center gap-1.5 cursor-pointer select-none">
            <input type="checkbox" name="needs_review" value="true"
                   {% if item.needs_review %}checked{% endif %}
                   class="h-4 w-4 rounded border-gray-300 text-amber-600 focus:ring-amber-500">
            <span class="text-xs font-medium text-gray-600">Needs review</span>
          </label>
        </div>
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_item_needs_review_edit.py -v`
Expected: both PASS.

- [ ] **Step 6: Run the full items test set, format, commit**

```bash
uv run pytest tests/ -k "item" -v
uv run ruff format . && uv run ruff format --check .
git add src/cvp/routers/items.py src/cvp/templates/_item_row_edit.html tests/test_item_needs_review_edit.py
git commit -m "feat(items): needs_review checkbox in item edit form"
```

Expected: all item tests PASS.

---

### Task 6: Full-suite verification

- [ ] **Step 1: Run the whole test suite**

Run: `uv run pytest`
Expected: PASS (one pre-existing vision test may fail per the known DYLD/worktree note — confirm it is that same pre-existing failure and nothing new).

- [ ] **Step 2: Lint**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: no errors, zero files to reformat.

- [ ] **Step 3: Manual smoke (optional but recommended)**

Follow the browser-verify recipe (fresh DB + `AUTO_LOGIN` + system_admin), open a matter's Items tab, and confirm: the amber `flag`/`⚑ review` pill toggles, the "Needs review" filter option pulls only flagged rows, a flagged item still shows in the PDF preview, and the summary bar shows "Needs review: N".
