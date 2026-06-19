# Live Items List Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After a vision scan or region rescan creates draft items, surface them in the Items tab via an opt-in "N new items added — View them" banner, with no manual page refresh.

**Architecture:** Reuse the two existing scan pollers (full-scan HTMX poll on the Evidence tab; region-scan JSON poll in `crop-editor.js`). Both dispatch one document-level `cvp:items-added` CustomEvent on completion. A delegated handler in `app.js` shows a banner on the Items tab; clicking "View them" does a dedup-safe page-1 refresh of `#items-tbody` (via the existing `items-rows` endpoint) plus a totals refresh (via one new `items-summary` endpoint), then scrolls the list to the bottom where new items sort.

**Tech Stack:** FastAPI, Jinja2, HTMX (CDN), vanilla JS (`app.js`, `crop-editor.js`), SQLAlchemy 2.x, pytest. No new dependencies.

## Global Constraints

- Currency stored/computed as **integer cents**; format to dollars only at display/export. (verbatim from domain rule 1)
- **Never use inline JS event handlers** (`onclick=` etc.) — CSP `script-src` has no `unsafe-inline`. Wire interactivity via `data-*` attributes + delegated `document.addEventListener('click', ...)` in `app.js`.
- Type hints everywhere; modern syntax (`X | None`, `list[str]`).
- Pure functions stay DB-free; this plan adds DB-reading helpers in the router layer, not in `depreciation.py`.
- Run `uv run ruff format .` then verify `uv run ruff format --check .` shows zero files before every commit; line length 100. CI enforces this.
- One router file per resource, < 200 lines where practical.
- Tests live in `tests/` mirroring `src/cvp/`. Routers get one happy-path integration test each.
- Do not change Xactimate CSV column names, depreciation methodology, list ordering, or pagination mechanism.
- Branch: `feat/live-items-list` (already created; the spec commit is on it). Never commit to `main`.

---

## File Structure

- `src/cvp/routers/items.py` — add `compute_items_totals()` helper + `GET /api/matters/{matter_id}/items-summary` endpoint.
- `src/cvp/routers/matters.py` — replace inline totals computation with the shared helper.
- `src/cvp/templates/_items_summary.html` — **new** summary fragment (self-refreshing on `item-created`).
- `src/cvp/templates/_tab_items.html` — replace inline summary block with the fragment include; add `#items-new-banner`.
- `src/cvp/templates/_scan_progress.html` — add terminal-state data attributes for the JS completion contract.
- `src/cvp/static/app.js` — scan-completion detector, `cvp:items-added` banner handler, `data-view-new-items` click handler.
- `src/cvp/static/crop-editor.js` — dispatch `cvp:items-added` on region-job completion.
- `tests/test_items_summary.py` — **new** tests for the helper + endpoint.
- `tests/test_scan_progress_template.py` — **new** render test for the completion contract attributes.

---

## Task 1: Shared items-totals helper

**Files:**
- Modify: `src/cvp/routers/items.py` (add `compute_items_totals`; refactor nothing else here)
- Modify: `src/cvp/routers/matters.py:140-157` (use the helper)
- Test: `tests/test_items_summary.py` (helper tests; endpoint added in Task 2)

