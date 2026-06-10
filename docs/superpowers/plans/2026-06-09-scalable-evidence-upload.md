# Scalable Evidence Upload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the all-in-one multipart evidence upload with per-file streaming uploads driven by a small in-browser concurrency queue, with runtime-configurable caps tunable by a system admin without redeploy.

**Architecture:** New `app_setting` table holds runtime overrides for three knobs (concurrency / max-file-MB / max-batch-count); pydantic-settings values are the startup defaults. A new `runtime_config` service reads settings with a 30 s in-process TTL cache. The evidence upload endpoint becomes single-file, streams to disk via `run_in_threadpool` + chunked copy, inserts one row, returns one HTML tile. The browser fans the user's drop into N parallel single-file POSTs.

**Tech Stack:** FastAPI, SQLAlchemy 2.x, Alembic, Jinja2, HTMX, vanilla JS, pytest, ruff.

**Companion spec:** `docs/superpowers/specs/2026-06-09-scalable-evidence-upload-design.md`. A separate plan for "lazy/paginated evidence + items pages" will follow this one.

**Branch:** work proceeds on `spec/scalable-evidence-upload` (already created for the spec commit) or a sibling feature branch — pick at execution start. Never commit to `main`.

---

## File Map

**New files:**
- `src/cvp/models_app_setting.py` — `AppSetting` SQLAlchemy model
- `migrations/versions/<rev>_add_app_setting_table.py` — Alembic migration
- `src/cvp/services/runtime_config.py` — `get_setting(...)` with TTL cache and env-var fallback
- `src/cvp/routers/admin/runtime_config.py` — `/admin/system/runtime-config` GET/POST
- `src/cvp/templates/admin/system/runtime_config.html` — admin form page
- `src/cvp/templates/_evidence_tile.html` — single-tile partial extracted from grid
- `tests/test_runtime_config.py`
- `tests/test_admin_runtime_config.py`
- `tests/test_evidence_upload.py`

**Modified files:**
- `src/cvp/models.py` — add `import cvp.models_app_setting` to the trailing register block
- `src/cvp/config.py` — three new `Settings` fields
- `src/cvp/main.py` — register the runtime-config admin router
- `src/cvp/templates/admin/system/dashboard.html` — add a "Runtime Config" tile/link
- `src/cvp/routers/evidence.py` — replace `upload_evidence` batch handler with single-file streaming handler
- `src/cvp/templates/_evidence_grid.html` — replace per-loop tile body with `{% include "_evidence_tile.html" %}`
- `src/cvp/templates/_tab_evidence.html` — drop-zone `data-*` attributes + progress strip; remove `hx-post` on the form (queue does it now)
- `src/cvp/static/app.js` — replace `initEvidenceUpload` with `EvidenceUploadQueue`

---

## Task 1: AppSetting model + migration

**Files:**
- Create: `src/cvp/models_app_setting.py`
- Modify: `src/cvp/models.py` (trailing import block)
- Create: `migrations/versions/<rev>_add_app_setting_table.py`
- Test: `tests/test_runtime_config.py` (just an import smoke test for now)

- [ ] **Step 1: Write the failing test**

Create `tests/test_runtime_config.py`:

```python
"""Tests for AppSetting model and runtime_config service."""

from cvp.models_app_setting import AppSetting


def test_app_setting_model_importable_with_expected_columns():
    cols = {c.name for c in AppSetting.__table__.columns}
    assert cols == {"key", "value_json", "updated_at", "updated_by_user_id"}
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/test_runtime_config.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'cvp.models_app_setting'`.

- [ ] **Step 3: Create the model**

Create `src/cvp/models_app_setting.py`:

```python
"""Runtime-configurable settings stored in the DB, edited via System Admin UI."""

from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from cvp.models import Base


class AppSetting(Base):
    """A single runtime-tunable key/value pair.

    `value_json` stores the value as a JSON-encoded string so we can keep ints,
    floats, bools, and strings in one column without per-type tables. Defaults
    for missing keys come from `cvp.config.Settings` (env vars at startup).
    """

    __tablename__ = "app_setting"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False
    )
    updated_by_user_id: Mapped[str | None] = mapped_column(String, nullable=True)
```

Then register it in `src/cvp/models.py` by adding a new line in the trailing register block (the section starting around line 367 with `import cvp.models_access`):

```python
import cvp.models_app_setting as _app_setting_models  # noqa: F401, E402 — register app_setting table with Base
```

- [ ] **Step 4: Verify the test passes**

```bash
uv run pytest tests/test_runtime_config.py -v
```

Expected: PASS.

- [ ] **Step 5: Generate the migration**

```bash
uv run alembic revision --autogenerate -m "add app_setting table"
```

Open the generated file under `migrations/versions/`. Confirm `upgrade()` calls `op.create_table("app_setting", ...)` with the four columns and a primary key on `key`. Confirm `downgrade()` calls `op.drop_table("app_setting")`. If autogenerate produced anything else (e.g. unrelated diff because of model drift), trim the migration to *only* the `app_setting` table changes.

- [ ] **Step 6: Apply the migration locally and confirm it round-trips**

```bash
uv run alembic upgrade head
uv run alembic downgrade -1
uv run alembic upgrade head
```

Expected: all three commands succeed with no errors.

- [ ] **Step 7: Run full test suite + lint + format**

```bash
uv run ruff format .
uv run ruff format --check .
uv run ruff check .
uv run pytest -x
```

Expected: zero files reformatted, no lint errors, all tests pass.

- [ ] **Step 8: Commit**

```bash
git add src/cvp/models_app_setting.py src/cvp/models.py migrations/versions/*app_setting* tests/test_runtime_config.py
git commit -m "feat: add app_setting table for runtime config"
```

---

## Task 2: runtime_config service with TTL cache

**Files:**
- Create: `src/cvp/services/runtime_config.py`
- Modify: `src/cvp/config.py` (three new Settings fields)
- Modify: `tests/test_runtime_config.py` (add real coverage)

- [ ] **Step 1: Add the failing tests**

Replace `tests/test_runtime_config.py` with:

