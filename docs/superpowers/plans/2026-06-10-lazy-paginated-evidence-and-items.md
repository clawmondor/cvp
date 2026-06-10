# Lazy & Paginated Evidence and Items Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop exhausting the SQLAlchemy connection pool when the matter detail page loads many evidence thumbnails, and stop rendering unbounded evidence/items lists on every matter render.

**Architecture:** Three independent units, all targeting the QueuePool exhaustion observed after PR #17. (1) An in-memory `(user_id, matter_id, minimum_role) -> bool` cache wraps the per-thumbnail auth check so a burst of N thumbnail requests becomes 1 DB check + N-1 cache hits. (2) Two trivial settings — `loading="lazy"` on thumbnail `<img>` tags and a modest SQLAlchemy pool bump (20 + 30). (3) Cursor-based HTMX infinite scroll on the evidence grid (page 24) and items table (page 50), backed by a shared pagination helper. The auth cache is the load-bearing fix; pagination is the durable fix for grid render cost; lazy + pool are cheap insurance.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.x, Jinja2, HTMX, vanilla JS, pytest, ruff. Project conventions per `CLAUDE.md` (uv, `db.query()` style, no inline JS handlers, ruff format check before commit).

**Spec:** `docs/superpowers/specs/2026-06-10-lazy-paginated-evidence-and-items-design.md`.

**Branch:** work proceeds on `spec/lazy-paginated-evidence-items` (created when the spec was committed). Never commit to `main`.

---

## File Map

**New files:**
- `src/cvp/services/access_cache.py` — `(user_id, matter_id, minimum_role) -> bool` TTL cache + invalidation helpers.
- `src/cvp/services/pagination.py` — `paginate_by_cursor` helper.
- `src/cvp/templates/_evidence_grid_fragment.html` — rows + sentinel partial used by both the matter-detail first-render and the paginated endpoint.
- `src/cvp/templates/_items_rows_fragment.html` — same shape for items (`<tr>` rows + sentinel `<tr>`).
- `tests/test_access_cache.py`
- `tests/test_pagination.py`
- `tests/test_evidence_grid_pagination.py`
- `tests/test_items_pagination.py`

**Modified files:**
- `src/cvp/dependencies.py` — `require_matter_role`'s `_check_matter_access` call is replaced with `check_matter_access_cached`.
- `src/cvp/db.py` — `pool_size=20, max_overflow=30` on the Postgres branch.
- `src/cvp/templates/_evidence_tile.html` — `loading="lazy"` + `decoding="async"` on the `<img>` tag.
- `src/cvp/templates/_evidence_grid.html` — loops `_evidence_grid_fragment.html` inside `#evidence-grid` container.
- `src/cvp/templates/_items_tbody.html` — loops `_items_rows_fragment.html` inside the existing structure; "No items yet" empty-state row stays for the truly-empty case but uses `items_total_count` rather than `items | length`.
- `src/cvp/templates/_tab_items.html` — totals at the bottom use server-passed `items_total_count` / `items_confirmed_count` / `items_rcv_total_cents` / `items_acv_total_cents` instead of iterating over `items`.
- `src/cvp/routers/evidence.py` — `GET /api/matters/{matter_id}/evidence-grid` becomes cursor-paginated (page size 24).
- `src/cvp/routers/items.py` — new `GET /api/matters/{matter_id}/items-rows` endpoint (page size 50); `_items_tbody_html` helper removed; `create_item` returns the new row HTML for OOB append instead of rebuilding the tbody.
- `src/cvp/routers/matters.py` — drops `selectinload(Matter.items)`, `selectinload(Matter.evidence_files)`; loads only first page of each + computes totals via aggregate query; passes new context keys.

---

## Task 1: Access decision cache (load-bearing fix)

**Files:**
- Create: `src/cvp/services/access_cache.py`
- Modify: `src/cvp/dependencies.py:218-276` (`require_matter_role` body)
- Test: `tests/test_access_cache.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_access_cache.py`:

