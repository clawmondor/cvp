# Items Sort & Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let specialists sort the matter Items table by any column and filter it by room, category, status, and free text — server-side, across the whole matter, integrated with the existing infinite scroll.

**Architecture:** A pure-ish query builder in `routers/items.py` applies filters + sort to a SQLAlchemy `Query`. The items list switches from `line_number` cursor pagination to `OFFSET/LIMIT` (arbitrary sort columns aren't unique). A new `items-region` endpoint renders a swappable region (filter bar + sortable header + first page); the existing `items-rows` endpoint returns rows-only pages for scroll. HTMX swaps the region on any control change and threads the active sort/filter state through the querystring; `app.js` reuses that state for the new-scan "View them" refresh.

**Tech Stack:** FastAPI, SQLAlchemy 2.x, Jinja2, HTMX, vanilla `app.js`, pytest.

## Global Constraints

- Python 3.11+; modern type syntax (`list[str]`, `X | None`).
- Currency is always integer cents; never floats. Format to dollars only at display/export.
- Server-rendered HTML + HTMX only. No React/Next/Redis/Celery.
- **No inline JS event handlers** (`onclick=` etc.) — CSP blocks them. Wire via `data-*` + delegated listeners in `src/cvp/static/app.js`.
- Do NOT change Xactimate CSV column names (not touched here, but never).
- Run `uv run ruff format .` then `uv run ruff format --check .` before every commit; line length 100.
- WeasyPrint native libs: if imports fail in a worktree venv, prefix commands with `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib`.
- One known pre-existing failing vision test on `cvp-legacy` is unrelated — ignore it.

---

### Task 1: Query builder, filters, and querystring helpers

Pure functions + query builder with unit tests. No endpoint or template changes yet.

**Files:**
- Modify: `src/cvp/routers/items.py` (add helpers near the top, after imports/constants)
- Test: `tests/test_items_filter_sort.py` (create)

**Interfaces:**
- Produces:
  - `ItemFilters` dataclass: `room_id: str = ""`, `category_id: str = ""`, `status: str = "all"`, `q: str = ""`, `sort: str = "line"`, `dir: str = "asc"`
  - `SORTABLE_KEYS: list[str]`
  - `_parse_item_filters(request: Request) -> ItemFilters`
  - `_build_items_query(db, matter_id: str, f: ItemFilters) -> Query` (filters + sort applied; `id` tiebreaker)
  - `_count_items(db, matter_id: str, f: ItemFilters) -> int` (filtered count)
  - `items_query_string(f: ItemFilters, *, sort: str | None = None, direction: str | None = None) -> str`
  - `_sort_state(f: ItemFilters, col: str) -> tuple[str, str]` → `(querystring, indicator)` where indicator ∈ `{"", "▲", "▼"}`

- [ ] **Step 1: Write the failing test file**

Create `tests/test_items_filter_sort.py`:

```python
"""Unit tests for the items sort/filter query builder + querystring helpers."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cvp.models_vision  # noqa: F401
from cvp.models import Base, Category, Item, Matter, Room
from cvp.routers.items import (
    ItemFilters,
    _build_items_query,
    _count_items,
    _sort_state,
    items_query_string,
)

MATTER_ID = "m-fs"


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
    s.add(Category(id=1, name="Appliances", useful_life_years=10, acv_floor_pct=0.2))
    s.add(Category(id=2, name="Bedding", useful_life_years=5, acv_floor_pct=0.2))
    s.add(Room(id="r-kit", matter_id=MATTER_ID, name="Kitchen", sort_order=0))
    s.add(Room(id="r-bed", matter_id=MATTER_ID, name="Bedroom", sort_order=1))
    s.commit()
    yield s
    s.close()


def _add(db, **kw):
    defaults = dict(
        matter_id=MATTER_ID,
        category_id=1,
        quantity=1,
        age_years=0.0,
        condition="average",
        retail_unit_cents=0,
        rcv_total_cents=0,
        acv_total_cents=0,
        confirmed=True,
        excluded=False,
    )
    defaults.update(kw)
    it = Item(**defaults)
    db.add(it)
    db.commit()
    return it


def _descs(rows):
    return [r.description for r in rows]


def test_default_sort_is_line_number_asc(db):
    _add(db, line_number=2, description="b")
    _add(db, line_number=1, description="a")
    rows = _build_items_query(db, MATTER_ID, ItemFilters()).all()
    assert _descs(rows) == ["a", "b"]


def test_sort_rcv_total_desc(db):
    _add(db, line_number=1, description="cheap", rcv_total_cents=100)
    _add(db, line_number=2, description="pricey", rcv_total_cents=9999)
    f = ItemFilters(sort="rcv_total", dir="desc")
    assert _descs(_build_items_query(db, MATTER_ID, f).all()) == ["pricey", "cheap"]


def test_sort_condition_ranks_excellent_first(db):
    _add(db, line_number=1, description="avg", condition="average")
    _add(db, line_number=2, description="exc", condition="excellent")
    _add(db, line_number=3, description="low", condition="below_average")
    f = ItemFilters(sort="condition", dir="asc")
    assert _descs(_build_items_query(db, MATTER_ID, f).all()) == ["exc", "avg", "low"]


def test_sort_room_by_name(db):
    _add(db, line_number=1, description="k", room_id="r-kit")  # Kitchen
    _add(db, line_number=2, description="b", room_id="r-bed")  # Bedroom
    f = ItemFilters(sort="room", dir="asc")
    # Bedroom < Kitchen alphabetically
    assert _descs(_build_items_query(db, MATTER_ID, f).all()) == ["b", "k"]


def test_sort_status_asc_surfaces_active_unconfirmed_first(db):
    _add(db, line_number=1, description="conf", confirmed=True, excluded=False)
    _add(db, line_number=2, description="todo", confirmed=False, excluded=False)
    _add(db, line_number=3, description="excl", confirmed=True, excluded=True)
    f = ItemFilters(sort="status", dir="asc")
    assert _descs(_build_items_query(db, MATTER_ID, f).all()) == ["todo", "conf", "excl"]


def test_filter_by_room(db):
    _add(db, line_number=1, description="k", room_id="r-kit")
    _add(db, line_number=2, description="b", room_id="r-bed")
    f = ItemFilters(room_id="r-kit")
    assert _descs(_build_items_query(db, MATTER_ID, f).all()) == ["k"]


def test_filter_by_category(db):
    _add(db, line_number=1, description="app", category_id=1)
    _add(db, line_number=2, description="bed", category_id=2)
    f = ItemFilters(category_id="2")
    assert _descs(_build_items_query(db, MATTER_ID, f).all()) == ["bed"]


def test_filter_status_missing_price(db):
    _add(db, line_number=1, description="priced", confirmed=True, retail_unit_cents=500)
    _add(db, line_number=2, description="noprice", confirmed=True, retail_unit_cents=0)
    _add(db, line_number=3, description="draft", confirmed=False, retail_unit_cents=0)
    f = ItemFilters(status="missing_price")
    assert _descs(_build_items_query(db, MATTER_ID, f).all()) == ["noprice"]


def test_filter_text_matches_brand(db):
    _add(db, line_number=1, description="tv", brand="Samsung")
    _add(db, line_number=2, description="couch", brand="Ashley")
    f = ItemFilters(q="samsung")
    assert _descs(_build_items_query(db, MATTER_ID, f).all()) == ["tv"]


def test_count_items_respects_filters(db):
    _add(db, line_number=1, description="a", room_id="r-kit")
    _add(db, line_number=2, description="b", room_id="r-kit")
    _add(db, line_number=3, description="c", room_id="r-bed")
    assert _count_items(db, MATTER_ID, ItemFilters(room_id="r-kit")) == 2
    assert _count_items(db, MATTER_ID, ItemFilters()) == 3


def test_unknown_sort_falls_back_to_line(db):
    _add(db, line_number=2, description="b")
    _add(db, line_number=1, description="a")
    f = ItemFilters(sort="bogus", dir="weird")
    # Bad sort/dir default to line asc (fallback happens in _parse; builder
    # also treats unknown sort keys as line).
    assert _descs(_build_items_query(db, MATTER_ID, f).all()) == ["a", "b"]


def test_query_string_omits_defaults():
    assert items_query_string(ItemFilters()) == ""


def test_query_string_includes_active_filters_and_sort():
    f = ItemFilters(room_id="r-kit", status="unconfirmed", sort="rcv_total", dir="desc")
    qs = items_query_string(f)
    assert "room_id=r-kit" in qs
    assert "status=unconfirmed" in qs
    assert "sort=rcv_total" in qs
    assert "dir=desc" in qs


def test_sort_state_toggles_active_column():
    # Active column asc -> link flips to desc, indicator ▲
    qs, indicator = _sort_state(ItemFilters(sort="qty", dir="asc"), "qty")
    assert "sort=qty" in qs and "dir=desc" in qs
    assert indicator == "▲"
    # Inactive column -> link is asc, no indicator
    qs2, indicator2 = _sort_state(ItemFilters(sort="qty", dir="asc"), "age")
    assert "sort=age" in qs2 and "dir=asc" in qs2
    assert indicator2 == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_items_filter_sort.py -q`
Expected: FAIL — `ImportError` (`ItemFilters` / helpers not defined).

- [ ] **Step 3: Add the helpers to `items.py`**

In `src/cvp/routers/items.py`, add imports at the top (merge with existing import lines):

```python
from dataclasses import dataclass
from urllib.parse import quote_plus, urlencode

from sqlalchemy import case, func, or_
```

(`quote_plus` and `func` are already imported — merge, don't duplicate. Add `Room` to the existing `from cvp.models import ...` line if not present; it already imports `Room`.)

Then, after the `ITEMS_PAGE_SIZE = 50` constant, add:

```python
SORTABLE_KEYS = [
    "line",
    "description",
    "room",
    "category",
    "qty",
    "age",
    "condition",
    "rcv_unit",
    "rcv_total",
    "acv_total",
    "status",
]

_SIMPLE_SORT_COLUMNS = {
    "line": Item.line_number,
    "description": Item.description,
    "qty": Item.quantity,
    "age": Item.age_years,
    "rcv_unit": Item.retail_unit_cents,
    "rcv_total": Item.rcv_total_cents,
    "acv_total": Item.acv_total_cents,
}

_CONDITION_RANK = case(
    {"excellent": 0, "above_average": 1, "average": 2, "below_average": 3},
    value=Item.condition,
    else_=99,
)

_STATUS_VALUES = {"all", "unconfirmed", "confirmed", "excluded", "missing_price"}


@dataclass
class ItemFilters:
    room_id: str = ""
    category_id: str = ""
    status: str = "all"
    q: str = ""
    sort: str = "line"
    dir: str = "asc"


def _parse_item_filters(request: Request) -> ItemFilters:
    p = request.query_params
    sort = p.get("sort", "line")
    if sort not in SORTABLE_KEYS:
        sort = "line"
    direction = p.get("dir", "asc")
    if direction not in ("asc", "desc"):
        direction = "asc"
    status = p.get("status", "all")
    if status not in _STATUS_VALUES:
        status = "all"
    return ItemFilters(
        room_id=p.get("room_id", "").strip(),
        category_id=p.get("category_id", "").strip(),
        status=status,
        q=p.get("q", "").strip(),
        sort=sort,
        dir=direction,
    )


def _apply_item_filters(query, f: ItemFilters):
    if f.room_id:
        query = query.filter(Item.room_id == f.room_id)
    if f.category_id:
        try:
            query = query.filter(Item.category_id == int(f.category_id))
        except ValueError:
            pass
    if f.status == "unconfirmed":
        query = query.filter(Item.confirmed.is_(False))
    elif f.status == "confirmed":
        query = query.filter(Item.confirmed.is_(True))
    elif f.status == "excluded":
        query = query.filter(Item.excluded.is_(True))
    elif f.status == "missing_price":
        query = query.filter(
            Item.confirmed.is_(True),
            Item.excluded.is_(False),
            Item.retail_unit_cents == 0,
        )
    if f.q:
        like = f"%{f.q}%"
        query = query.filter(
            or_(
                Item.description.ilike(like),
                Item.brand.ilike(like),
                Item.model.ilike(like),
            )
        )
    return query


def _apply_item_sort(query, f: ItemFilters):
    descending = f.dir == "desc"

    def d(expr):
        return expr.desc() if descending else expr.asc()

    if f.sort == "room":
        query = query.outerjoin(Room, Item.room_id == Room.id).order_by(
            d(Room.name), Item.id.asc()
        )
    elif f.sort == "category":
        query = query.join(Category, Item.category_id == Category.id).order_by(
            d(Category.name), Item.id.asc()
        )
    elif f.sort == "condition":
        query = query.order_by(d(_CONDITION_RANK), Item.id.asc())
    elif f.sort == "status":
        if descending:
            query = query.order_by(
                Item.excluded.desc(), Item.confirmed.desc(), Item.id.asc()
            )
        else:
            query = query.order_by(
                Item.excluded.asc(), Item.confirmed.asc(), Item.id.asc()
            )
    else:
        col = _SIMPLE_SORT_COLUMNS.get(f.sort, Item.line_number)
        query = query.order_by(d(col), Item.id.asc())
    return query


def _build_items_query(db, matter_id: str, f: ItemFilters):
    query = (
        db.query(Item)
        .options(selectinload(Item.crops))
        .filter(Item.matter_id == matter_id)
    )
    query = _apply_item_filters(query, f)
    query = _apply_item_sort(query, f)
    return query


def _count_items(db, matter_id: str, f: ItemFilters) -> int:
    query = db.query(Item).filter(Item.matter_id == matter_id)
    query = _apply_item_filters(query, f)
    return query.count()


def items_query_string(
    f: ItemFilters, *, sort: str | None = None, direction: str | None = None
) -> str:
    """Build a querystring for filters + sort, omitting defaults.

    ``sort``/``direction`` override the filter's own values (used to build
    per-column header links). The default sort (``line`` asc) is omitted so a
    reset view has an empty querystring.
    """
    params: dict[str, str] = {}
    if f.room_id:
        params["room_id"] = f.room_id
    if f.category_id:
        params["category_id"] = f.category_id
    if f.status and f.status != "all":
        params["status"] = f.status
    if f.q:
        params["q"] = f.q
    s = f.sort if sort is None else sort
    dirn = f.dir if direction is None else direction
    if s != "line" or dirn != "asc":
        params["sort"] = s
        params["dir"] = dirn
    return urlencode(params)


def _sort_state(f: ItemFilters, col: str) -> tuple[str, str]:
    """Return ``(querystring, indicator)`` for a sortable header link.

    Clicking the active column flips direction; any other column starts asc.
    Indicator is ▲ (asc active) / ▼ (desc active) / "" (inactive).
    """
    if f.sort == col:
        next_dir = "desc" if f.dir == "asc" else "asc"
        indicator = "▲" if f.dir == "asc" else "▼"
    else:
        next_dir = "asc"
        indicator = ""
    return items_query_string(f, sort=col, direction=next_dir), indicator
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_items_filter_sort.py -q`
Expected: PASS (13 passed).

- [ ] **Step 5: Format + commit**

```bash
uv run ruff format src/cvp/routers/items.py tests/test_items_filter_sort.py
uv run ruff format --check .
git add src/cvp/routers/items.py tests/test_items_filter_sort.py
git commit -m "feat(items): sort/filter query builder + querystring helpers"
```

---

### Task 2: Switch `items-rows` to offset pagination + filter/sort params

Rewire the existing rows-only endpoint and its sentinel template from `cursor`/`line_number` to `offset` + the Task 1 filters.

**Files:**
- Modify: `src/cvp/routers/items.py` — `get_items_rows` (lines ~146-179)
- Modify: `src/cvp/templates/_items_rows_fragment.html`
- Test: `tests/test_items_pagination.py` (update existing cursor tests to offset; add a sort/filter test)

**Interfaces:**
- Consumes (Task 1): `_parse_item_filters`, `_build_items_query`, `items_query_string`.
- Produces: `GET /api/matters/{matter_id}/items-rows?offset=N&<filters>` returns rows-only + sentinel; the fragment expects template vars `items`, `items_qs` (str), `items_next_offset` (int | None), `matter_id`, `categories`, `rooms`.

- [ ] **Step 1: Update the sentinel fragment**

Replace the entire contents of `src/cvp/templates/_items_rows_fragment.html` with:

```html
{% for item in items %}{% include "_item_row.html" %}{% endfor %}
{% if items_next_offset is not none %}
<tr hx-get="/api/matters/{{ matter_id }}/items-rows?offset={{ items_next_offset }}{% if items_qs %}&{{ items_qs }}{% endif %}"
    hx-trigger="revealed"
    hx-swap="outerHTML">
  <td colspan="13" class="text-center text-xs text-gray-400 py-2">Loading…</td>
</tr>
{% endif %}
```

- [ ] **Step 2: Rewrite `get_items_rows` to offset + params**

Replace the body of `get_items_rows` in `src/cvp/routers/items.py` with:

```python
@router.get("/api/matters/{matter_id}/items-rows", response_class=HTMLResponse)
def get_items_rows(
    request: Request,
    matter_id: str,
    offset: int = 0,
    user: CurrentUser = Depends(require_matter_role("viewer")),
) -> HTMLResponse:
    """Render one offset-paginated page of item `<tr>` rows + sentinel.

    Honors the sort/filter querystring (see `_parse_item_filters`). `offset`
    is the row offset of this page (0 for the first page).
    """
    offset = max(0, offset)
    f = _parse_item_filters(request)
    db = SessionLocal()
    try:
        rows = (
            _build_items_query(db, matter_id, f)
            .offset(offset)
            .limit(ITEMS_PAGE_SIZE + 1)
            .all()
        )
        if len(rows) > ITEMS_PAGE_SIZE:
            rows = rows[:ITEMS_PAGE_SIZE]
            next_offset = offset + ITEMS_PAGE_SIZE
        else:
            next_offset = None
        categories, room_objs, _groups = _get_context(matter_id, db)
    finally:
        db.close()
    return HTMLResponse(
        templates.get_template("_items_rows_fragment.html").render(
            items=rows,
            items_next_offset=next_offset,
            items_qs=items_query_string(f),
            matter_id=matter_id,
            categories=categories,
            rooms=room_objs,
        )
    )
```

- [ ] **Step 3: Update the existing pagination tests (cursor → offset)**

In `tests/test_items_pagination.py`:

Change `test_second_page_returns_remainder_and_no_sentinel` to use `offset`:

```python
def test_second_page_returns_remainder_and_no_sentinel(client, db_session):
    _seed_items(db_session, 60)
    resp = client.get(f"/api/matters/{MATTER_ID}/items-rows?offset=50")
    assert resp.status_code == 200
    body = resp.text
    assert body.count('<tr id="item-row-') == 10
    assert 'hx-trigger="revealed"' not in body
```

Add a sort/filter regression test after it:

```python
def test_rows_respect_sort_and_preserve_params_in_sentinel(client, db_session):
    # 60 items priced ascending by line; sort desc should put the priciest first,
    # and the sentinel must carry sort+dir so page 2 stays consistent.
    for i in range(60):
        db_session.add(
            Item(
                matter_id=MATTER_ID,
                category_id=1,
                line_number=i + 1,
                description=f"item {i + 1}",
                quantity=1,
                condition="average",
                retail_unit_cents=(i + 1) * 100,
                rcv_total_cents=(i + 1) * 100,
                acv_total_cents=(i + 1) * 80,
                confirmed=True,
            )
        )
    db_session.commit()
    resp = client.get(f"/api/matters/{MATTER_ID}/items-rows?sort=rcv_total&dir=desc")
    assert resp.status_code == 200
    body = resp.text
    # First row rendered should be the priciest (item 60).
    first_row_pos = body.index('<tr id="item-row-')
    assert "item 60" in body[first_row_pos : first_row_pos + 400]
    # Sentinel preserves sort + dir and advances offset.
    assert "offset=50" in body
    assert "sort=rcv_total" in body
    assert "dir=desc" in body
```

- [ ] **Step 4: Run the pagination tests**

Run: `uv run pytest tests/test_items_pagination.py -q`
Expected: PASS (all, including the two updated/added tests).

- [ ] **Step 5: Format + commit**

```bash
uv run ruff format src/cvp/routers/items.py tests/test_items_pagination.py
uv run ruff format --check .
git add src/cvp/routers/items.py src/cvp/templates/_items_rows_fragment.html tests/test_items_pagination.py
git commit -m "feat(items): offset-paginate items-rows with sort/filter params"
```

---

### Task 3: `items-region` endpoint, region templates, and tab/initial-render wiring

Add the swappable region (filter bar + sortable header + first page), the region-context helper shared with the initial matter render, and wire it into the tab.

**Files:**
- Modify: `src/cvp/routers/items.py` — add `items_region_context` + `get_items_region` endpoint
- Create: `src/cvp/templates/_items_controls.html`
- Create: `src/cvp/templates/_items_head.html`
- Create: `src/cvp/templates/_items_region.html`
- Modify: `src/cvp/templates/_tab_items.html` (replace the static `<table>` block)
- Modify: `src/cvp/routers/matters.py` — initial render uses `items_region_context`
- Test: `tests/test_items_region.py` (create)

**Interfaces:**
- Consumes (Task 1/2): `ItemFilters`, `_parse_item_filters`, `_build_items_query`, `_count_items`, `items_query_string`, `_sort_state`, `SORTABLE_KEYS`, `ITEMS_PAGE_SIZE`, `_get_context`.
- Produces:
  - `items_region_context(db, matter_id: str, f: ItemFilters, *, offset: int = 0) -> dict` with keys: `matter_id`, `f`, `items`, `items_next_offset`, `items_qs`, `header_sorts` (dict[col → (qs, indicator)]), `filtered_count`, `items_total_count`, `categories`, `rooms`.
  - `GET /api/matters/{matter_id}/items-region` → full region HTML under `id="items-region"`.

- [ ] **Step 1: Write the failing router test**

Create `tests/test_items_region.py`:

```python
"""Tests for GET /api/matters/{matter_id}/items-region (filter bar + region)."""

import inspect

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cvp.models_vision  # noqa: F401
import cvp.routers.items as items_router
from cvp.db import get_db
from cvp.dependencies import CurrentUser
from cvp.main import app
from cvp.models import Base, Category, Item, Matter, Room
from cvp.services import access_cache

VIEWER_ID = "v1"
MATTER_ID = "m-region"


@pytest.fixture(autouse=True)
def clear_caches():
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
    from cvp.models_auth import User

    s.add(User(id=VIEWER_ID, email="v@test.com", display_name="V", system_role="internal_user"))
    s.add(Matter(id=MATTER_ID, policyholder_name="P", loss_type="total_loss"))
    s.add(Category(id=1, name="Appliances", useful_life_years=10, acv_floor_pct=0.2))
    s.add(Room(id="r-kit", matter_id=MATTER_ID, name="Kitchen", sort_order=0))
    s.commit()
    yield s
    s.close()


@pytest.fixture
def client(db_session, monkeypatch):
    async def mock_viewer():
        return CurrentUser(
            id=VIEWER_ID,
            email="v@test.com",
            system_role="internal_user",
            group_id=None,
            group_kind="internal",
        )

    def override_get_db():
        yield db_session

    dep = inspect.signature(items_router.get_items_region).parameters["user"].default.dependency
    app.dependency_overrides[dep] = mock_viewer
    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr("cvp.routers.items.SessionLocal", lambda: db_session)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _seed(db, n):
    for i in range(n):
        db.add(
            Item(
                matter_id=MATTER_ID,
                category_id=1,
                room_id="r-kit" if i % 2 == 0 else None,
                line_number=i + 1,
                description=f"item {i + 1}",
                quantity=1,
                condition="average",
                retail_unit_cents=100,
                rcv_total_cents=100,
                acv_total_cents=80,
                confirmed=True,
            )
        )
    db.commit()


def test_region_renders_controls_and_region_id(client, db_session):
    _seed(db_session, 3)
    resp = client.get(f"/api/matters/{MATTER_ID}/items-region")
    assert resp.status_code == 200
    body = resp.text
    assert 'id="items-region"' in body
    assert 'id="items-controls"' in body
    assert 'id="items-tbody"' in body
    assert 'data-sort="line"' in body


def test_region_shows_filtered_count(client, db_session):
    _seed(db_session, 4)  # 2 in Kitchen, 2 unassigned
    resp = client.get(f"/api/matters/{MATTER_ID}/items-region?room_id=r-kit")
    body = resp.text
    assert body.count('<tr id="item-row-') == 2
    assert "Showing 2 of 4" in body
    # The room select preselects the active room.
    assert 'value="r-kit" selected' in body


def test_region_first_page_capped_and_sentinel_present(client, db_session):
    _seed(db_session, 60)
    resp = client.get(f"/api/matters/{MATTER_ID}/items-region")
    body = resp.text
    assert body.count('<tr id="item-row-') == 50
    assert "offset=50" in body


def test_region_empty_filter_message(client, db_session):
    _seed(db_session, 2)
    resp = client.get(f"/api/matters/{MATTER_ID}/items-region?q=nomatch")
    body = resp.text
    assert "No items match the current filters." in body
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_items_region.py -q`
Expected: FAIL — `get_items_region` attribute/endpoint does not exist.

- [ ] **Step 3: Add `items_region_context` + endpoint to `items.py`**

In `src/cvp/routers/items.py`, add after `get_items_rows`:

```python
def items_region_context(
    db, matter_id: str, f: ItemFilters, *, offset: int = 0
) -> dict:
    """Build the template context for the swappable items region."""
    rows = (
        _build_items_query(db, matter_id, f)
        .offset(offset)
        .limit(ITEMS_PAGE_SIZE + 1)
        .all()
    )
    if len(rows) > ITEMS_PAGE_SIZE:
        rows = rows[:ITEMS_PAGE_SIZE]
        next_offset = offset + ITEMS_PAGE_SIZE
    else:
        next_offset = None
    categories, room_objs, _groups = _get_context(matter_id, db)
    total_count = db.query(func.count(Item.id)).filter(Item.matter_id == matter_id).scalar()
    return {
        "matter_id": matter_id,
        "f": f,
        "items": rows,
        "items_next_offset": next_offset,
        "items_qs": items_query_string(f),
        "header_sorts": {col: _sort_state(f, col) for col in SORTABLE_KEYS},
        "filtered_count": _count_items(db, matter_id, f),
        "items_total_count": total_count,
        "categories": categories,
        "rooms": room_objs,
    }


@router.get("/api/matters/{matter_id}/items-region", response_class=HTMLResponse)
def get_items_region(
    request: Request,
    matter_id: str,
    user: CurrentUser = Depends(require_matter_role("viewer")),
) -> HTMLResponse:
    """Render the full items region (filter bar + sortable header + page 1)."""
    f = _parse_item_filters(request)
    db = SessionLocal()
    try:
        ctx = items_region_context(db, matter_id, f)
    finally:
        db.close()
    return HTMLResponse(templates.get_template("_items_region.html").render(**ctx))
```

- [ ] **Step 4: Create `_items_head.html`**

Create `src/cvp/templates/_items_head.html`:

```html
{% set cols = [
  ("#", "line", "left"),
  ("Description", "description", "left"),
  ("Room", "room", "left"),
  ("Category", "category", "left"),
  ("Qty", "qty", "right"),
  ("Age", "age", "right"),
  ("Cond", "condition", "left"),
  ("RCV/unit", "rcv_unit", "right"),
  ("RCV total", "rcv_total", "right"),
  ("ACV total", "acv_total", "right"),
  ("Status", "status", "center"),
] %}
<tr>
  {# Leading Photo column is not sortable; it sits after the "#" column visually
     but "#" is a sortable header, so render Photo as a plain th between them. #}
  {% set first = cols[0] %}
  {% set qs, indicator = header_sorts[first[1]] %}
  <th class="px-3 py-2 text-left text-xs font-medium text-gray-500">
    <a hx-get="/api/matters/{{ matter_id }}/items-region{% if qs %}?{{ qs }}{% endif %}"
       hx-target="#items-region" hx-swap="outerHTML"
       class="cursor-pointer select-none hover:text-gray-700">{{ first[0] }} {{ indicator }}</a>
  </th>
  <th class="px-3 py-2 text-left text-xs font-medium text-gray-500" style="width:100px;min-width:100px;">Photo</th>
  {% for label, key, align in cols[1:] %}
  {% set qs, indicator = header_sorts[key] %}
  <th class="px-3 py-2 text-{{ align }} text-xs font-medium text-gray-500">
    <a hx-get="/api/matters/{{ matter_id }}/items-region{% if qs %}?{{ qs }}{% endif %}"
       hx-target="#items-region" hx-swap="outerHTML"
       class="cursor-pointer select-none hover:text-gray-700">{{ label }} {{ indicator }}</a>
  </th>
  {% endfor %}
  <th class="px-3 py-2 text-center text-xs font-medium text-gray-500">Actions</th>
</tr>
```

- [ ] **Step 5: Create `_items_controls.html`**

Create `src/cvp/templates/_items_controls.html`:

```html
{% set has_filter = f.room_id or f.category_id or (f.status and f.status != "all") or f.q %}
<form id="items-controls"
      hx-get="/api/matters/{{ matter_id }}/items-region"
      hx-target="#items-region" hx-swap="outerHTML"
      hx-trigger="change, keyup changed delay:300ms from:find input[name='q']"
      class="flex flex-wrap items-end gap-3 rounded-lg border border-gray-200 bg-white px-4 py-3 shadow-sm">
  {# Preserve the active sort across filter changes. #}
  <input type="hidden" name="sort" value="{{ f.sort }}">
  <input type="hidden" name="dir" value="{{ f.dir }}">
  <div>
    <label class="text-xs font-medium text-gray-600">Search</label>
    <input name="q" value="{{ f.q }}" placeholder="description, brand, model…"
           class="mt-0.5 block w-56 rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500">
  </div>
  <div>
    <label class="text-xs font-medium text-gray-600">Room</label>
    <select name="room_id"
            class="mt-0.5 block rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:border-indigo-500 focus:outline-none">
      <option value="">All rooms</option>
      <option value="__unassigned__" {% if f.room_id == "__unassigned__" %}selected{% endif %}>— unassigned —</option>
      {% for room in rooms %}
      <option value="{{ room.id }}" {% if f.room_id == room.id %}selected{% endif %}>{{ room.name }}</option>
      {% endfor %}
    </select>
  </div>
  <div>
    <label class="text-xs font-medium text-gray-600">Category</label>
    <select name="category_id"
            class="mt-0.5 block rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:border-indigo-500 focus:outline-none">
      <option value="">All categories</option>
      {% for cat in categories %}
      <option value="{{ cat.id }}" {% if f.category_id == cat.id|string %}selected{% endif %}>{{ cat.name }}</option>
      {% endfor %}
    </select>
  </div>
  <div>
    <label class="text-xs font-medium text-gray-600">Status</label>
    <select name="status"
            class="mt-0.5 block rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:border-indigo-500 focus:outline-none">
      {% for value, label in [
        ("all", "All"),
        ("unconfirmed", "Unconfirmed"),
        ("confirmed", "Confirmed"),
        ("excluded", "Excluded"),
        ("missing_price", "Missing price"),
      ] %}
      <option value="{{ value }}" {% if f.status == value %}selected{% endif %}>{{ label }}</option>
      {% endfor %}
    </select>
  </div>
  <div class="ml-auto flex items-center gap-3 pb-1 text-xs text-gray-500">
    <span>Showing {{ filtered_count }} of {{ items_total_count }} items</span>
    {% if has_filter %}
    <a hx-get="/api/matters/{{ matter_id }}/items-region"
       hx-target="#items-region" hx-swap="outerHTML"
       class="cursor-pointer font-medium text-indigo-600 hover:text-indigo-500">Clear filters</a>
    {% endif %}
  </div>
</form>
```

Note: `__unassigned__` room value requires a filter branch. Update `_apply_item_filters` in `items.py` — change the `if f.room_id:` block to:

```python
    if f.room_id == "__unassigned__":
        query = query.filter(Item.room_id.is_(None))
    elif f.room_id:
        query = query.filter(Item.room_id == f.room_id)
```

- [ ] **Step 6: Create `_items_region.html`**

Create `src/cvp/templates/_items_region.html`:

```html
<div id="items-region" data-sort="{{ f.sort }}" data-dir="{{ f.dir }}" data-matter-id="{{ matter_id }}"
     class="space-y-4">
  {% include "_items_controls.html" %}
  <div class="overflow-x-auto rounded-lg border border-gray-200 bg-white shadow-sm">
    <table class="min-w-full divide-y divide-gray-200">
      <thead class="bg-gray-50">
        {% include "_items_head.html" %}
      </thead>
      <tbody id="items-tbody" class="divide-y divide-gray-100 bg-white">
        {% if items %}
          {% include "_items_rows_fragment.html" %}
        {% else %}
        <tr id="items-empty-row">
          <td colspan="13" class="px-6 py-10 text-center text-sm text-gray-400">
            {% if items_qs %}No items match the current filters.{% else %}No items yet — add one above.{% endif %}
          </td>
        </tr>
        {% endif %}
      </tbody>
    </table>
  </div>
</div>
```

- [ ] **Step 7: Wire `_tab_items.html` to include the region**

In `src/cvp/templates/_tab_items.html`, replace the entire `<!-- Items table -->` block (the `<div class="overflow-x-auto …">…</div>` containing the `<table>`, lines ~92-116) with:

```html
  <!-- Items table (sortable/filterable region) -->
  {% include "_items_region.html" %}
```

Leave the new-items banner, the `+ Add item` form, and the `{% include "_items_summary.html" %}` line unchanged.

- [ ] **Step 8: Wire the initial matter render in `matters.py`**

In `src/cvp/routers/matters.py`:

Update the import that pulls from `cvp.routers.items` to include the new names, e.g.:

```python
from cvp.routers.items import ItemFilters, compute_items_totals, items_region_context
```

Remove the items `paginate_by_cursor` block (the `items, items_next_cursor = paginate_by_cursor(... Item ...)` call, ~lines 149-156). Keep the evidence `paginate_by_cursor` call.

After `_totals = compute_items_totals(matter_id, db)` and the rooms/categories are available, add:

```python
        items_region = items_region_context(db, matter_id, ItemFilters())
```

In the `TemplateResponse` context dict, remove the `"items": items,` and `"items_next_cursor": items_next_cursor,` entries (these were the items cursor ones — do NOT touch `evidence_next_cursor`) and add:

```python
            "items": items_region["items"],
            "items_next_offset": items_region["items_next_offset"],
            "items_qs": items_region["items_qs"],
            "f": items_region["f"],
            "header_sorts": items_region["header_sorts"],
            "filtered_count": items_region["filtered_count"],
```

`categories`, `rooms`, and `items_total_count` already exist in the context and match the region's values — leave them as-is.

- [ ] **Step 9: Run region tests + the full items/matters suites**

Run: `uv run pytest tests/test_items_region.py tests/test_items_pagination.py tests/test_items_summary.py tests/test_items_template.py -q`
Expected: PASS. If `test_items_template.py` asserted the old inline `<table>`/`_items_tbody` structure, update those assertions to match the region (region id / controls id) rather than reverting the template.

- [ ] **Step 10: Format + commit**

```bash
uv run ruff format src/cvp/routers/items.py src/cvp/routers/matters.py tests/test_items_region.py
uv run ruff format --check .
git add src/cvp/routers/items.py src/cvp/routers/matters.py \
  src/cvp/templates/_items_controls.html src/cvp/templates/_items_head.html \
  src/cvp/templates/_items_region.html src/cvp/templates/_tab_items.html \
  tests/test_items_region.py
git commit -m "feat(items): sortable/filterable items region + endpoint"
```

---

### Task 4: `app.js` — thread active sort/filter through the new-scan refresh

Make the "View them" banner refresh (and any manual region refresh) preserve the active sort/filter instead of resetting to page 1.

**Files:**
- Modify: `src/cvp/static/app.js` — the `data-view-new-items` click handler (~lines 659-683)
- Test: manual verification via the `verify` skill (JS behavior; no unit harness).

**Interfaces:**
- Consumes (Task 3 DOM): `#items-region[data-sort][data-dir][data-matter-id]`, `#items-controls` form, `GET …/items-region`.

- [ ] **Step 1: Add `currentItemsQuery()` helper**

In `src/cvp/static/app.js`, inside the same IIFE (near the items handlers, before the `data-view-new-items` listener), add:

```javascript
  // Serialize the active items filters (from #items-controls) + sort state
  // (from #items-region data-*) into a querystring, omitting defaults.
  function currentItemsQuery() {
    var region = document.getElementById('items-region');
    var form = document.getElementById('items-controls');
    var params = new URLSearchParams();
    if (form) {
      new FormData(form).forEach(function (v, k) {
        if (k === 'sort' || k === 'dir') return;
        if (v === '' || (k === 'status' && v === 'all')) return;
        params.set(k, v);
      });
    }
    if (region) {
      var sort = region.dataset.sort || 'line';
      var dir = region.dataset.dir || 'asc';
      if (sort !== 'line' || dir !== 'asc') {
        params.set('sort', sort);
        params.set('dir', dir);
      }
    }
    var s = params.toString();
    return s ? '?' + s : '';
  }
```

- [ ] **Step 2: Rewrite the "View them" handler to refresh the region with current state**

Replace the body of the `data-view-new-items` click listener so the refresh targets the region with the active query:

```javascript
  // "View them": refresh the region honoring the active sort/filter, refresh
  // totals, and scroll the region into view.
  document.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-view-new-items]');
    if (!btn || !window.htmx) return;
    var banner = document.getElementById('items-new-banner');
    var matterId = banner ? banner.dataset.matterId : null;
    if (!matterId) return;

    htmx.ajax('GET', '/api/matters/' + matterId + '/items-region' + currentItemsQuery(),
      { target: '#items-region', swap: 'outerHTML' });
    htmx.ajax('GET', '/api/matters/' + matterId + '/items-summary',
      { target: '#items-summary', swap: 'outerHTML' });

    newItemsCount = 0;
    if (banner) banner.classList.add('hidden');

    var onSettle = function (ev) {
      if (ev.detail && ev.detail.target && ev.detail.target.id === 'items-region') {
        document.removeEventListener('htmx:afterSettle', onSettle);
        var region = document.getElementById('items-region');
        if (region) region.scrollIntoView({ block: 'end', behavior: 'smooth' });
      }
    };
    document.addEventListener('htmx:afterSettle', onSettle);
  });
```

- [ ] **Step 3: Verify end-to-end**

Use the `verify` / `run` skill to drive the real app:
1. Start the app: `uv run dev` (add `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib` if WeasyPrint import fails).
2. Open a matter with >50 items. Confirm: clicking column headers re-sorts the whole list (arrow indicator flips); scrolling loads more rows in the same sort order.
3. Set a Room + Status filter; confirm "Showing X of Y" updates and the whole-matter totals summary does NOT change.
4. Confirm "Clear filters" resets to default order and shows all rows.
5. Confirm typing in Search filters after ~300ms.

Expected: all behaviors correct; browser console free of CSP violations (no inline handlers).

- [ ] **Step 4: Commit**

```bash
uv run ruff format --check .
git add src/cvp/static/app.js
git commit -m "feat(items): preserve active sort/filter on new-scan refresh"
```

---

## Self-Review

**Spec coverage:**
- Server-side sort/filter → Task 1 (`_build_items_query`). ✓
- Offset pagination replacing cursor → Task 2. ✓
- Whole-matter totals unchanged + "Showing X of Y" → Task 3 (`items_total_count` from `compute_items_totals` untouched; `filtered_count` in controls). ✓
- All sortable columns incl. Condition CASE + Status order + Room/Category by name → Task 1. ✓
- Filters: room (incl. unassigned), category, status, text → Task 1 + controls (Task 3 Step 5 adds `__unassigned__`). ✓
- Endpoints `items-region` (new) + `items-rows` (offset) → Tasks 2/3. ✓
- Templates `_items_controls`, `_items_head`, `_items_region`, `_tab_items`, `_items_rows_fragment` → Tasks 2/3. ✓
- State threading + header dir toggle → `items_query_string` / `_sort_state` (Task 1), head links (Task 3). ✓
- app.js `currentItemsQuery` + View-them refresh → Task 4. ✓
- Known limitation (add-item append position) → accepted, no task needed. ✓

**Placeholder scan:** none — every code step has full content.

**Type consistency:** `ItemFilters`, `_build_items_query`, `_count_items`, `items_query_string`, `_sort_state`, `items_region_context`, `get_items_region` names/signatures match across Tasks 1-4 and the tests. Template vars (`f`, `header_sorts`, `items_qs`, `items_next_offset`, `filtered_count`, `items_total_count`) are produced by `items_region_context` and consumed by the region/controls/head/fragment templates consistently. The `__unassigned__` sentinel is introduced in Task 3 Step 5 with its matching filter branch.