```python
"""Tests for AppSetting model and runtime_config service."""

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from cvp.models import Base
from cvp.models_app_setting import AppSetting
from cvp.services import runtime_config


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
    yield s
    s.close()


@pytest.fixture(autouse=True)
def clear_cache():
    runtime_config._cache.clear()
    yield
    runtime_config._cache.clear()


def test_app_setting_model_columns():
    cols = {c.name for c in AppSetting.__table__.columns}
    assert cols == {"key", "value_json", "updated_at", "updated_by_user_id"}


def test_get_int_returns_env_default_when_no_db_row(db):
    assert runtime_config.get_int(db, "evidence_upload_concurrency") == 4


def test_get_int_returns_db_override_when_row_exists(db):
    db.add(AppSetting(key="evidence_upload_concurrency", value_json=json.dumps(7)))
    db.commit()
    assert runtime_config.get_int(db, "evidence_upload_concurrency") == 7


def test_get_int_rejects_out_of_bounds_value_and_returns_default(db):
    db.add(AppSetting(key="evidence_upload_concurrency", value_json=json.dumps(999)))
    db.commit()
    # 999 exceeds the documented 1..16 bound; service falls back to env default
    assert runtime_config.get_int(db, "evidence_upload_concurrency") == 4


def test_cache_returns_stale_value_within_ttl(db, monkeypatch):
    db.add(AppSetting(key="evidence_upload_concurrency", value_json=json.dumps(7)))
    db.commit()
    assert runtime_config.get_int(db, "evidence_upload_concurrency") == 7

    # Update DB but stay within TTL — cached value (7) should still be returned
    db.query(AppSetting).filter_by(key="evidence_upload_concurrency").update(
        {"value_json": json.dumps(12)}
    )
    db.commit()
    assert runtime_config.get_int(db, "evidence_upload_concurrency") == 7


def test_cache_refreshes_after_ttl_expires(db, monkeypatch):
    db.add(AppSetting(key="evidence_upload_concurrency", value_json=json.dumps(7)))
    db.commit()
    assert runtime_config.get_int(db, "evidence_upload_concurrency") == 7

    # Fast-forward past TTL
    monkeypatch.setattr(
        runtime_config,
        "_now",
        lambda: runtime_config._cache["evidence_upload_concurrency"][0]
        + runtime_config._TTL_SECONDS
        + 1,
    )
    db.query(AppSetting).filter_by(key="evidence_upload_concurrency").update(
        {"value_json": json.dumps(12)}
    )
    db.commit()
    assert runtime_config.get_int(db, "evidence_upload_concurrency") == 12


def test_set_value_writes_row_and_invalidates_cache(db):
    runtime_config.set_value(db, "evidence_upload_concurrency", 9, updated_by_user_id="u1")
    row = db.query(AppSetting).filter_by(key="evidence_upload_concurrency").one()
    assert json.loads(row.value_json) == 9
    assert row.updated_by_user_id == "u1"
    # Cache invalidated, so a fresh read returns the new value immediately
    assert runtime_config.get_int(db, "evidence_upload_concurrency") == 9
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_runtime_config.py -v
```

Expected: FAIL with `ModuleNotFoundError` or `AttributeError` on `runtime_config.get_int` / `set_value` / `_cache`.

- [ ] **Step 3: Add the three new Settings fields**

In `src/cvp/config.py`, inside `class Settings(BaseSettings)`, add at the bottom (before the closing of the class):

```python
    # Evidence upload runtime knobs — overridable per matter session via app_setting table
    evidence_upload_concurrency: int = 4
    evidence_upload_max_file_mb: int = 10
    evidence_upload_max_batch_count: int = 500
```

- [ ] **Step 4: Implement the runtime_config service**

Create `src/cvp/services/runtime_config.py`:

```python
"""Runtime-configurable settings backed by the `app_setting` DB table.

Defaults come from `cvp.config.Settings` (env vars / .env). A row in
`app_setting` with the matching key, when present, supersedes the env default.

Reads are cached in-process for a short TTL to avoid hammering the DB on every
request. Writes via `set_value` invalidate the cache immediately so admin edits
take effect on the next request.
"""

import json
import time
from typing import Any

from sqlalchemy.orm import Session

from cvp.config import settings
from cvp.models_app_setting import AppSetting

_TTL_SECONDS: float = 30.0
_cache: dict[str, tuple[float, Any]] = {}  # key -> (loaded_at, value)


# Bounds enforced on read: any DB value outside the range is ignored, falling
# back to the env default. Admin UI also enforces these on write.
_BOUNDS: dict[str, tuple[int, int]] = {
    "evidence_upload_concurrency": (1, 16),
    "evidence_upload_max_file_mb": (1, 100),
    "evidence_upload_max_batch_count": (1, 5000),
}


def _now() -> float:
    """Wall clock — split out so tests can monkeypatch."""
    return time.time()


def _env_default(key: str) -> Any:
    return getattr(settings, key)


def _load_from_db(db: Session, key: str) -> Any:
    row = db.query(AppSetting).filter_by(key=key).first()
    if row is None:
        return _env_default(key)
    try:
        value = json.loads(row.value_json)
    except (json.JSONDecodeError, TypeError):
        return _env_default(key)
    bounds = _BOUNDS.get(key)
    if bounds and isinstance(value, int):
        lo, hi = bounds
        if value < lo or value > hi:
            return _env_default(key)
    return value


def get_int(db: Session, key: str) -> int:
    """Return the current int value for `key`, using the DB override if present."""
    cached = _cache.get(key)
    if cached is not None:
        loaded_at, value = cached
        if (_now() - loaded_at) < _TTL_SECONDS:
            return int(value)
    value = _load_from_db(db, key)
    _cache[key] = (_now(), value)
    return int(value)


def set_value(db: Session, key: str, value: Any, *, updated_by_user_id: str | None) -> None:
    """Write a value to `app_setting`, invalidating the in-process cache."""
    bounds = _BOUNDS.get(key)
    if bounds and isinstance(value, int):
        lo, hi = bounds
        if value < lo or value > hi:
            raise ValueError(f"{key}={value} out of bounds {bounds}")
    row = db.query(AppSetting).filter_by(key=key).first()
    if row is None:
        row = AppSetting(key=key, value_json=json.dumps(value), updated_by_user_id=updated_by_user_id)
        db.add(row)
    else:
        row.value_json = json.dumps(value)
        row.updated_by_user_id = updated_by_user_id
    db.commit()
    _cache.pop(key, None)
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
uv run pytest tests/test_runtime_config.py -v
```