```python
"""Tests for the matter-access TTL cache."""

import pytest

from cvp.dependencies import CurrentUser
from cvp.services import access_cache


@pytest.fixture(autouse=True)
def clear_cache():
    access_cache._cache.clear()
    yield
    access_cache._cache.clear()


def _user(user_id: str = "u1", role: str = "internal_user") -> CurrentUser:
    return CurrentUser(
        id=user_id,
        email=f"{user_id}@test.com",
        system_role=role,
        group_id=None,
        group_kind="internal",
    )


def test_first_call_misses_then_caches(monkeypatch):
    calls = []

    def fake_check(db, user, matter_id, minimum_role):
        calls.append((user.id, matter_id, minimum_role))
        return True

    monkeypatch.setattr(access_cache, "_check_matter_access", fake_check)
    assert access_cache.check_matter_access_cached(None, _user(), "m1", "viewer") is True
    assert access_cache.check_matter_access_cached(None, _user(), "m1", "viewer") is True
    # Second call hit the cache; underlying check ran only once.
    assert len(calls) == 1


def test_different_keys_do_not_share_entries(monkeypatch):
    monkeypatch.setattr(access_cache, "_check_matter_access", lambda *a, **k: True)
    access_cache.check_matter_access_cached(None, _user("a"), "m1", "viewer")
    access_cache.check_matter_access_cached(None, _user("b"), "m1", "viewer")
    access_cache.check_matter_access_cached(None, _user("a"), "m2", "viewer")
    access_cache.check_matter_access_cached(None, _user("a"), "m1", "manager")
    assert len(access_cache._cache) == 4


def test_system_admin_bypasses_cache(monkeypatch):
    calls = []

    def fake_check(db, user, matter_id, minimum_role):
        calls.append(user.id)
        return True

    monkeypatch.setattr(access_cache, "_check_matter_access", fake_check)
    admin = _user("admin", role="system_admin")
    access_cache.check_matter_access_cached(None, admin, "m1", "viewer")
    access_cache.check_matter_access_cached(None, admin, "m1", "viewer")
    # Admin short-circuit returns True without hitting cache or underlying check.
    assert calls == []
    assert access_cache._cache == {}


def test_ttl_expiry_triggers_recheck(monkeypatch):
    calls = []
    monkeypatch.setattr(
        access_cache,
        "_check_matter_access",
        lambda *a, **k: calls.append("x") or True,
    )
    access_cache.check_matter_access_cached(None, _user(), "m1", "viewer")
    assert len(calls) == 1

    # Fast-forward past TTL
    entry_time = access_cache._cache[("u1", "m1", "viewer")][0]
    monkeypatch.setattr(access_cache, "_now", lambda: entry_time + access_cache._TTL_SECONDS + 1)

    access_cache.check_matter_access_cached(None, _user(), "m1", "viewer")
    assert len(calls) == 2


def test_invalidate_matter_clears_only_matching_entries(monkeypatch):
    monkeypatch.setattr(access_cache, "_check_matter_access", lambda *a, **k: True)
    access_cache.check_matter_access_cached(None, _user("a"), "m1", "viewer")
    access_cache.check_matter_access_cached(None, _user("b"), "m1", "viewer")
    access_cache.check_matter_access_cached(None, _user("a"), "m2", "viewer")
    access_cache.invalidate_matter("m1")
    keys = set(access_cache._cache.keys())
    assert keys == {("a", "m2", "viewer")}


def test_invalidate_user_clears_only_matching_entries(monkeypatch):
    monkeypatch.setattr(access_cache, "_check_matter_access", lambda *a, **k: True)
    access_cache.check_matter_access_cached(None, _user("a"), "m1", "viewer")
    access_cache.check_matter_access_cached(None, _user("b"), "m1", "viewer")
    access_cache.check_matter_access_cached(None, _user("a"), "m2", "viewer")
    access_cache.invalidate_user("a")
    keys = set(access_cache._cache.keys())
    assert keys == {("b", "m1", "viewer")}


def test_eviction_when_cache_exceeds_max_size(monkeypatch):
    monkeypatch.setattr(access_cache, "_check_matter_access", lambda *a, **k: True)
    # Make eviction window small enough to be observable in a test.
    monkeypatch.setattr(access_cache, "_MAX_ENTRIES", 8)
    monkeypatch.setattr(access_cache, "_EVICT_BATCH", 3)

    base = 1_000_000.0
    for i in range(8):
        monkeypatch.setattr(access_cache, "_now", lambda i=i: base + i)
        access_cache.check_matter_access_cached(None, _user(f"u{i}"), "m", "viewer")
    assert len(access_cache._cache) == 8

    # 9th insert should trigger eviction of the 3 oldest.
    monkeypatch.setattr(access_cache, "_now", lambda: base + 100)
    access_cache.check_matter_access_cached(None, _user("u9"), "m", "viewer")
    assert len(access_cache._cache) == 6
    surviving_users = {k[0] for k in access_cache._cache}
    # Oldest three (u0, u1, u2) evicted; u3..u8 + u9 remain.
    assert "u0" not in surviving_users
    assert "u1" not in surviving_users
    assert "u2" not in surviving_users
    assert "u9" in surviving_users
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_access_cache.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'cvp.services.access_cache'`.

- [ ] **Step 3: Create the access cache module**

Create `src/cvp/services/access_cache.py`:

```python
"""TTL cache for the matter-access decision used by `require_matter_role`.

Browsers fan out 50+ concurrent thumbnail requests on a single matter page
load. Each one runs `_check_matter_access`, which does two DB queries. The
cache makes a burst of N thumbnail requests cost 1 DB check + (N-1) cache
hits, preventing the SQLAlchemy `QueuePool timeout` we saw after PR #17.

Cache key is (user_id, matter_id, minimum_role); value is bool. TTL is 60 s.
System admins short-circuit before the cache so admin grants never end up
cached or shared with non-admins.

Worst-case staleness after a role change is `_TTL_SECONDS`. Wiring of
`invalidate_matter` / `invalidate_user` into MatterAccess and user-role
mutation paths is tracked as a follow-up in the spec's Backlog.
"""

import time
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from cvp.dependencies import _check_matter_access

if TYPE_CHECKING:
    from cvp.dependencies import CurrentUser

_TTL_SECONDS: float = 60.0
_MAX_ENTRIES: int = 1024
_EVICT_BATCH: int = 256

# key -> (loaded_at, allowed)
_cache: dict[tuple[str, str, str], tuple[float, bool]] = {}


def _now() -> float:
    """Wall clock — split out so tests can monkeypatch."""
    return time.time()


def _evict_oldest() -> None:
    """Drop the `_EVICT_BATCH` oldest entries in one sweep."""
    items = sorted(_cache.items(), key=lambda kv: kv[1][0])
    for key, _ in items[:_EVICT_BATCH]:
        _cache.pop(key, None)


def check_matter_access_cached(
    db: Session,
    user: "CurrentUser",
    matter_id: str,
    minimum_role: str,
) -> bool:
    """Cached wrapper around `_check_matter_access`. System admins skip the cache."""
    if user.system_role == "system_admin":
        return True

    key = (user.id, matter_id, minimum_role)
    entry = _cache.get(key)
    if entry is not None:
        loaded_at, allowed = entry
        if (_now() - loaded_at) < _TTL_SECONDS:
            return allowed

    allowed = _check_matter_access(db, user, matter_id, minimum_role)
    _cache[key] = (_now(), allowed)
    if len(_cache) > _MAX_ENTRIES:
        _evict_oldest()
    return allowed


def invalidate_matter(matter_id: str) -> None:
    """Drop every cache entry for `matter_id` (call when access on a matter changes)."""
    for key in list(_cache.keys()):
        if key[1] == matter_id:
            _cache.pop(key, None)


def invalidate_user(user_id: str) -> None:
    """Drop every cache entry for `user_id` (call when the user's role changes)."""
    for key in list(_cache.keys()):
        if key[0] == user_id:
            _cache.pop(key, None)
```

- [ ] **Step 4: Run the cache unit tests**

```bash
uv run pytest tests/test_access_cache.py -v
```

Expected: 7/7 pass.

- [ ] **Step 5: Wire the cache into `require_matter_role`**