**Interfaces:**
- Produces: `compute_items_totals(matter_id: str, db: Session) -> dict[str, int]` returning keys `items_total_count`, `items_confirmed_count`, `items_rcv_total_cents`, `items_acv_total_cents`, `unconfirmed_count`, `missing_price_count`. Totals count only rows where `confirmed and not excluded`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_items_summary.py`:

```python
"""Tests for the items-totals helper and the items-summary endpoint."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cvp.models_vision  # noqa: F401
from cvp.models import Base, Category, Item, Matter
from cvp.routers.items import compute_items_totals

MATTER_ID = "m-totals"


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
    s.add(Matter(id=MATTER_ID, policyholder_name="P", loss_type="total_loss"))
    s.add(Category(id=1, name="C", useful_life_years=5, acv_floor_pct=0.2))
    s.commit()
    yield s
    s.close()


def _add_item(db, *, line, confirmed, excluded, rcv_total, acv_total, rcv_unit):
    db.add(
        Item(
            matter_id=MATTER_ID,
            category_id=1,
            line_number=line,
            description=f"item {line}",
            quantity=1,
            age_years=0.0,
            condition="average",
            rcv_unit_cents=rcv_unit,
            rcv_total_cents=rcv_total,
            acv_total_cents=acv_total,
            confirmed=confirmed,
            excluded=excluded,
        )
    )


def test_totals_count_only_confirmed_not_excluded(db_session):
    # confirmed + not excluded -> counted
    _add_item(db_session, line=1, confirmed=True, excluded=False,
              rcv_total=10000, acv_total=8000, rcv_unit=10000)
    # confirmed but excluded -> not counted in money totals
    _add_item(db_session, line=2, confirmed=True, excluded=True,
              rcv_total=5000, acv_total=4000, rcv_unit=5000)
    # unconfirmed (draft from a scan) -> not counted in money totals
    _add_item(db_session, line=3, confirmed=False, excluded=False,
              rcv_total=9999, acv_total=9999, rcv_unit=0)
    db_session.commit()

    totals = compute_items_totals(MATTER_ID, db_session)

    assert totals["items_total_count"] == 3
    assert totals["items_confirmed_count"] == 1
    assert totals["items_rcv_total_cents"] == 10000
    assert totals["items_acv_total_cents"] == 8000
    assert totals["unconfirmed_count"] == 1
    assert totals["missing_price_count"] == 0


def test_missing_price_counts_confirmed_zero_rcv(db_session):
    _add_item(db_session, line=1, confirmed=True, excluded=False,
              rcv_total=0, acv_total=0, rcv_unit=0)
    db_session.commit()
    totals = compute_items_totals(MATTER_ID, db_session)
    assert totals["missing_price_count"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_items_summary.py -v`
Expected: FAIL with `ImportError: cannot import name 'compute_items_totals'`.

- [ ] **Step 3: Add the helper to `src/cvp/routers/items.py`**

Insert directly after the `_get_context` function (around line 45, before `_compute_and_set_totals`):

```python
def compute_items_totals(matter_id: str, db) -> dict[str, int]:
    """Money + count totals for a matter's items.

    Money totals (RCV/ACV) count only rows that are confirmed and not
    excluded. Counts are integer cents — never floats.
    """
    rows = (
        db.query(
            Item.confirmed,
            Item.excluded,
            Item.rcv_total_cents,
            Item.acv_total_cents,
            Item.rcv_unit_cents,
        )
        .filter(Item.matter_id == matter_id)
        .all()
    )
    confirmed_rows = [r for r in rows if r.confirmed and not r.excluded]
    return {
        "items_total_count": len(rows),
        "items_confirmed_count": len(confirmed_rows),
        "items_rcv_total_cents": sum(r.rcv_total_cents for r in confirmed_rows),
        "items_acv_total_cents": sum(r.acv_total_cents for r in confirmed_rows),
        "unconfirmed_count": sum(1 for r in rows if not r.confirmed),
        "missing_price_count": sum(1 for r in confirmed_rows if r.rcv_unit_cents == 0),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_items_summary.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Refactor `matters.py` to use the helper**

In `src/cvp/routers/matters.py`, add to the existing import of the items router helpers near the top (find the existing `from cvp.routers...` / `from cvp.services...` import block and add):

```python
from cvp.routers.items import compute_items_totals
```

Then replace lines 140-157 (the `items_for_totals = (...)` block through `items_confirmed_count = len(confirmed_rows)`) with:

```python
        _totals = compute_items_totals(matter_id, db)
        total_rcv_cents = _totals["items_rcv_total_cents"]
        total_acv_cents = _totals["items_acv_total_cents"]
        unconfirmed_count = _totals["unconfirmed_count"]
        missing_price_count = _totals["missing_price_count"]
        items_total_count = _totals["items_total_count"]
        items_confirmed_count = _totals["items_confirmed_count"]
```

(The surrounding `db.query(Item)...` pagination block at lines 159+ and the context dict at 254+ are unchanged — they already read these local names.)

- [ ] **Step 6: Verify no circular import and full suite still passes**

Run: `uv run pytest tests/test_items_summary.py tests/test_items_pagination.py -v`
Expected: PASS. (Confirms `matters.py` importing from `items.py` does not create a circular import — `items.py` does not import `matters.py`.)

- [ ] **Step 7: Format and commit**

```bash
uv run ruff format .
uv run ruff format --check .
git add src/cvp/routers/items.py src/cvp/routers/matters.py tests/test_items_summary.py
git commit -m "$(cat <<'EOF'
feat: shared items-totals helper; reuse in matter detail

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: items-summary endpoint + fragment + tab wiring

**Files:**
- Modify: `src/cvp/routers/items.py` (add `get_items_summary` endpoint)
- Create: `src/cvp/templates/_items_summary.html`
- Modify: `src/cvp/templates/_tab_items.html:101-107` (replace inline summary with the fragment include)
- Test: `tests/test_items_summary.py` (extend)

**Interfaces:**
- Consumes: `compute_items_totals` (Task 1).
- Produces: `GET /api/matters/{matter_id}/items-summary` → HTML fragment rooted at `<div id="items-summary">`; `viewer` role. Renders the Confirmed/RCV/ACV block and self-refreshes on the `item-created` body event.

- [ ] **Step 1: Write the failing endpoint test**

Append to `tests/test_items_summary.py`:

```python
import inspect

from fastapi.testclient import TestClient

from cvp.db import get_db
from cvp.dependencies import CurrentUser
from cvp.main import app
from cvp.models_auth import User
from cvp.services import access_cache

VIEWER_ID = "v-totals"


@pytest.fixture(autouse=True)
def _clear_access_cache():
    access_cache._cache.clear()
    yield
    access_cache._cache.clear()


@pytest.fixture
def client(db_session, monkeypatch):
    db_session.add(
        User(id=VIEWER_ID, email="v@t.com", display_name="V", system_role="internal_user")
    )
    db_session.commit()

    import cvp.routers.items as items_router

    async def mock_viewer():
        return CurrentUser(
            id=VIEWER_ID,
            email="v@t.com",
            system_role="internal_user",
            group_id=None,
            group_kind="internal",
        )

    def override_get_db():
        yield db_session

    dep = inspect.signature(items_router.get_items_summary).parameters["user"].default.dependency
    app.dependency_overrides[dep] = mock_viewer
    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr("cvp.routers.items.SessionLocal", lambda: db_session)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_items_summary_renders_totals(client, db_session):
    _add_item(db_session, line=1, confirmed=True, excluded=False,
              rcv_total=10000, acv_total=8000, rcv_unit=10000)
    db_session.commit()
    resp = client.get(f"/api/matters/{MATTER_ID}/items-summary")
    assert resp.status_code == 200
    body = resp.text
    assert 'id="items-summary"' in body
    assert "$100.00" in body  # RCV total
    assert "$80.00" in body   # ACV total
    assert 'hx-trigger="item-created from:body"' in body


def test_items_summary_empty_matter_renders_no_totals_row(client):
    resp = client.get(f"/api/matters/{MATTER_ID}/items-summary")
    assert resp.status_code == 200
    assert 'id="items-summary"' in resp.text
    assert "RCV total" not in resp.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_items_summary.py -v`
Expected: FAIL — `get_items_summary` has no attribute (AttributeError in fixture) / route 404.

- [ ] **Step 3: Create the fragment `src/cvp/templates/_items_summary.html`**

```html
<div id="items-summary"
     hx-get="/api/matters/{{ matter_id }}/items-summary"
     hx-trigger="item-created from:body"
     hx-swap="outerHTML">
  {% if items_total_count and items_total_count > 0 %}
  <div class="flex justify-end gap-6 text-sm text-gray-600">
    <span>Confirmed: <strong class="text-gray-900">{{ items_confirmed_count }}</strong> of {{ items_total_count }}</span>
    <span>RCV total: <strong class="font-mono text-gray-900">${{ "%.2f" % (items_rcv_total_cents / 100) }}</strong></span>
    <span>ACV total: <strong class="font-mono text-gray-900">${{ "%.2f" % (items_acv_total_cents / 100) }}</strong></span>
  </div>
  {% endif %}
</div>
```

- [ ] **Step 4: Add the endpoint to `src/cvp/routers/items.py`**

Insert immediately after `get_items_rows` (after its `return HTMLResponse(...)` block, ~line 150):

```python
@router.get("/api/matters/{matter_id}/items-summary", response_class=HTMLResponse)
def get_items_summary(
    matter_id: str,
    user: CurrentUser = Depends(require_matter_role("viewer")),
) -> HTMLResponse:
    """Render the Confirmed / RCV total / ACV total summary block."""
    db = SessionLocal()
    try:
        totals = compute_items_totals(matter_id, db)
    finally:
        db.close()
    return HTMLResponse(
        templates.get_template("_items_summary.html").render(matter_id=matter_id, **totals)
    )
```

- [ ] **Step 5: Wire the fragment into `_tab_items.html`**

Replace lines 101-107 (the `{% if items_total_count ... %}` ... `{% endif %}` summary block) with:

```html
  {% set matter_id = matter.id %}
  {% include "_items_summary.html" %}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_items_summary.py -v`
Expected: PASS (all tests).

- [ ] **Step 7: Verify the matter detail page still renders the summary**

Run: `uv run pytest tests/test_items_template.py -v`
Expected: PASS. (If this test asserts on the old inline summary markup, update its assertions to match the fragment — the Confirmed/RCV/ACV text is unchanged, only the wrapping `<div id="items-summary">` is new.)

- [ ] **Step 8: Format and commit**

```bash
uv run ruff format .
uv run ruff format --check .
git add src/cvp/routers/items.py src/cvp/templates/_items_summary.html src/cvp/templates/_tab_items.html tests/test_items_summary.py
git commit -m "$(cat <<'EOF'
feat: items-summary fragment endpoint, self-refreshing on item-created

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Scan-progress completion contract (data attributes)

**Files:**
- Modify: `src/cvp/templates/_scan_progress.html:1-9`
- Test: `tests/test_scan_progress_template.py` (new)

**Interfaces:**
- Produces: when `status` is `done` or `error`, the `#scan-status` root carries `data-scan-state`, `data-job-id`, `data-matter-id`, `data-items-created`. `app.js` (Task 4) reads these to dispatch `cvp:items-added`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_scan_progress_template.py`:

```python
"""The full-scan progress fragment must expose a completion contract for app.js."""

from cvp.routers.vision import templates


def _render(**kw):
    base = dict(
        job_id="job-1",
        matter_id="m-1",
        status="done",
        progress=3,
        total=3,
        items_created=5,
        errors=[],
    )
    base.update(kw)
    return templates.get_template("_scan_progress.html").render(**base)


def test_done_state_exposes_completion_data_attrs():
    html = _render(status="done")
    assert 'data-scan-state="done"' in html
    assert 'data-job-id="job-1"' in html
    assert 'data-matter-id="m-1"' in html
    assert 'data-items-created="5"' in html


def test_error_state_exposes_completion_data_attrs():
    html = _render(status="error", items_created=2)
    assert 'data-scan-state="error"' in html
    assert 'data-items-created="2"' in html


def test_running_state_has_no_completion_attrs():
    html = _render(status="running", progress=1)
    assert "data-scan-state" not in html
    assert 'hx-trigger="every 2s"' in html  # still polling
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_scan_progress_template.py -v`
Expected: FAIL — `data-scan-state` not present.

- [ ] **Step 3: Add the data attributes**

In `src/cvp/templates/_scan_progress.html`, change the opening `#scan-status` div (lines 2-9) to add the terminal-state attributes. Replace:

```html
<div id="scan-status"
  {% if status == "running" %}
  hx-get="/api/matters/{{ matter_id }}/vision-scan/{{ job_id }}"
  hx-trigger="every 2s"
  hx-target="#scan-status"
  hx-swap="outerHTML"
  {% endif %}
  class="rounded-lg border {% if status == 'error' %}border-red-200 bg-red-50{% elif status == 'done' %}border-green-200 bg-green-50{% else %}border-indigo-200 bg-indigo-50{% endif %} p-4 space-y-2">
```

with:

```html
<div id="scan-status"
  {% if status == "running" %}
  hx-get="/api/matters/{{ matter_id }}/vision-scan/{{ job_id }}"
  hx-trigger="every 2s"
  hx-target="#scan-status"
  hx-swap="outerHTML"
  {% else %}
  data-scan-state="{{ status }}"
  data-job-id="{{ job_id }}"
  data-matter-id="{{ matter_id }}"
  data-items-created="{{ items_created }}"
  {% endif %}
  class="rounded-lg border {% if status == 'error' %}border-red-200 bg-red-50{% elif status == 'done' %}border-green-200 bg-green-50{% else %}border-indigo-200 bg-indigo-50{% endif %} p-4 space-y-2">
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_scan_progress_template.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Format and commit**

```bash
uv run ruff format .
uv run ruff format --check .
git add src/cvp/templates/_scan_progress.html tests/test_scan_progress_template.py
git commit -m "$(cat <<'EOF'
feat: expose scan-completion data attrs on scan-progress fragment

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Items-tab banner + app.js handlers

**Files:**
- Modify: `src/cvp/templates/_tab_items.html` (add `#items-new-banner` above the add-item form)
- Modify: `src/cvp/static/app.js` (scan-completion detector; `cvp:items-added` handler; `data-view-new-items` click handler)

**Interfaces:**
- Consumes: `data-scan-state`/`data-job-id`/`data-matter-id`/`data-items-created` (Task 3); `GET items-rows` (existing) and `GET items-summary` (Task 2).
- Produces: `cvp:items-added` CustomEvent contract `{ detail: { matterId, jobId, count } }` (also consumed by Task 5).

No JS unit-test harness exists in this repo; this task is verified by running the app (see Verification).

- [ ] **Step 1: Add the banner markup to `_tab_items.html`**

Immediately after the opening `<div class="space-y-4">` (line 1), before the `<!-- Add item form -->` comment, insert:

```html
  <!-- New-items banner: shown by app.js when a scan/region rescan adds items -->
  <div id="items-new-banner" data-matter-id="{{ matter.id }}"
       class="hidden flex items-center justify-between gap-3 rounded-lg border border-indigo-200 bg-indigo-50 px-4 py-2 text-sm text-indigo-800">
    <span><span aria-hidden="true">✦</span> <span data-new-items-label>New items added</span></span>
    <button type="button" data-view-new-items
            class="rounded-md bg-indigo-600 px-3 py-1 text-xs font-semibold text-white hover:bg-indigo-500">
      View them →
    </button>
  </div>
```

- [ ] **Step 2: Add the scan-completion detector + banner logic to `app.js`**

Append this block to the end of `src/cvp/static/app.js`:

```javascript
// ---- Live items list: surface scan / region-rescan results -------------
// Both the full-scan HTMX poll and the region-scan JSON poll converge on a
// single document event: cvp:items-added {detail:{matterId, jobId, count}}.
(function () {
  var handledScanJobs = new Set();
  var newItemsCount = 0;

  // Detect full-scan completion from the swapped scan-progress fragment.
  document.addEventListener('htmx:afterSwap', function (e) {
    var root = e.target;
    if (!root || !root.querySelector) return;
    var el = (root.matches && root.matches('[data-scan-state]'))
      ? root
      : root.querySelector('[data-scan-state]');
    if (!el) return;
    var state = el.dataset.scanState;
    if (state !== 'done' && state !== 'error') return;
    var jobId = el.dataset.jobId;
    if (!jobId || handledScanJobs.has(jobId)) return;
    handledScanJobs.add(jobId);
    var count = parseInt(el.dataset.itemsCreated, 10) || 0;
    if (count <= 0) return;
    document.dispatchEvent(new CustomEvent('cvp:items-added', {
      detail: { matterId: el.dataset.matterId, jobId: jobId, count: count }
    }));
  });

  // Accumulate count + reveal the banner.
  document.addEventListener('cvp:items-added', function (e) {
    var detail = e.detail || {};
    newItemsCount += (detail.count || 0);
    var banner = document.getElementById('items-new-banner');
    if (!banner) return;
    if (detail.matterId) banner.dataset.matterId = detail.matterId;
    var label = banner.querySelector('[data-new-items-label]');
    if (label) {
      label.textContent =
        newItemsCount + ' new item' + (newItemsCount === 1 ? '' : 's') + ' added';
    }
    banner.classList.remove('hidden');
  });

  // "View them": dedup-safe page-1 refresh + totals refresh + scroll to bottom.
  document.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-view-new-items]');
    if (!btn || !window.htmx) return;
    var banner = document.getElementById('items-new-banner');
    var matterId = banner ? banner.dataset.matterId : null;
    if (!matterId) return;

    htmx.ajax('GET', '/api/matters/' + matterId + '/items-rows',
      { target: '#items-tbody', swap: 'innerHTML' });
    htmx.ajax('GET', '/api/matters/' + matterId + '/items-summary',
      { target: '#items-summary', swap: 'outerHTML' });

    newItemsCount = 0;
    if (banner) banner.classList.add('hidden');

    var onSettle = function (ev) {
      if (ev.detail && ev.detail.target && ev.detail.target.id === 'items-tbody') {
        document.removeEventListener('htmx:afterSettle', onSettle);
        var tbody = document.getElementById('items-tbody');
        if (tbody) tbody.scrollIntoView({ block: 'end', behavior: 'smooth' });
      }
    };
    document.addEventListener('htmx:afterSettle', onSettle);
  });
})();
```

- [ ] **Step 3: Run the full test suite (no regressions)**

Run: `uv run pytest -q`
Expected: PASS (the JS change is untested here but must not break Python tests; templates still render).

- [ ] **Step 4: Format and commit**

```bash
uv run ruff format .
uv run ruff format --check .
git add src/cvp/templates/_tab_items.html src/cvp/static/app.js
git commit -m "$(cat <<'EOF'
feat: new-items banner on items tab, driven by cvp:items-added

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Dispatch cvp:items-added from region rescan

**Files:**
- Modify: `src/cvp/static/crop-editor.js:404-433` (`pollRegionJob`)

**Interfaces:**
- Consumes: `matterId`, `jobId` (function params) and `d.items_created` (poll response).
- Produces: `cvp:items-added` event on completion (same contract as Task 4).

Verified by running the app (see Verification).

- [ ] **Step 1: Add dispatch on the done branch**

In `src/cvp/static/crop-editor.js`, inside `pollRegionJob`, locate the success branch:

```javascript
            regionStatusEl.textContent = 'Done — ' + d.items_created + ' item(s) created.';
            if (window.htmx) {
```

Insert the dispatch between those two lines so it reads:

```javascript
            regionStatusEl.textContent = 'Done — ' + d.items_created + ' item(s) created.';
            if (d.items_created > 0) {
              document.dispatchEvent(new CustomEvent('cvp:items-added', {
                detail: { matterId: matterId, jobId: jobId, count: d.items_created }
              }));
            }
            if (window.htmx) {
```

- [ ] **Step 2: Add dispatch on the error-with-items branch**

In the same function, the error branch currently reads:

```javascript
            if (d.status === 'error') {
              regionStatusEl.textContent =
                'Finished with errors — ' + d.items_created + ' item(s) created.';
              scanRegionBtn.disabled = false;  // allow retry; pendingRegion is still set
              return;
            }
```

Replace it with (adds the dispatch when partial items were still created):

```javascript
            if (d.status === 'error') {
              regionStatusEl.textContent =
                'Finished with errors — ' + d.items_created + ' item(s) created.';
              if (d.items_created > 0) {
                document.dispatchEvent(new CustomEvent('cvp:items-added', {
                  detail: { matterId: matterId, jobId: jobId, count: d.items_created }
                }));
              }
              scanRegionBtn.disabled = false;  // allow retry; pendingRegion is still set
              return;
            }
```

- [ ] **Step 3: Run the full test suite (no regressions)**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 4: Format and commit**

```bash
uv run ruff format .
uv run ruff format --check .
git add src/cvp/static/crop-editor.js
git commit -m "$(cat <<'EOF'
feat: region rescan dispatches cvp:items-added on completion

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Verification (manual, after all tasks)

Run the app: `uv run dev` (localhost:8000). With a matter that has evidence images:

1. **Full scan:** Evidence tab → select images → Scan. When the progress fragment reaches "Scan complete", switch to the Items tab: the `✦ N new items added — View them` banner is visible. Click it → the items list refreshes, totals update, and the view scrolls to the newest rows at the bottom.
2. **Scan all:** same, via "Scan all unscanned". Confirm the banner count reflects the items created.
3. **Region rescan:** open the crop editor on an image, draw a region, "Scan region". On completion the banner appears on the Items tab (close the modal to see it); "View them" reveals the new rows.
4. **Multiple scans before viewing:** run two scans without clicking "View them" — confirm the banner count is the sum and dedups per job (no double counting on the repeating 2s poll).
5. **Totals staleness fix:** add an item manually via "+ Add item" — confirm the Confirmed/RCV/ACV summary updates without reload (the `item-created` self-refresh).

Then run the `verify` workflow to confirm in the real app.

---

## Self-Review

- **Spec coverage:** §1 completion signal → Tasks 3 (full-scan attrs), 4 (detector), 5 (region dispatch). §2 banner → Task 4. §3 View them action → Task 4. §4 summary refresh → Tasks 1–2. §5 large-matter scroll → Task 4 (`scrollIntoView` on settle). Files-touched list → all mapped. ✓
- **Placeholder scan:** no TBD/TODO; every code step shows full content. ✓
- **Type consistency:** `compute_items_totals(matter_id, db) -> dict[str, int]` defined Task 1, consumed Task 2; `cvp:items-added` detail `{matterId, jobId, count}` identical in Tasks 4 and 5; data-attr names (`data-scan-state`, `data-job-id`, `data-matter-id`, `data-items-created`) identical in Tasks 3 and 4. ✓