Expected: all 7 tests pass.

- [ ] **Step 6: Format + lint + full test sweep**

```bash
uv run ruff format .
uv run ruff format --check .
uv run ruff check .
uv run pytest -x
```

Expected: zero files reformatted, no lint errors, all tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/cvp/services/runtime_config.py src/cvp/config.py tests/test_runtime_config.py
git commit -m "feat: runtime_config service with TTL cache and bounds"
```

---

## Task 3: Admin runtime-config page

**Files:**
- Create: `src/cvp/routers/admin/runtime_config.py`
- Create: `src/cvp/templates/admin/system/runtime_config.html`
- Modify: `src/cvp/templates/admin/system/dashboard.html` (add link)
- Modify: `src/cvp/main.py` (register router)
- Test: `tests/test_admin_runtime_config.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_admin_runtime_config.py`:

```python
"""Tests for /admin/system/runtime-config admin page."""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cvp.models_vision  # noqa: F401
from cvp.db import get_db
from cvp.dependencies import CurrentUser, require_system_admin
from cvp.main import app
from cvp.models import Base
from cvp.models_app_setting import AppSetting
from cvp.services import runtime_config


@pytest.fixture(autouse=True)
def clear_cache():
    runtime_config._cache.clear()
    yield
    runtime_config._cache.clear()


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
    yield s
    s.close()


@pytest.fixture
def admin_client(db_session):
    async def mock_admin():
        return CurrentUser(
            id="admin-1",
            email="admin@test.com",
            system_role="system_admin",
            group_id=None,
            group_kind=None,
        )

    def override_get_db():
        yield db_session

    app.dependency_overrides[require_system_admin] = mock_admin
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_get_renders_form_with_current_values(admin_client):
    resp = admin_client.get("/admin/system/runtime-config")
    assert resp.status_code == 200
    body = resp.text
    assert "evidence_upload_concurrency" in body
    assert "evidence_upload_max_file_mb" in body
    assert "evidence_upload_max_batch_count" in body
    # Defaults from Settings
    assert 'value="4"' in body
    assert 'value="10"' in body
    assert 'value="500"' in body


def test_post_updates_row_and_redirects(admin_client, db_session):
    resp = admin_client.post(
        "/admin/system/runtime-config",
        data={"evidence_upload_concurrency": "8"},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)
    row = db_session.query(AppSetting).filter_by(key="evidence_upload_concurrency").one()
    assert json.loads(row.value_json) == 8


def test_post_rejects_out_of_bounds(admin_client, db_session):
    resp = admin_client.post(
        "/admin/system/runtime-config",
        data={"evidence_upload_concurrency": "999"},
        follow_redirects=False,
    )
    assert resp.status_code == 400
    assert db_session.query(AppSetting).filter_by(key="evidence_upload_concurrency").first() is None
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/test_admin_runtime_config.py -v
```

Expected: FAIL with 404 on `/admin/system/runtime-config`.

- [ ] **Step 3: Create the admin router**

Create `src/cvp/routers/admin/runtime_config.py`:

```python
"""System-admin page for runtime-configurable settings stored in app_setting."""

from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from cvp.db import get_db
from cvp.dependencies import CurrentUser, require_system_admin
from cvp.services import runtime_config

BASE_DIR = Path(__file__).parent.parent.parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")

router = APIRouter(prefix="/admin/system/runtime-config")

_KNOBS = (
    "evidence_upload_concurrency",
    "evidence_upload_max_file_mb",
    "evidence_upload_max_batch_count",
)