In `src/cvp/dependencies.py`, find the call to `_check_matter_access` inside `require_matter_role`'s nested `dependency` function (line 271):

```python
        if not _check_matter_access(db, user, matter_id, minimum_role):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
```

Replace with:

```python
        from cvp.services.access_cache import check_matter_access_cached

        if not check_matter_access_cached(db, user, matter_id, minimum_role):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
```

The import is inside the function body to avoid a circular import (`access_cache.py` imports `_check_matter_access` from `dependencies.py`).

- [ ] **Step 6: Run the full suite**

```bash
uv run ruff format .
uv run ruff format --check .
uv run ruff check .
uv run pytest -x
```

Expected: zero reformat, no lint errors, all tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/cvp/services/access_cache.py src/cvp/dependencies.py tests/test_access_cache.py
git commit -m "feat: cache matter-access decision (60s TTL) to fix thumbnail-burst QueuePool exhaustion"
```

---

## Task 2: Lazy thumbnails + pool bump (cheap insurance)

**Files:**
- Modify: `src/cvp/templates/_evidence_tile.html` (one `<img>` tag)
- Modify: `src/cvp/db.py:55-58` (pool params)

- [ ] **Step 1: Add lazy & async-decode hints to the thumbnail tag**

In `src/cvp/templates/_evidence_tile.html`, find the `<img src="/files/{{ f.stored_path }}" ...>` tag (currently three lines: `src`, `alt`, `class`). Add `loading="lazy"` and `decoding="async"`:

```html
    <img src="/files/{{ f.stored_path }}"
         alt="{{ f.filename }}"
         loading="lazy"
         decoding="async"
         class="h-32 w-full object-cover">
```

- [ ] **Step 2: Bump the SQLAlchemy pool**

In `src/cvp/db.py`, find the Postgres engine block (the `else:` branch around lines 52–60):

```python
    engine = create_engine(
        _db_url,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
        pool_timeout=10,
        pool_recycle=1800,
    )
```

Change `pool_size=10` → `pool_size=20` and `max_overflow=20` → `max_overflow=30`. The other params stay.

- [ ] **Step 3: Verify nothing regressed**

```bash
uv run ruff format .
uv run ruff format --check .
uv run ruff check .
uv run pytest -x
```

Expected: zero reformat, no lint errors, all tests pass.

- [ ] **Step 4: Commit**

```bash
git add src/cvp/templates/_evidence_tile.html src/cvp/db.py
git commit -m "feat: loading=lazy on evidence thumbs + SQLAlchemy pool 20+30"
```

---

## Task 3: Cursor pagination helper

**Files:**
- Create: `src/cvp/services/pagination.py`
- Test: `tests/test_pagination.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pagination.py`:

```python
"""Tests for the cursor-based pagination helper."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from cvp.models import Base, Matter, EvidenceFile
from cvp.services.pagination import paginate_by_cursor


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    s.add(Matter(id="m", policyholder_name="P", loss_type="total_loss"))
    s.commit()
    # 7 evidence rows; we'll paginate by id (stable, ascending insertion order)
    for i in range(7):
        s.add(
            EvidenceFile(
                matter_id="m",
                filename=f"f{i}.jpg",
                stored_path=f"m/f{i}.jpg",
                mime_type="image/jpeg",
                size_bytes=100,
                kind="image",
            )
        )
    s.commit()
    yield s
    s.close()


def test_first_page_returns_limit_rows_and_next_cursor(db):
    rows, next_cursor = paginate_by_cursor(
        db.query(EvidenceFile).filter_by(matter_id="m"),
        cursor_col=EvidenceFile.id,
        cursor_value=None,
        limit=3,
        order="asc",
    )
    assert len(rows) == 3
    assert next_cursor == rows[-1].id


def test_middle_page_skips_consumed_rows(db):
    rows, _ = paginate_by_cursor(
        db.query(EvidenceFile).filter_by(matter_id="m"),
        cursor_col=EvidenceFile.id,
        cursor_value=None,
        limit=3,
        order="asc",
    )
    last_id = rows[-1].id

    page2, next_cursor2 = paginate_by_cursor(
        db.query(EvidenceFile).filter_by(matter_id="m"),
        cursor_col=EvidenceFile.id,
        cursor_value=last_id,
        limit=3,
        order="asc",
    )
    assert len(page2) == 3
    assert all(r.id != last_id for r in page2)
    assert next_cursor2 == page2[-1].id


def test_last_page_returns_no_cursor(db):
    # Page 1 of 3, page 2 of 3, page 3 of 1
    cursor = None
    pages = []
    for _ in range(3):
        rows, cursor = paginate_by_cursor(
            db.query(EvidenceFile).filter_by(matter_id="m"),
            cursor_col=EvidenceFile.id,
            cursor_value=cursor,
            limit=3,
            order="asc",
        )
        pages.append((rows, cursor))
    assert [len(p[0]) for p in pages] == [3, 3, 1]
    assert pages[-1][1] is None  # last page → no next cursor


def test_descending_order_works(db):
    rows, _ = paginate_by_cursor(
        db.query(EvidenceFile).filter_by(matter_id="m"),
        cursor_col=EvidenceFile.id,
        cursor_value=None,
        limit=10,
        order="desc",
    )
    ids = [r.id for r in rows]
    assert ids == sorted(ids, reverse=True)
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_pagination.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'cvp.services.pagination'`.

- [ ] **Step 3: Implement the helper**

Create `src/cvp/services/pagination.py`:

```python
"""Cursor-based pagination for HTMX infinite-scroll endpoints.

Cursor pagination is stable across concurrent inserts (no off-by-one when a
new row lands between page fetches) and avoids the O(offset) cost of offset
pagination on Postgres. The cursor is the value of the order column from the
last row of the previous page.
"""

from typing import Any, Literal

from sqlalchemy.orm import Query


def paginate_by_cursor(
    query: Query,
    *,
    cursor_col: Any,
    cursor_value: Any | None,
    limit: int,
    order: Literal["asc", "desc"] = "desc",
) -> tuple[list, Any | None]:
    """Return `(rows, next_cursor)` for one cursor-paginated page.

    `cursor_col` is the model column to order by (must be unique-ish enough
    that ties don't cause skipped rows — id, line_number, created_at).
    `cursor_value`, if present, is the cursor returned from the previous page
    call; `None` means "first page".

    `next_cursor` is the cursor value to pass for the next page, or `None`
    when this was the last page.
    """
    if order == "desc":
        q = query.order_by(cursor_col.desc())
        if cursor_value is not None:
            q = q.filter(cursor_col < cursor_value)
    else:
        q = query.order_by(cursor_col.asc())
        if cursor_value is not None:
            q = q.filter(cursor_col > cursor_value)

    rows = q.limit(limit + 1).all()
    if len(rows) > limit:
        # We fetched one extra to know whether there's another page; drop it.
        page = rows[:limit]
        next_cursor = getattr(page[-1], cursor_col.key)
        return page, next_cursor
    return rows, None
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/test_pagination.py -v
```

Expected: 4/4 pass.

- [ ] **Step 5: Format + lint + full sweep**

```bash
uv run ruff format .
uv run ruff format --check .
uv run ruff check .
uv run pytest -x
```

Expected: clean, all pass.

- [ ] **Step 6: Commit**

```bash
git add src/cvp/services/pagination.py tests/test_pagination.py
git commit -m "feat: paginate_by_cursor helper for HTMX infinite-scroll endpoints"
```

---

## Task 4: Evidence grid pagination

**Files:**
- Create: `src/cvp/templates/_evidence_grid_fragment.html`
- Modify: `src/cvp/templates/_evidence_grid.html`
- Modify: `src/cvp/routers/evidence.py` (`get_evidence_grid` becomes paginated)
- Modify: `src/cvp/routers/matters.py` (matter detail handler — pass first page + cursor)
- Test: `tests/test_evidence_grid_pagination.py`

- [ ] **Step 1: Write the failing endpoint tests**

Create `tests/test_evidence_grid_pagination.py`:

```python
"""Tests for the paginated GET /api/matters/{matter_id}/evidence-grid endpoint."""

import os

import pytest
from fastapi.testclient import TestClient
from PIL import Image as PILImage
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cvp.models_vision  # noqa: F401
from cvp.db import get_db
from cvp.dependencies import CurrentUser
from cvp.main import app
from cvp.models import Base, EvidenceFile, Matter
from cvp.services import access_cache

VIEWER_ID = "v1"
MATTER_ID = "m-grid"


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
    Session = sessionmaker(bind=engine)
    s = Session()
    from cvp.models_auth import User

    s.add(User(id=VIEWER_ID, email="v@test.com", display_name="V", system_role="internal_user"))
    s.add(Matter(id=MATTER_ID, policyholder_name="P", loss_type="total_loss"))
    s.commit()
    yield s
    s.close()


@pytest.fixture
def client(db_session, monkeypatch, tmp_path):
    import inspect
    import cvp.routers.evidence as ev_router

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

    dep = inspect.signature(ev_router.get_evidence_grid).parameters["user"].default.dependency
    app.dependency_overrides[dep] = mock_viewer
    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr("cvp.routers.evidence.SessionLocal", lambda: db_session)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _seed_images(db, count: int, tmp_path) -> list[EvidenceFile]:
    rows = []
    for i in range(count):
        path = tmp_path / f"img_{i:03d}.jpg"
        PILImage.new("RGB", (10, 10), "white").save(path, "JPEG")
        ef = EvidenceFile(
            matter_id=MATTER_ID,
            filename=path.name,
            stored_path=f"{MATTER_ID}/{path.name}",
            mime_type="image/jpeg",
            size_bytes=os.path.getsize(path),
            kind="image",
        )
        db.add(ef)
        db.commit()
        db.refresh(ef)
        rows.append(ef)
    return rows


def test_first_page_returns_24_tiles_and_sentinel(client, db_session, tmp_path):
    _seed_images(db_session, 30, tmp_path)
    resp = client.get(f"/api/matters/{MATTER_ID}/evidence-grid")
    assert resp.status_code == 200
    body = resp.text
    assert body.count("data-file-card") == 24
    assert 'hx-trigger="revealed"' in body
    assert 'cursor=' in body


def test_second_page_returns_remainder_and_no_sentinel(client, db_session, tmp_path):
    rows = _seed_images(db_session, 30, tmp_path)
    # Newest-first ordering by created_at desc; oldest of the first page is rows[6]
    # (rows[29], rows[28], ..., rows[6] = 24 newest). Cursor = rows[6].created_at.
    cursor = rows[6].created_at.isoformat()
    resp = client.get(f"/api/matters/{MATTER_ID}/evidence-grid?cursor={cursor}")
    assert resp.status_code == 200
    body = resp.text
    assert body.count("data-file-card") == 6
    assert 'hx-trigger="revealed"' not in body


def test_empty_matter_returns_no_tiles_no_sentinel(client):
    resp = client.get(f"/api/matters/{MATTER_ID}/evidence-grid")
    assert resp.status_code == 200
    assert "data-file-card" not in resp.text
    assert 'hx-trigger="revealed"' not in resp.text
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_evidence_grid_pagination.py -v
```

Expected: FAIL — current endpoint returns the full grid (no pagination, no sentinel, no `data-file-card` count check).

- [ ] **Step 3: Create the fragment partial**

Create `src/cvp/templates/_evidence_grid_fragment.html`:

```html
{% for f in evidence_files %}
{% include "_evidence_tile.html" %}
{% endfor %}
{% if evidence_next_cursor %}
<div hx-get="/api/matters/{{ matter_id }}/evidence-grid?cursor={{ evidence_next_cursor }}"
     hx-trigger="revealed"
     hx-swap="outerHTML"
     class="col-span-full h-4 text-center text-xs text-gray-400">
  Loading…
</div>
{% endif %}
```

- [ ] **Step 4: Update `_evidence_grid.html` to include the fragment**

Replace the body of `src/cvp/templates/_evidence_grid.html` with:

```html
{% if vision_models is defined and vision_models %}
{% include "_vision_model_picker.html" %}
{% endif %}
<div id="evidence-grid"
     class="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
  {% include "_evidence_grid_fragment.html" %}
</div>
```

- [ ] **Step 5: Replace the endpoint with the paginated version**

In `src/cvp/routers/evidence.py`, find the existing `get_evidence_grid` handler (the GET endpoint added in Spec 1, around line ~125–145) and replace it with:

```python
EVIDENCE_PAGE_SIZE = 24


@router.get("/api/matters/{matter_id}/evidence-grid", response_class=HTMLResponse)
def get_evidence_grid(
    request: Request,
    matter_id: str,
    cursor: str = "",
    user: CurrentUser = Depends(require_matter_role("viewer")),
) -> HTMLResponse:
    """Render one cursor-paginated page of evidence tiles + sentinel.

    `cursor` is the ISO timestamp of the oldest tile from the previous page
    (empty string for the first page). Tiles are ordered by `created_at DESC`.
    """
    from datetime import datetime

    cursor_dt = datetime.fromisoformat(cursor) if cursor else None
    db = SessionLocal()
    try:
        rows, next_cursor = paginate_by_cursor(
            db.query(EvidenceFile).filter(EvidenceFile.matter_id == matter_id),
            cursor_col=EvidenceFile.created_at,
            cursor_value=cursor_dt,
            limit=EVIDENCE_PAGE_SIZE,
            order="desc",
        )
    finally:
        db.close()
    next_cursor_str = next_cursor.isoformat() if next_cursor else None
    return HTMLResponse(
        templates.get_template("_evidence_grid_fragment.html").render(
            evidence_files=rows,
            evidence_next_cursor=next_cursor_str,
            matter_id=matter_id,
        )
    )
```

Add this import alongside the existing imports at the top of the file:

```python
from cvp.services.pagination import paginate_by_cursor
```

- [ ] **Step 6: Update the matter detail handler**

In `src/cvp/routers/matters.py`, edit the `matter_detail` handler (around line 110). Two changes:

1. Drop `selectinload(Matter.evidence_files)` from the eager-load block (around line 123).
2. Replace the `evidence_files = sorted(matter.evidence_files, ...)` line (around line 137) with a paginated query.

Find this block (line ~119–138):

```python
        matter = (
            db.query(Matter)
            .options(
                selectinload(Matter.items).selectinload(Item.crops),
                selectinload(Matter.evidence_files),
                selectinload(Matter.rooms),
            )
            .filter(Matter.id == matter_id)
            .first()
        )
        if matter is None:
            return HTMLResponse("Matter not found", status_code=404)
        items = sorted(matter.items, key=lambda i: i.line_number)
        confirmed = [i for i in items if i.confirmed and not i.excluded]
        total_rcv_cents = sum(i.rcv_total_cents for i in confirmed)
        total_acv_cents = sum(i.acv_total_cents for i in confirmed)
        unconfirmed_count = sum(1 for i in items if not i.confirmed)
        missing_price_count = sum(1 for i in confirmed if i.rcv_unit_cents == 0)
        evidence_files = sorted(matter.evidence_files, key=lambda f: f.created_at, reverse=True)
```

Change to:

```python
        matter = (
            db.query(Matter)
            .options(selectinload(Matter.rooms))
            .filter(Matter.id == matter_id)
            .first()
        )
        if matter is None:
            return HTMLResponse("Matter not found", status_code=404)

        # First page of evidence (newest-first), with cursor for infinite scroll.
        evidence_files, evidence_next_cursor = paginate_by_cursor(
            db.query(EvidenceFile).filter(EvidenceFile.matter_id == matter_id),
            cursor_col=EvidenceFile.created_at,
            cursor_value=None,
            limit=24,
            order="desc",
        )
        evidence_next_cursor = (
            evidence_next_cursor.isoformat() if evidence_next_cursor else None
        )

        # Full-set items totals (aggregate query, not row-by-row).
        items_for_totals = (
            db.query(Item.confirmed, Item.excluded, Item.rcv_total_cents,
                     Item.acv_total_cents, Item.rcv_unit_cents)
            .filter(Item.matter_id == matter_id)
            .all()
        )
        confirmed_rows = [r for r in items_for_totals if r.confirmed and not r.excluded]
        total_rcv_cents = sum(r.rcv_total_cents for r in confirmed_rows)
        total_acv_cents = sum(r.acv_total_cents for r in confirmed_rows)
        unconfirmed_count = sum(1 for r in items_for_totals if not r.confirmed)
        missing_price_count = sum(1 for r in confirmed_rows if r.rcv_unit_cents == 0)
        items_total_count = len(items_for_totals)
        items_confirmed_count = len(confirmed_rows)

        # First page of items rows (line_number ASC), with cursor.
        items, items_next_cursor = paginate_by_cursor(
            db.query(Item).options(selectinload(Item.crops))
                .filter(Item.matter_id == matter_id),
            cursor_col=Item.line_number,
            cursor_value=None,
            limit=50,
            order="asc",
        )
```

Then find the `context` block at the bottom of the handler (around line 225–240 where context is built) and add the new keys:

```python
            "evidence_files": evidence_files,
            "evidence_next_cursor": evidence_next_cursor,
            "items": items,
            "items_next_cursor": items_next_cursor,
            "items_total_count": items_total_count,
            "items_confirmed_count": items_confirmed_count,
            "items_rcv_total_cents": total_rcv_cents,
            "items_acv_total_cents": total_acv_cents,
```

(Keep the existing `total_rcv_cents` / `total_acv_cents` keys if they're already in context — these stay as-is for whatever else uses them. Just *add* the four new `items_*` keys.)

Add these imports near the top of `matters.py` if not present:

```python
from cvp.models import EvidenceFile
from cvp.services.pagination import paginate_by_cursor
```

- [ ] **Step 7: Run the endpoint tests + full sweep**

```bash
uv run pytest tests/test_evidence_grid_pagination.py -v
uv run ruff format .
uv run ruff format --check .
uv run ruff check .
uv run pytest -x
```

Expected: new 3 tests pass; full suite green; ruff clean. If the existing matter-detail test breaks, it's almost certainly because it was asserting on the eager-loaded `matter.items` / `matter.evidence_files` paths — update the test to match the new context keys, but do NOT change the new context keys to match the test.

- [ ] **Step 8: Commit**

```bash
git add src/cvp/routers/evidence.py src/cvp/routers/matters.py src/cvp/templates/_evidence_grid.html src/cvp/templates/_evidence_grid_fragment.html tests/test_evidence_grid_pagination.py
git commit -m "feat: paginate evidence grid (cursor-based, HTMX infinite scroll, page size 24)"
```

---

## Task 5: Items pagination

**Files:**
- Create: `src/cvp/templates/_items_rows_fragment.html`
- Modify: `src/cvp/templates/_items_tbody.html`
- Modify: `src/cvp/templates/_tab_items.html` (totals use server-passed values)
- Modify: `src/cvp/routers/items.py` (new endpoint; `create_item` returns single row for OOB)
- Test: `tests/test_items_pagination.py`

- [ ] **Step 1: Write the failing endpoint tests**

Create `tests/test_items_pagination.py`:

```python
"""Tests for the paginated GET /api/matters/{matter_id}/items-rows endpoint."""

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
from cvp.services import access_cache

VIEWER_ID = "v1"
MATTER_ID = "m-items"


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
    Session = sessionmaker(bind=engine)
    s = Session()
    from cvp.models_auth import User

    s.add(User(id=VIEWER_ID, email="v@test.com", display_name="V", system_role="internal_user"))
    s.add(Matter(id=MATTER_ID, policyholder_name="P", loss_type="total_loss"))
    s.add(Category(id=1, name="C", useful_life_years=5, acv_floor_pct=0.2))
    s.commit()
    yield s
    s.close()


@pytest.fixture
def client(db_session, monkeypatch):
    import inspect
    import cvp.routers.items as items_router

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

    dep = inspect.signature(items_router.get_items_rows).parameters["user"].default.dependency
    app.dependency_overrides[dep] = mock_viewer
    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr("cvp.routers.items.SessionLocal", lambda: db_session)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _seed_items(db, count: int) -> list[Item]:
    rows = []
    for i in range(count):
        it = Item(
            matter_id=MATTER_ID,
            category_id=1,
            line_number=i + 1,
            description=f"item {i + 1}",
            quantity=1,
            age_years=0.0,
            condition="average",
            rcv_unit_cents=100,
            rcv_total_cents=100,
            acv_total_cents=80,
            confirmed=True,
        )
        db.add(it)
        rows.append(it)
    db.commit()
    return rows


def test_first_page_returns_50_rows_and_sentinel(client, db_session):
    _seed_items(db_session, 60)
    resp = client.get(f"/api/matters/{MATTER_ID}/items-rows")
    assert resp.status_code == 200
    body = resp.text
    assert body.count('<tr id="item-row-') == 50
    assert 'hx-trigger="revealed"' in body


def test_second_page_returns_remainder_and_no_sentinel(client, db_session):
    _seed_items(db_session, 60)
    resp = client.get(f"/api/matters/{MATTER_ID}/items-rows?cursor=50")
    assert resp.status_code == 200
    body = resp.text
    assert body.count('<tr id="item-row-') == 10
    assert 'hx-trigger="revealed"' not in body


def test_empty_matter_returns_no_rows_no_sentinel(client):
    resp = client.get(f"/api/matters/{MATTER_ID}/items-rows")
    assert resp.status_code == 200
    assert '<tr id="item-row-' not in resp.text
    assert 'hx-trigger="revealed"' not in resp.text
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_items_pagination.py -v
```

Expected: FAIL — endpoint `get_items_rows` doesn't exist.

- [ ] **Step 3: Create the rows fragment partial**

Create `src/cvp/templates/_items_rows_fragment.html`:

```html
{% for item in items %}{% include "_item_row.html" %}{% endfor %}
{% if items_next_cursor %}
<tr hx-get="/api/matters/{{ matter_id }}/items-rows?cursor={{ items_next_cursor }}"
    hx-trigger="revealed"
    hx-swap="outerHTML">
  <td colspan="13" class="text-center text-xs text-gray-400 py-2">Loading…</td>
</tr>
{% endif %}
```

(`colspan="13"` matches the column count in `_items_tbody.html`'s thead; the existing empty-state row at line 84 also uses 13.)

- [ ] **Step 4: Update `_items_tbody.html` to use the fragment**

Replace the full contents of `src/cvp/templates/_items_tbody.html` with:

```html
{% set room_map = {} %}
{% for r in rooms %}{% set _ = room_map.update({r.id: r.name}) %}{% endfor %}
{% set cat_map = {} %}
{% for c in categories %}{% set _ = cat_map.update({c.id: c.name}) %}{% endfor %}
{% if items_total_count and items_total_count > 0 %}
{% include "_items_rows_fragment.html" %}
{% else %}
<tr id="items-empty-row">
  <td colspan="13" class="px-6 py-10 text-center text-sm text-gray-400">
    No items yet — add one above.
  </td>
</tr>
{% endif %}
```

The `room_map` / `cat_map` set blocks stay because `_item_row.html` reads them.

- [ ] **Step 5: Update the totals line in `_tab_items.html`**

In `src/cvp/templates/_tab_items.html`, replace the totals block (around lines 101–108):

```html
  {% if items %}
  <div class="flex justify-end gap-6 text-sm text-gray-600">
    {% set confirmed_items = items | selectattr("confirmed") | rejectattr("excluded") | list %}
    <span>Confirmed: <strong class="text-gray-900">{{ confirmed_items | length }}</strong> of {{ items | length }}</span>
    <span>RCV total: <strong class="font-mono text-gray-900">${{ "%.2f" % (confirmed_items | sum(attribute="rcv_total_cents") / 100) }}</strong></span>
    <span>ACV total: <strong class="font-mono text-gray-900">${{ "%.2f" % (confirmed_items | sum(attribute="acv_total_cents") / 100) }}</strong></span>
  </div>
  {% endif %}
```

With:

```html
  {% if items_total_count and items_total_count > 0 %}
  <div class="flex justify-end gap-6 text-sm text-gray-600">
    <span>Confirmed: <strong class="text-gray-900">{{ items_confirmed_count }}</strong> of {{ items_total_count }}</span>
    <span>RCV total: <strong class="font-mono text-gray-900">${{ "%.2f" % (items_rcv_total_cents / 100) }}</strong></span>
    <span>ACV total: <strong class="font-mono text-gray-900">${{ "%.2f" % (items_acv_total_cents / 100) }}</strong></span>
  </div>
  {% endif %}
```

- [ ] **Step 6: Add the paginated items endpoint + adapt `create_item`**

In `src/cvp/routers/items.py`:

**6a.** Add this import near the top:

```python
from cvp.services.pagination import paginate_by_cursor
```

**6b.** Add a constant near the top of the file (after the existing module-level constants):

```python
ITEMS_PAGE_SIZE = 50
```

**6c.** Add the new endpoint anywhere alongside the other `@router` handlers (e.g., right after `_items_tbody_html`):

```python
@router.get("/api/matters/{matter_id}/items-rows", response_class=HTMLResponse)
def get_items_rows(
    request: Request,
    matter_id: str,
    cursor: str = "",
    user: CurrentUser = Depends(require_matter_role("viewer")),
) -> HTMLResponse:
    """Render one cursor-paginated page of item `<tr>` rows + sentinel.

    `cursor` is the line_number of the last row from the previous page
    (empty string for the first page). Rows are ordered by `line_number` ASC.
    """
    cursor_int = int(cursor) if cursor else None
    db = SessionLocal()
    try:
        rows, next_cursor = paginate_by_cursor(
            db.query(Item).options(selectinload(Item.crops))
                .filter(Item.matter_id == matter_id),
            cursor_col=Item.line_number,
            cursor_value=cursor_int,
            limit=ITEMS_PAGE_SIZE,
            order="asc",
        )
        categories, room_objs, _groups = _get_context(matter_id, db)
    finally:
        db.close()
    return HTMLResponse(
        templates.get_template("_items_rows_fragment.html").render(
            items=rows,
            items_next_cursor=next_cursor,
            matter_id=matter_id,
            categories=categories,
            rooms=room_objs,
        )
    )
```

**6d.** Update `create_item` to return just the new row for OOB append (not the full tbody). Find the existing `create_item` handler. Its current return path uses:

```python
        html = _items_tbody_html(matter_id, db)
    finally:
        db.close()
    background_tasks.add_task(...)
    return HTMLResponse(html)
```

Change to:

```python
        categories, rooms, item_groups = _get_context(matter_id, db)
        # OOB append to the existing tbody so users on any loaded page see the new row.
        row_html = templates.get_template("_item_row.html").render(
            item=item, categories=categories, rooms=rooms, item_groups=item_groups
        )
        oob = (
            '<tr id="item-row-' + item.id + '" hx-swap-oob="beforeend:#items-tbody">'
            + row_html.replace('<tr id="item-row-' + item.id + '"', '<tr', 1)
            + '</tr>'
        )
        # Note: we wrap with hx-swap-oob "beforeend:#items-tbody" then strip the outer
        # <tr> from the rendered partial. Simpler: render just the bare row and rely on
        # HTMX OOB to append it.
```

Actually that's awkward. Use this cleaner approach instead — replace the whole `html = _items_tbody_html(matter_id, db)` line plus the subsequent `return HTMLResponse(html)` near the end of `create_item` with:

```python
        categories, rooms, item_groups = _get_context(matter_id, db)
        row_html = _item_row_html(item, categories, rooms, item_groups)
    finally:
        db.close()
    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="item.create",
        resource_type="item",
        resource_id=item_id,
        matter_id=matter_id,
        ip_address=get_client_ip(request),
    )
    # Use HX-Trigger to nudge the client to refresh totals + drop empty-state row.
    headers = {"HX-Trigger": "item-created"}
    return HTMLResponse(row_html, headers=headers, status_code=200)
```

And update the form in `src/cvp/templates/_tab_items.html` (the add-item form near the top of the tab, around lines 8–10) to OOB-append into the tbody by adding `hx-swap="beforeend"` and `hx-target="#items-tbody"`:

Find:

```html
      <form hx-post="/api/matters/{{ matter.id }}/items"
```

Change the surrounding attributes (the form's existing `hx-target` / `hx-swap`) to:

```html
      <form hx-post="/api/matters/{{ matter.id }}/items"
            hx-target="#items-tbody"
            hx-swap="beforeend"
```

(Confirm the existing attributes; if a different target/swap is already configured, replace them with these two. If the form already had `hx-target="#items-tbody"` and `hx-swap="innerHTML"`, change to `beforeend`.)

The `HX-Trigger: item-created` header is emitted but unused by the client for now (totals stay slightly stale after add until the user reloads — acceptable for v1, called out in the spec as known behavior).

**6e.** Delete the now-unused `_items_tbody_html` helper function at the top of `items.py` (around lines 85–100). No other callers — `create_item` was the only one.

- [ ] **Step 7: Run the tests + full sweep**

```bash
uv run pytest tests/test_items_pagination.py -v
uv run ruff format .
uv run ruff format --check .
uv run ruff check .
uv run pytest -x
```

Expected: new 3 tests pass; full suite green; ruff clean.

If existing items tests break because they asserted on the old `_items_tbody_html` return value, update the assertions to match the new single-row return.

- [ ] **Step 8: Commit**

```bash
git add src/cvp/routers/items.py src/cvp/templates/_items_tbody.html src/cvp/templates/_items_rows_fragment.html src/cvp/templates/_tab_items.html tests/test_items_pagination.py
git commit -m "feat: paginate items table (cursor by line_number, page size 50, OOB row append on add)"
```

---

## Task 6: Heavy-list manual verification

This is the original failure case (50+ thumbnails exhausting the pool) plus a smoke check on the items page.

- [ ] **Step 1: Reuse the 53 synthetic JPEGs from PR #17 QA or regenerate**

If `/tmp/cvp-upload-test/` is gone, regenerate:

```bash
mkdir -p /tmp/cvp-upload-test && cd /tmp/cvp-upload-test
source /Users/cmondor/consulting/tor/.venv/bin/activate
for i in $(seq 1 60); do
  python -c "from PIL import Image; import random; \
    Image.new('RGB', (2000, 1500), (random.randint(0,255), random.randint(0,255), random.randint(0,255))).save(open('img_$(printf %02d $i).jpg','wb'), 'JPEG', quality=90)"
done
ls -lh | head
```

- [ ] **Step 2: Upload all 60 via the dev server**

`cd /Users/cmondor/consulting/tor && uv run dev`. Drop all 60. After drain, you should see the first 24 in the grid with a "Loading…" sentinel at the bottom.

- [ ] **Step 3: Verify infinite scroll works**

Scroll down. The sentinel should fire when it enters the viewport (DevTools Network → one new `evidence-grid?cursor=…` request). New tiles append. Scroll to the bottom — last batch arrives, no further sentinel.

- [ ] **Step 4: Verify QueuePool stays healthy**

DevTools Network: as you scroll, the thumbnails for newly-revealed tiles fire `/files/...` requests but the burst is bounded by what's visible. The application logs should show no `QueuePool timeout` errors.

If you have shell access to the prod-like environment (or stand up the Postgres branch locally), check `pg_stat_activity` during the burst — connections held by `cvp` should stay under 50.

- [ ] **Step 5: Items smoke check**

On the same matter (or one with > 50 items), open the Items tab. Confirm first 50 rows render. Scroll down — sentinel fires, next 50 load. Add a new item via the form — confirm the new row appears appended at the bottom of the tbody.

- [ ] **Step 6: Commit any tweaks from manual QA**

```bash
git add -A
git commit -m "fix: <what you tweaked>"
```

(Skip if nothing needs tweaking.)

---

## Task 7: Push branch + open PR

- [ ] **Step 1: Push**

```bash
git push -u origin spec/lazy-paginated-evidence-items
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create --title "feat: lazy & paginated evidence and items pages" --body "$(cat <<'EOF'
## Summary
- Adds an in-memory `(user_id, matter_id, minimum_role) -> bool` TTL cache (60 s) wrapping `_check_matter_access`, eliminating the per-thumbnail DB burst that exhausted the SQLAlchemy pool after PR #17.
- Adds cursor-based HTMX infinite scroll for the evidence grid (page size 24) and items table (page size 50), backed by a shared `paginate_by_cursor` helper.
- `loading="lazy"` + `decoding="async"` on thumbnail `<img>` tags so the browser only fetches viewport images.
- Modest SQLAlchemy pool bump: 10 + 20 → 20 + 30 on Postgres.

Spec: `docs/superpowers/specs/2026-06-10-lazy-paginated-evidence-and-items-design.md`

Known follow-up (in spec Backlog): wire `invalidate_matter` / `invalidate_user` into MatterAccess grant/revoke and user role-change paths. Until then, worst-case staleness after a role revocation is 60 s.

## Test plan
- [x] `uv run pytest -x` green
- [x] `uv run ruff format --check . && uv run ruff check .` clean
- [ ] Manual: drop 60 × 1 MB JPEGs, reload matter — first 24 render with sentinel, scroll loads next batches, no QueuePool errors
- [ ] Manual: matter with > 50 items — first 50 render with sentinel, scroll loads next batch
- [ ] Manual: add item via form on a matter with > 50 items — new row appended to tbody

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Return the PR URL**

Print the URL for the user.

---

## Plan self-review

**Spec coverage check:**
- ✅ Access cache (60 s TTL, 1024 cap, system_admin bypass, invalidate helpers) → Task 1
- ✅ Lazy thumbnails + pool bump → Task 2
- ✅ Pagination helper → Task 3
- ✅ Evidence grid pagination (page 24, cursor by `created_at` desc, sentinel) → Task 4
- ✅ Items pagination (page 50, cursor by `line_number` asc, sentinel) → Task 5
- ✅ `_evidence_grid_fragment.html` + `_items_rows_fragment.html` → Tasks 4, 5
- ✅ Matter detail handler drops eager loads, passes first-page + cursors + totals → Task 4 (covers both items and evidence context wiring; Task 5 only updates the items totals display template)
- ✅ `create_item` OOB row append behavior → Task 5
- ✅ Manual heavy-list verification → Task 6
- ✅ Single PR rollout → Task 7

**Placeholder scan:** none. All code blocks complete.

**Type / name consistency check:**
- `access_cache.check_matter_access_cached` / `invalidate_matter` / `invalidate_user` / `_cache` / `_TTL_SECONDS` / `_MAX_ENTRIES` / `_EVICT_BATCH` / `_now` consistent across module, tests, dependencies wiring.
- `paginate_by_cursor` signature `(query, *, cursor_col, cursor_value, limit, order)` consistent across module, tests, evidence endpoint, items endpoint, matter detail handler.
- Template context keys: `evidence_files` / `evidence_next_cursor` / `items` / `items_next_cursor` / `items_total_count` / `items_confirmed_count` / `items_rcv_total_cents` / `items_acv_total_cents` consistent across matter detail handler, `_evidence_grid_fragment.html`, `_items_rows_fragment.html`, `_items_tbody.html`, `_tab_items.html`.
- `EVIDENCE_PAGE_SIZE = 24` and `ITEMS_PAGE_SIZE = 50` constants live alongside the endpoints; the matter detail handler hard-codes `24` and `50` for the first-page query (acceptable — two places, two constants would mean a cross-file import for cosmetic gain).

**Known plan soft spots:**
- Task 4 Step 6 edits `matters.py` substantially. The `selectinload` removal and totals-aggregate-query refactor should be sanity-checked against existing matter-detail tests; if any break, prefer updating the test to match the new (correct) behavior rather than restoring the old (load-everything) pattern.
- Task 5 Step 6d's `create_item` OOB swap relies on `hx-target="#items-tbody"` + `hx-swap="beforeend"` on the form. If the existing form has different attrs, the implementer must reconcile rather than blindly overwrite.
- The HX-Trigger emitted on item creation is wired but unused; totals will be 1-row stale after add until reload. Called out as acceptable in the spec's behavior note.