@router.get("", response_class=HTMLResponse)
def index(
    request: Request,
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    rows = [{"key": k, "value": runtime_config.get_int(db, k)} for k in _KNOBS]
    return templates.TemplateResponse(
        request,
        "admin/system/runtime_config.html",
        {
            "user": user,
            "rows": rows,
            "bounds": runtime_config._BOUNDS,
            "breadcrumbs": [
                {"label": "System Admin", "url": "/admin/system/"},
                {"label": "Runtime Config", "url": "/admin/system/runtime-config"},
            ],
        },
    )


@router.post("", response_class=HTMLResponse)
def update(
    request: Request,
    evidence_upload_concurrency: int | None = Form(None),
    evidence_upload_max_file_mb: int | None = Form(None),
    evidence_upload_max_batch_count: int | None = Form(None),
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    submitted = {
        "evidence_upload_concurrency": evidence_upload_concurrency,
        "evidence_upload_max_file_mb": evidence_upload_max_file_mb,
        "evidence_upload_max_batch_count": evidence_upload_max_batch_count,
    }
    for key, value in submitted.items():
        if value is None:
            continue
        try:
            runtime_config.set_value(db, key, value, updated_by_user_id=user.id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
    return RedirectResponse(url="/admin/system/runtime-config", status_code=303)
```

- [ ] **Step 4: Create the admin template**

Create `src/cvp/templates/admin/system/runtime_config.html`:

```html
{% extends "admin/base.html" %}
{% block content %}
<div class="space-y-4">
  <h1 class="text-xl font-semibold text-gray-800">Runtime Config</h1>
  <p class="text-sm text-gray-600">
    These values override the corresponding environment variables at runtime.
    Changes take effect within 30 seconds. Bounds are enforced both client- and
    server-side.
  </p>

  <form method="post" action="/admin/system/runtime-config" class="space-y-3 max-w-md">
    <input type="hidden" name="_csrf" value="{{ request.cookies.get('cvp_csrf', '') }}">
    {% for row in rows %}
      {% set lo, hi = bounds[row.key] %}
      <label class="block">
        <span class="text-sm font-medium text-gray-700">{{ row.key }}</span>
        <input
          type="number"
          name="{{ row.key }}"
          value="{{ row.value }}"
          min="{{ lo }}"
          max="{{ hi }}"
          class="mt-1 block w-32 rounded border border-gray-300 px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-indigo-500">
        <span class="text-xs text-gray-400">range {{ lo }}–{{ hi }}</span>
      </label>
    {% endfor %}
    <button type="submit"
            class="rounded bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-500">
      Save
    </button>
  </form>
</div>
{% endblock %}
```

- [ ] **Step 5: Add a link on the dashboard**

In `src/cvp/templates/admin/system/dashboard.html`, find the existing tile/link grid and add a new card linking to `/admin/system/runtime-config`. Use the same markup pattern as the surrounding tiles; if the dashboard uses a simple `<a>` list, append:

```html
<a href="/admin/system/runtime-config"
   class="block rounded-lg border border-gray-200 bg-white p-4 hover:bg-gray-50">
  <p class="text-sm font-semibold text-gray-800">Runtime Config</p>
  <p class="text-xs text-gray-500">Evidence upload caps and concurrency.</p>
</a>
```

(If the file uses a different pattern — e.g. cards-in-a-grid component — match the existing style. Open the file first to confirm.)

- [ ] **Step 6: Register the router**

In `src/cvp/main.py`, in the `from cvp.routers.admin import ...` block, add:

```python
from cvp.routers.admin import runtime_config as admin_runtime_config
```

And in the `app.include_router(...)` block (around line 85), add:

```python
app.include_router(admin_runtime_config.router)
```

- [ ] **Step 7: Run the tests to verify they pass**

```bash
uv run pytest tests/test_admin_runtime_config.py -v
```

Expected: all 3 tests pass.

- [ ] **Step 8: Format + lint + full test sweep**

```bash
uv run ruff format .
uv run ruff format --check .
uv run ruff check .
uv run pytest -x
```

Expected: zero reformat, no lint errors, all tests pass.

- [ ] **Step 9: Commit**

```bash
git add src/cvp/routers/admin/runtime_config.py src/cvp/templates/admin/system/runtime_config.html src/cvp/templates/admin/system/dashboard.html src/cvp/main.py tests/test_admin_runtime_config.py
git commit -m "feat: admin page for runtime config (/admin/system/runtime-config)"
```

---

## Task 4: Extract `_evidence_tile.html` partial

This is a pure refactor — no behavior change. Done as its own commit to keep Task 5's diff focused on upload logic.

**Files:**
- Create: `src/cvp/templates/_evidence_tile.html`
- Modify: `src/cvp/templates/_evidence_grid.html`

- [ ] **Step 1: Create the tile partial**

Create `src/cvp/templates/_evidence_tile.html` with the contents of the `<div data-file-card ...>` block currently in `_evidence_grid.html` (lines 7–63). The partial expects two variables in scope: `f` (an `EvidenceFile`) and `matter_id` (str). Existing optional scope variables (`item_groups_flat`, `scan_errors`) work unchanged because Jinja uses outer-scope lookups.

```html
<div data-file-card class="group relative rounded-lg border border-gray-200 bg-white overflow-hidden shadow-sm">
  {% if f.kind == "image" %}
  <img src="/files/{{ f.stored_path }}"
       alt="{{ f.filename }}"
       class="h-32 w-full object-cover">
  {% elif f.kind == "pdf" %}
  <div class="flex h-32 items-center justify-center bg-red-50 text-4xl">📄</div>
  {% elif f.kind == "video" %}
  <div class="flex h-32 items-center justify-center bg-purple-50 text-4xl">🎬</div>
  {% else %}
  <div class="flex h-32 items-center justify-center bg-gray-50 text-4xl">📎</div>
  {% endif %}

  <div class="px-2 py-1.5">
    <p class="truncate text-xs font-medium text-gray-700" title="{{ f.filename }}">{{ f.filename }}</p>
    <p class="text-xs text-gray-400">{{ (f.size_bytes / 1024) | round(1) }} KB</p>
    {% if f.kind == "image" and item_groups_flat is defined %}
      {% include "_evidence_group_select.html" %}
    {% endif %}
    {% if f.kind == "image" %}
      {% if f.scanned %}
      <button data-toggle-crop-editor="{{ f.id }}"
              class="mt-1 rounded border border-indigo-200 px-1.5 py-0.5 text-xs text-indigo-600 hover:bg-indigo-50">
        Edit crops
      </button>
      {% else %}
      <form hx-post="/api/matters/{{ matter_id }}/vision-scan"
            hx-target="#scan-progress-{{ f.id }}"
            hx-include="#model_slug"
            hx-swap="innerHTML"
            class="mt-1">
        <input type="hidden" name="evidence_file_ids" value="{{ f.id }}">
        <button type="submit"
                class="rounded border border-violet-200 px-1.5 py-0.5 text-xs text-violet-600 hover:bg-violet-50">
          Scan Now
        </button>
      </form>
      {% if scan_errors is defined and f.id in scan_errors %}
      <p class="mt-0.5 truncate text-xs text-red-600"
         title="{{ scan_errors[f.id] }}">
        Scan failed: {{ scan_errors[f.id][:60] }}
      </p>
      {% endif %}
      <div id="scan-progress-{{ f.id }}"></div>
      {% endif %}
    {% endif %}
  </div>

  <button
    hx-delete="/api/evidence/{{ f.id }}"
    hx-target="closest [data-file-card]"
    hx-swap="outerHTML"
    hx-confirm="Delete {{ f.filename }}?"
    class="absolute right-1 top-1 hidden rounded bg-red-600 px-1.5 py-0.5 text-xs font-semibold text-white opacity-90 group-hover:block hover:bg-red-700">
    ✕
  </button>
</div>
```

- [ ] **Step 2: Update `_evidence_grid.html` to include the partial**

Replace the body of the `{% for f in evidence_files %}` loop in `src/cvp/templates/_evidence_grid.html` with just `{% include "_evidence_tile.html" %}`. The full file becomes:

```html
{% if vision_models is defined and vision_models %}
{% include "_vision_model_picker.html" %}
{% endif %}
<div id="evidence-grid"
     class="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
  {% for f in evidence_files %}
  {% include "_evidence_tile.html" %}
  {% endfor %}
</div>
```

- [ ] **Step 3: Verify the existing grid still renders unchanged**

```bash
uv run pytest -x
```

Expected: all tests pass. (No test changes; we are just verifying nothing regressed.) Then manually open a matter's Evidence tab in the dev server (`uv run dev`) and confirm tiles look identical to before.

- [ ] **Step 4: Format + lint**

```bash
uv run ruff format .
uv run ruff format --check .
uv run ruff check .
```

- [ ] **Step 5: Commit**

```bash
git add src/cvp/templates/_evidence_tile.html src/cvp/templates/_evidence_grid.html
git commit -m "refactor: extract _evidence_tile.html partial"
```

---

## Task 5: Single-file streaming upload endpoint

**Files:**
- Modify: `src/cvp/routers/evidence.py` (replace `upload_evidence`)
- Test: `tests/test_evidence_upload.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_evidence_upload.py`:

```python
"""Tests for POST /api/matters/{matter_id}/evidence (single-file endpoint)."""

import io
import json

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
from cvp.models_app_setting import AppSetting
from cvp.services import runtime_config

CONTRIB_ID = "contrib-1"
MATTER_ID = "matter-up"


@pytest.fixture(autouse=True)
def clear_cache():
    runtime_config._cache.clear()
    yield
    runtime_config._cache.clear()


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

    s.add(
        User(id=CONTRIB_ID, email="c@test.com", display_name="C", system_role="internal_user")
    )
    s.add(Matter(id=MATTER_ID, policyholder_name="Owner", loss_type="total_loss"))
    s.commit()
    yield s
    s.close()


@pytest.fixture
def client_contrib(db_session, monkeypatch, tmp_path):
    import inspect
    import cvp.routers.evidence as ev_router

    async def mock_contrib():
        return CurrentUser(
            id=CONTRIB_ID,
            email="c@test.com",
            system_role="internal_user",
            group_id=None,
            group_kind="internal",
        )

    def override_get_db():
        yield db_session

    dep = inspect.signature(ev_router.upload_evidence).parameters["user"].default.dependency
    app.dependency_overrides[dep] = mock_contrib
    app.dependency_overrides[get_db] = override_get_db

    monkeypatch.setattr(
        "cvp.routers.evidence.settings",
        type("S", (), {"upload_dir": str(tmp_path), "crop_dir": str(tmp_path)})(),
    )
    monkeypatch.setattr("cvp.routers.evidence.SessionLocal", lambda: db_session)

    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _jpeg_bytes(side: int = 10) -> bytes:
    buf = io.BytesIO()
    PILImage.new("RGB", (side, side), "white").save(buf, "JPEG")
    return buf.getvalue()


def test_upload_single_image_succeeds_and_returns_tile_fragment(client_contrib, db_session):
    payload = _jpeg_bytes()
    resp = client_contrib.post(
        f"/api/matters/{MATTER_ID}/evidence",
        files={"file": ("a.jpg", payload, "image/jpeg")},
    )
    assert resp.status_code == 200
    # Response is a single-tile HTML fragment, not the whole grid
    assert 'data-file-card' in resp.text
    assert 'id="evidence-grid"' not in resp.text

    rows = db_session.query(EvidenceFile).filter_by(matter_id=MATTER_ID).all()
    assert len(rows) == 1
    assert rows[0].filename == "a.jpg"
    assert rows[0].kind == "image"
    assert rows[0].size_bytes == len(payload)


def test_upload_rejects_file_exceeding_runtime_cap(client_contrib, db_session):
    # Set cap to 1 MB via DB override
    runtime_config.set_value(db_session, "evidence_upload_max_file_mb", 1, updated_by_user_id=None)
    big = b"\x00" * (2 * 1024 * 1024)  # 2 MB
    resp = client_contrib.post(
        f"/api/matters/{MATTER_ID}/evidence",
        files={"file": ("big.bin", big, "application/octet-stream")},
    )
    assert resp.status_code == 413
    assert db_session.query(EvidenceFile).filter_by(matter_id=MATTER_ID).count() == 0


def test_upload_requires_exactly_one_file_field(client_contrib):
    resp = client_contrib.post(f"/api/matters/{MATTER_ID}/evidence", data={})
    assert resp.status_code == 422  # FastAPI validation error
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_evidence_upload.py -v
```

Expected: FAIL — the current endpoint takes `files: list[UploadFile]`, not `file: UploadFile`; size cap is not enforced; response is the full grid.

- [ ] **Step 3: Replace the upload endpoint**

In `src/cvp/routers/evidence.py`, replace the existing `upload_evidence` function (lines 34–98) with:

```python
@router.post("/api/matters/{matter_id}/evidence", response_class=HTMLResponse)
async def upload_evidence(
    request: Request,
    matter_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile,
    user: CurrentUser = Depends(require_matter_role("contributor")),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Accept a single evidence file, stream it to disk, return its tile fragment.

    Streaming + per-file requests replace the previous batch endpoint so we
    don't hit Cloudflare's edge timeout on big drops. Concurrency is handled
    by the browser queue in app.js.
    """
    max_mb = runtime_config.get_int(db, "evidence_upload_max_file_mb")
    max_bytes = max_mb * 1024 * 1024
    hard_ceiling = 2 * max_bytes

    # Cheap pre-check: if Content-Length is present and clearly oversize, reject
    # before reading any bytes.
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > hard_ceiling:
        raise HTTPException(status_code=413, detail=f"File exceeds {max_mb} MB cap")

    upload_base = Path(settings.upload_dir).resolve()
    matter_dir = upload_base / matter_id
    matter_dir.mkdir(parents=True, exist_ok=True)

    raw_name = Path(file.filename or "file").name
    uid8 = str(uuid.uuid4())[:8]
    stored_name = f"{uid8}_{raw_name}"
    dest = matter_dir / stored_name

    # Stream to disk in 1 MB chunks, enforcing the size cap as we go.
    bytes_written = 0
    chunk_size = 1 << 20  # 1 MB
    try:
        with dest.open("wb") as out:
            while True:
                chunk = await file.read(chunk_size)
                if not chunk:
                    break
                bytes_written += len(chunk)
                if bytes_written > max_bytes:
                    out.close()
                    dest.unlink(missing_ok=True)
                    raise HTTPException(status_code=413, detail=f"File exceeds {max_mb} MB cap")
                await run_in_threadpool(out.write, chunk)
    except HTTPException:
        raise
    except Exception:
        dest.unlink(missing_ok=True)
        raise

    mime = file.content_type or (mimetypes.guess_type(raw_name)[0] or "")
    ef = EvidenceFile(
        matter_id=matter_id,
        filename=raw_name,
        stored_path=f"{matter_id}/{stored_name}",
        mime_type=mime,
        size_bytes=bytes_written,
        kind=_kind_from_mime(mime),
    )

    write_db = SessionLocal()
    try:
        write_db.add(ef)
        write_db.commit()
        write_db.refresh(ef)
    finally:
        write_db.close()

    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="evidence.create",
        resource_type="evidence",
        resource_id=ef.id,
        matter_id=matter_id,
        ip_address=get_client_ip(request),
    )

    return HTMLResponse(
        templates.get_template("_evidence_tile.html").render(f=ef, matter_id=matter_id)
    )
```

Also add these imports near the top of the file, alongside the existing ones:

```python
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from cvp.db import get_db
from cvp.services import runtime_config
```

(The existing `from cvp.db import SessionLocal` line stays — both `SessionLocal` and `get_db` are imported.)

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/test_evidence_upload.py -v
```

Expected: all 3 tests pass.

- [ ] **Step 5: Full test sweep + lint + format**

```bash
uv run ruff format .
uv run ruff format --check .
uv run ruff check .
uv run pytest -x
```

Expected: zero reformat, no lint errors, all tests pass — including the existing `test_evidence_remove_all.py`. If `test_evidence_remove_all` breaks because it imported old endpoint plumbing, leave the remove-all endpoint alone (it is unrelated) and only fix any incidental import error.

- [ ] **Step 6: Commit**

```bash
git add src/cvp/routers/evidence.py tests/test_evidence_upload.py
git commit -m "feat: single-file streaming evidence upload endpoint"
```

---

## Task 6: Browser upload queue with bounded concurrency

There are no JS unit tests in this repo, so this task uses manual verification rather than TDD. Keep the change surgical.

**Files:**
- Modify: `src/cvp/templates/_tab_evidence.html` (drop-zone `data-*`, progress strip, remove form `hx-post`)
- Modify: `src/cvp/static/app.js` (replace `initEvidenceUpload` with `EvidenceUploadQueue`)

- [ ] **Step 1: Update the evidence tab template**

Replace lines 1–19 of `src/cvp/templates/_tab_evidence.html` (the upload zone block) with:

```html
<div class="space-y-4">

  <!-- Upload zone (queue-driven; no hx-post here — JS handles requests) -->
  <div id="evidence-form">
    <div id="drop-zone"
         data-matter-id="{{ matter.id }}"
         data-csrf-token="{{ request.cookies.get('cvp_csrf', '') }}"
         data-evidence-upload-concurrency="{{ evidence_upload_concurrency }}"
         data-evidence-upload-max-file-mb="{{ evidence_upload_max_file_mb }}"
         data-evidence-upload-max-batch-count="{{ evidence_upload_max_batch_count }}"
         class="flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-gray-300 bg-white px-6 py-10 text-center transition-colors hover:border-indigo-400 cursor-pointer">
      <svg class="mx-auto mb-3 h-10 w-10 text-gray-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5"
              d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5"/>
      </svg>
      <p class="text-sm font-medium text-gray-600">Drop files here or <span class="text-indigo-600">browse</span></p>
      <p class="mt-1 text-xs text-gray-400">Photos, PDFs, videos — up to {{ evidence_upload_max_file_mb }} MB each, {{ evidence_upload_max_batch_count }} per drop</p>
      <input id="evidence-input" name="files" type="file" multiple class="hidden">
    </div>
    <div id="evidence-upload-progress" class="mt-2 space-y-1"></div>
  </div>
```

(Keep the rest of the file unchanged.)

- [ ] **Step 2: Inject the three runtime-config values where the tab is rendered**

The Evidence tab template is included in `matter_detail.html` (or whatever renders the matter page). Find the route handler that renders the matter page (search `_tab_evidence` or `matter_detail.html` in `src/cvp/routers/matters.py`) and add the three values to the template context.

```bash
grep -rn "matter_detail.html\|_tab_evidence" src/cvp/routers/
```

Open the matched router function. Where the context dict is built, import the service and inject three keys:

```python
from cvp.services import runtime_config

# inside the handler, after you already have a `db` session:
context["evidence_upload_concurrency"] = runtime_config.get_int(db, "evidence_upload_concurrency")
context["evidence_upload_max_file_mb"] = runtime_config.get_int(db, "evidence_upload_max_file_mb")
context["evidence_upload_max_batch_count"] = runtime_config.get_int(db, "evidence_upload_max_batch_count")
```

(Adapt to however that handler constructs its context — `TemplateResponse(..., {...})` or a local dict before the return.)

- [ ] **Step 3: Replace the JS upload module**

In `src/cvp/static/app.js`, replace the entire `initEvidenceUpload` function (lines 154–185, including the `document.addEventListener('DOMContentLoaded', initEvidenceUpload);` line) with this self-contained module. Keep the surrounding `// ── ... ──` separator comment for style consistency.

```javascript
// ── Evidence drag-drop upload ─────────────────────────────────────────────
// Per-file uploads with bounded concurrency. Caps come from data-* attrs on
// the drop zone (server-rendered from runtime_config).
function initEvidenceUpload() {
    var zone = document.getElementById('drop-zone');
    var input = document.getElementById('evidence-input');
    var progress = document.getElementById('evidence-upload-progress');
    var grid = document.getElementById('evidence-grid');
    if (!zone || !input) return;

    var matterId = zone.dataset.matterId;
    var csrf = zone.dataset.csrfToken || '';
    var concurrency = Math.max(1, parseInt(zone.dataset.evidenceUploadConcurrency, 10) || 4);
    var maxFileBytes = (parseInt(zone.dataset.evidenceUploadMaxFileMb, 10) || 10) * 1024 * 1024;
    var maxBatch = parseInt(zone.dataset.evidenceUploadMaxBatchCount, 10) || 500;

    var queue = [];
    var inFlight = 0;
    var rowId = 0;

    function newRow(name, state, message) {
        rowId += 1;
        var div = document.createElement('div');
        div.id = 'upload-row-' + rowId;
        div.className = 'flex items-center gap-2 text-xs';
        div.innerHTML =
            '<span class="truncate flex-1">' + name + '</span>' +
            '<span data-state class="' + stateClass(state) + '">' + (message || state) + '</span>';
        progress.appendChild(div);
        return div;
    }

    function stateClass(state) {
        if (state === 'done') return 'text-green-600';
        if (state === 'failed') return 'text-red-600 cursor-pointer underline';
        if (state === 'uploading') return 'text-blue-600';
        return 'text-gray-400';
    }

    function setRowState(row, state, message) {
        var badge = row.querySelector('[data-state]');
        badge.className = stateClass(state);
        badge.textContent = message || state;
        if (state === 'done') {
            setTimeout(function () { row.remove(); }, 2000);
        }
    }

    function enqueueDrop(fileList) {
        var files = Array.from(fileList || []);
        if (files.length === 0) return;
        if (files.length > maxBatch) {
            alert('Limit is ' + maxBatch + ' files per drop. Try smaller batches.');
            return;
        }
        files.forEach(function (f) {
            if (f.size > maxFileBytes) {
                newRow(f.name, 'failed', 'Too large (max ' + (maxFileBytes / 1024 / 1024) + ' MB)');
                return;
            }
            var row = newRow(f.name, 'queued', 'Queued');
            queue.push({ file: f, row: row });
        });
        pump();
    }

    function pump() {
        while (inFlight < concurrency && queue.length > 0) {
            var job = queue.shift();
            startJob(job);
        }
        if (inFlight === 0 && queue.length === 0) {
            // Queue fully drained — refresh grid chrome (counts, banners) once.
            htmx.ajax('GET', '/api/matters/' + matterId + '/evidence-grid', '#evidence-grid');
        }
    }

    function startJob(job) {
        inFlight += 1;
        setRowState(job.row, 'uploading', 'Uploading…');
        var form = new FormData();
        form.append('file', job.file, job.file.name);
        var xhr = new XMLHttpRequest();
        xhr.open('POST', '/api/matters/' + matterId + '/evidence');
        if (csrf) xhr.setRequestHeader('X-CSRF-Token', csrf);
        xhr.onload = function () {
            inFlight -= 1;
            if (xhr.status >= 200 && xhr.status < 300) {
                if (grid && xhr.responseText) {
                    grid.insertAdjacentHTML('beforeend', xhr.responseText);
                    htmx.process(grid);
                }
                setRowState(job.row, 'done', '✓');
            } else {
                var msg = (xhr.status === 413) ? 'Too large' : ('Failed (' + xhr.status + ')');
                setRowState(job.row, 'failed', msg + ' — retry');
                job.row.addEventListener('click', function retry() {
                    job.row.removeEventListener('click', retry);
                    setRowState(job.row, 'queued', 'Queued');
                    queue.push(job);
                    pump();
                });
            }
            pump();
        };
        xhr.onerror = function () {
            inFlight -= 1;
            setRowState(job.row, 'failed', 'Network — retry');
            pump();
        };
        xhr.send(form);
    }

    zone.addEventListener('click', function () { input.click(); });
    input.addEventListener('change', function () {
        enqueueDrop(input.files);
        input.value = ''; // allow re-selecting same files
    });
    zone.addEventListener('dragover', function (e) {
        e.preventDefault();
        zone.classList.add('border-indigo-500', 'bg-indigo-50');
    });
    zone.addEventListener('dragleave', function () {
        zone.classList.remove('border-indigo-500', 'bg-indigo-50');
    });
    zone.addEventListener('drop', function (e) {
        e.preventDefault();
        zone.classList.remove('border-indigo-500', 'bg-indigo-50');
        enqueueDrop(e.dataTransfer.files);
    });

    window.addEventListener('beforeunload', function (e) {
        if (inFlight > 0 || queue.length > 0) {
            e.preventDefault();
            e.returnValue = '';
        }
    });
}

document.addEventListener('DOMContentLoaded', initEvidenceUpload);
```

- [ ] **Step 4: Add a grid-refresh endpoint**

The JS calls `GET /api/matters/{matter_id}/evidence-grid` to refresh chrome (image counts, banners) after the queue drains. Add this to `src/cvp/routers/evidence.py`:

```python
@router.get("/api/matters/{matter_id}/evidence-grid", response_class=HTMLResponse)
def get_evidence_grid(
    request: Request,
    matter_id: str,
    user: CurrentUser = Depends(require_matter_role("viewer")),
) -> HTMLResponse:
    db = SessionLocal()
    try:
        evidence_files = (
            db.query(EvidenceFile)
            .filter(EvidenceFile.matter_id == matter_id)
            .order_by(EvidenceFile.created_at.desc())
            .all()
        )
    finally:
        db.close()
    return HTMLResponse(
        templates.get_template("_evidence_grid.html").render(
            evidence_files=evidence_files, matter_id=matter_id
        )
    )
```

(Companion spec 2 will replace this with a paginated version; for now it returns the full grid, matching prior behavior at queue-drain.)

- [ ] **Step 5: Manual QA — happy path**

```bash
uv run dev
```

In the browser:
1. Open a matter's Evidence tab. Confirm the drop zone shows "up to 10 MB each, 500 per drop".
2. Drop 5 small images. Confirm each shows "Queued" → "Uploading…" → "✓" briefly, tiles appear in the grid as each completes, and progress rows disappear after success.
3. Drop a file > 10 MB. Confirm the row shows "Too large" and the file is rejected.

- [ ] **Step 6: Manual QA — concurrency + caps**

1. In `/admin/system/runtime-config`, set `evidence_upload_concurrency` to 2. Refresh the matter page. Drop 8 files. Confirm only 2 are in flight at a time (browser DevTools → Network tab).
2. Set `evidence_upload_max_file_mb` to 1. Refresh. Try to drop a 2 MB file. Confirm rejection.
3. Set `evidence_upload_max_batch_count` to 3. Refresh. Try to drop 5 files. Confirm "Limit is 3 files per drop" alert and no uploads start.

- [ ] **Step 7: Lint + format + full test sweep**

```bash
uv run ruff format .
uv run ruff format --check .
uv run ruff check .
uv run pytest -x
```

Expected: zero reformat, no lint errors, all tests pass.

- [ ] **Step 8: Commit**

```bash
git add src/cvp/templates/_tab_evidence.html src/cvp/static/app.js src/cvp/routers/evidence.py src/cvp/routers/matters.py
git commit -m "feat: per-file evidence upload queue with bounded concurrency"
```

(If `matters.py` was not the file that needed the context injection, substitute the actual file path you edited in Task 6 Step 2.)

---

## Task 7: Verify with a heavy real-world drop

This is the original failure case the work was scoped to fix.

- [ ] **Step 1: Generate 53 synthetic ~1 MB JPEGs**

```bash
mkdir -p /tmp/cvp-upload-test && cd /tmp/cvp-upload-test
for i in $(seq 1 53); do
  uv run python -c "from PIL import Image; from io import BytesIO; import random; \
    img = Image.new('RGB', (2000, 1500), (random.randint(0,255), random.randint(0,255), random.randint(0,255))); \
    img.save(open('img_$(printf %02d $i).jpg','wb'), 'JPEG', quality=90)"
done
ls -lh | head
```

Expected: 53 files, each ~800 KB – 1.2 MB.

- [ ] **Step 2: Upload via the dev server**

With `uv run dev` running, open a matter's Evidence tab and drop all 53 files. Watch the network panel.

Expected:
- 53 separate POST requests, max 4 concurrent.
- All return 200 with single-tile HTML.
- No 5xx, no timeouts.
- Progress strip rows clear within ~2 seconds of each tile arriving.
- After the last one, one `GET /api/matters/{id}/evidence-grid` fires to refresh chrome.

- [ ] **Step 3: Sanity check DB rows + on-disk files**

```bash
uv run python -c "from cvp.db import SessionLocal; from cvp.models import EvidenceFile; \
  s = SessionLocal(); \
  print(s.query(EvidenceFile).count())"
ls data/uploads/<matter-id>/ | wc -l
```

Expected: count matches what you uploaded.

- [ ] **Step 4: Commit any minor fixes from the QA pass**

If anything needed tweaking in this pass, commit it:

```bash
git add -A
git commit -m "fix: <whatever you tweaked from manual QA>"
```

If nothing needed tweaking, skip this step.

---

## Task 8: Push branch + open PR

- [ ] **Step 1: Push**

```bash
git push -u origin spec/scalable-evidence-upload
```

- [ ] **Step 2: Open PR**

```bash
gh pr create --title "feat: scalable evidence upload (per-file, bounded concurrency)" --body "$(cat <<'EOF'
## Summary
- Replaces the all-in-one multipart evidence upload (which hit a Cloudflare 524 on a 53-file drop) with single-file streaming uploads driven by a browser-side concurrency queue (default 4 in flight).
- Adds an `app_setting` table and a `/admin/system/runtime-config` system-admin page so concurrency, per-file size cap, and per-batch count cap can be tuned without redeploy.
- Server streams uploads to disk in 1 MB chunks via `run_in_threadpool`, enforces the size cap mid-stream, and returns one tile fragment instead of re-rendering the entire grid.

Spec: `docs/superpowers/specs/2026-06-09-scalable-evidence-upload-design.md`

## Test plan
- [ ] `uv run pytest -x` green
- [ ] `uv run ruff format --check . && uv run ruff check .` clean
- [ ] Manual: drop 53 × ~1 MB JPEGs — all 53 succeed, ≤4 concurrent
- [ ] Manual: drop a single >10 MB file — rejected with "Too large" row
- [ ] Manual: drop >500 files — single rejection alert, no uploads start
- [ ] Manual: change concurrency to 2 in /admin/system/runtime-config — verified in DevTools Network
EOF
)"
```

- [ ] **Step 3: Return PR URL**

Print the PR URL so the user can open it.

---

## Plan self-review

**Spec coverage check:**
- ✅ Runtime config (table + service + admin + bounds + cache TTL) → Tasks 1, 2, 3
- ✅ Single-file streaming endpoint with size cap → Task 5
- ✅ Per-file HTMX tile response (new `_evidence_tile.html`) → Tasks 4, 5
- ✅ Browser queue with bounded concurrency, per-file size + batch caps → Task 6
- ✅ One audit log per file (natural fallout of single-file endpoint) → Task 5
- ✅ Manual heavy-batch verification → Task 7
- ✅ Single PR rollout → Task 8

**Placeholder scan:** no TBDs, no "add appropriate error handling", all code blocks complete.

**Type / name consistency check:** `AppSetting` consistent across model, service, router, tests. `runtime_config.get_int` and `set_value` consistent across service, tests, admin router. `evidence_upload_concurrency` / `evidence_upload_max_file_mb` / `evidence_upload_max_batch_count` consistent across config, service, admin, template, JS.

**One known soft spot:** Task 6 Step 2 ("find the matter detail handler and inject context") is a search step rather than a direct file:line edit, because the templating path in this repo wasn't fully mapped during planning. The grep is given; the engineer must follow it. If multiple matches exist, prefer the handler whose template includes `_tab_evidence.html`.
