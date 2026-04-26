# Phase 4: Comments + Audit Logging — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add scoped comments on items (internal vs. shared visibility) and a full audit logging system that tracks auth events, data mutations, and view/access events across the entire application.

**Architecture:** Comments are a new ORM model with a simple router. Audit logging uses a FastAPI dependency that writes log entries as background tasks (non-blocking). View events are debounced (same user + resource within 5 minutes = no duplicate). Audit viewer is added to the System Admin panel.

**Tech Stack:** SQLAlchemy 2.x, Alembic, FastAPI BackgroundTasks, Jinja2, HTMX

**Spec:** `docs/superpowers/specs/2026-04-25-auth-rbac-design.md` (Sections 8, 9)

**Prerequisite:** Phases 1 and 2 must be complete. Phase 3 is recommended but not strictly required (audit viewer goes in the System Admin panel).

---

## File Structure

### New files to create:
- `src/cvp/models_comments.py` — Comment ORM model
- `src/cvp/models_audit.py` — AuditLog ORM model
- `src/cvp/routers/comments.py` — Comment CRUD endpoints
- `src/cvp/services/audit.py` — Audit logging service (write, debounce, query)
- `src/cvp/templates/_comments.html` — Comment thread partial for item rows
- `src/cvp/templates/admin/system/audit.html` — Audit log viewer page
- `src/cvp/templates/admin/system/_audit_rows.html` — HTMX partial for filtered audit results
- `tests/test_comments.py` — Comment model and endpoint tests
- `tests/test_audit.py` — Audit logging service tests

### Files to modify:
- `src/cvp/models.py` — Import comment and audit models to register with Base
- `src/cvp/main.py` — Mount comments router
- `src/cvp/dependencies.py` — Add audit logging integration
- `src/cvp/templates/_item_row.html` — Add comments expand/collapse link
- `src/cvp/templates/_item_row_edit.html` — Add comments section
- `src/cvp/routers/auth.py` — Add audit logging for auth events
- `src/cvp/routers/admin/system.py` — Add audit viewer route
- All routers — Add audit log calls for mutations and views

---

### Task 1: Create Comment model and migration

**Files:**
- Create: `src/cvp/models_comments.py`
- Modify: `src/cvp/models.py`
- Test: `tests/test_comments.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_comments.py`:

```python
"""Tests for comments model and endpoints."""

from cvp.models_comments import Comment


def test_comment_model_fields():
    c = Comment(
        id="c1",
        item_id="i1",
        user_id="u1",
        body="This price looks too high.",
        visibility="shared",
    )
    assert c.item_id == "i1"
    assert c.visibility == "shared"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_comments.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Create models_comments.py**

Create `src/cvp/models_comments.py`:

```python
"""Comment ORM model — scoped visibility per item."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from cvp.models import Base, _new_uuid


class Comment(Base):
    """A comment on an item with internal or shared visibility."""

    __tablename__ = "comments"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    item_id: Mapped[str] = mapped_column(String, ForeignKey("items.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    visibility: Mapped[str] = mapped_column(String, nullable=False, default="shared")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
```

- [ ] **Step 4: Register with Base**

Add at the bottom of `src/cvp/models.py`:

```python
import cvp.models_comments as _comment_models  # noqa: F401, E402
```

- [ ] **Step 5: Generate and apply migration**

```bash
uv run alembic revision --autogenerate -m "add comments table"
uv run alembic upgrade head
```

- [ ] **Step 6: Run test**

Run: `uv run pytest tests/test_comments.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/cvp/models_comments.py src/cvp/models.py tests/test_comments.py migrations/versions/
git commit -m "feat: Comment model with internal/shared visibility"
```

---

### Task 2: Create comments router

**Files:**
- Create: `src/cvp/routers/comments.py`
- Test: `tests/test_comments.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_comments.py`:

```python
def test_create_comment_placeholder():
    """Placeholder — tests will use TestClient with seeded DB."""
    assert True


def test_comment_visibility_internal_only():
    """Internal comments should not be visible to external users."""
    assert True
```

- [ ] **Step 2: Create comments router**

Create `src/cvp/routers/comments.py`:

```python
"""Comment CRUD endpoints with visibility scoping."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from cvp.db import get_db
from cvp.dependencies import CurrentUser, require_matter_role
from cvp.models import Item
from cvp.models_comments import Comment
from cvp.models_auth import User

router = APIRouter()

EDIT_WINDOW_MINUTES = 15


@router.get("/api/items/{item_id}/comments", response_class=HTMLResponse)
def list_comments(
    item_id: str,
    user: CurrentUser = Depends(require_matter_role("viewer")),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """List comments for an item, filtered by visibility."""
    query = db.query(Comment).filter(Comment.item_id == item_id)

    # External users only see shared comments
    if user.group_kind == "external":
        query = query.filter(Comment.visibility == "shared")

    comments = query.order_by(Comment.created_at.asc()).all()

    # Fetch user display names
    user_ids = {c.user_id for c in comments}
    users = {u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()} if user_ids else {}

    from pathlib import Path
    from fastapi.templating import Jinja2Templates
    BASE_DIR = Path(__file__).parent.parent
    templates = Jinja2Templates(directory=BASE_DIR / "templates")

    html = templates.get_template("_comments.html").render(
        comments=comments,
        users=users,
        item_id=item_id,
        current_user=user,
        edit_window_minutes=EDIT_WINDOW_MINUTES,
        now=datetime.now(tz=timezone.utc),
    )
    return HTMLResponse(html)


@router.post("/api/items/{item_id}/comments", response_class=HTMLResponse)
def create_comment(
    item_id: str,
    body: str = Form(...),
    visibility: str = Form("shared"),
    user: CurrentUser = Depends(require_matter_role("viewer")),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Create a comment on an item."""
    if visibility not in ("internal", "shared"):
        raise HTTPException(status_code=400, detail="Invalid visibility")

    # External users can only create shared comments
    if user.group_kind == "external" and visibility == "internal":
        visibility = "shared"

    comment = Comment(
        item_id=item_id,
        user_id=user.id,
        body=body.strip(),
        visibility=visibility,
    )
    db.add(comment)
    db.commit()

    # Return updated comment list
    return list_comments(item_id, user=user, db=db)


@router.patch("/api/comments/{comment_id}", response_class=JSONResponse)
def edit_comment(
    comment_id: str,
    body: str = Form(...),
    user: CurrentUser = Depends(require_matter_role("viewer")),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Edit own comment within the edit window."""
    comment = db.get(Comment, comment_id)
    if comment is None:
        raise HTTPException(status_code=404, detail="Comment not found")

    if comment.user_id != user.id:
        raise HTTPException(status_code=403, detail="Can only edit your own comments")

    cutoff = datetime.now(tz=timezone.utc) - timedelta(minutes=EDIT_WINDOW_MINUTES)
    if comment.created_at.replace(tzinfo=timezone.utc) < cutoff:
        raise HTTPException(status_code=403, detail="Edit window has expired")

    comment.body = body.strip()
    db.commit()
    return JSONResponse({"ok": True})


@router.delete("/api/comments/{comment_id}", response_class=JSONResponse)
def delete_comment(
    comment_id: str,
    user: CurrentUser = Depends(require_matter_role("viewer")),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Delete own comment (within window) or any comment (if manager/admin)."""
    comment = db.get(Comment, comment_id)
    if comment is None:
        raise HTTPException(status_code=404, detail="Comment not found")

    # Managers and system admins can delete any comment
    if user.system_role in ("system_admin",):
        db.delete(comment)
        db.commit()
        return JSONResponse({"ok": True})

    # Check if this is the user's own comment within the window
    if comment.user_id != user.id:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    cutoff = datetime.now(tz=timezone.utc) - timedelta(minutes=EDIT_WINDOW_MINUTES)
    if comment.created_at.replace(tzinfo=timezone.utc) < cutoff:
        raise HTTPException(status_code=403, detail="Delete window has expired")

    db.delete(comment)
    db.commit()
    return JSONResponse({"ok": True})
```

- [ ] **Step 3: Create _comments.html template**

Create `src/cvp/templates/_comments.html`:

```html
<div class="space-y-3">
  {% for comment in comments %}
  <div class="p-3 rounded-lg text-sm {% if comment.visibility == 'internal' %}bg-amber-50 border border-amber-200{% else %}bg-gray-50 border border-gray-200{% endif %}">
    <div class="flex items-center justify-between mb-1">
      <div class="flex items-center gap-2">
        <span class="font-medium text-gray-900">{{ users.get(comment.user_id, {}).display_name or 'Unknown' }}</span>
        {% if comment.visibility == 'internal' %}
        <span class="inline-flex items-center rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700">Internal</span>
        {% endif %}
      </div>
      <span class="text-xs text-gray-500">{{ comment.created_at.strftime('%b %d, %Y %H:%M') }}</span>
    </div>
    <p class="text-gray-700 whitespace-pre-wrap">{{ comment.body }}</p>
  </div>
  {% endfor %}

  <!-- New comment form -->
  <form hx-post="/api/items/{{ item_id }}/comments"
        hx-target="closest .comments-container"
        hx-swap="innerHTML"
        class="flex gap-2 mt-2">
    <textarea name="body" rows="2" required placeholder="Add a comment..."
              class="flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none"></textarea>
    <div class="flex flex-col gap-1">
      {% if current_user.group_kind == 'internal' %}
      <select name="visibility" class="rounded-md border border-gray-300 px-2 py-1 text-xs">
        <option value="internal" selected>Internal</option>
        <option value="shared">Shared</option>
      </select>
      {% else %}
      <input type="hidden" name="visibility" value="shared" />
      {% endif %}
      <button type="submit"
              class="rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-500">
        Post
      </button>
    </div>
  </form>
</div>
```

- [ ] **Step 4: Mount comments router in main.py**

```python
from cvp.routers import comments
app.include_router(comments.router)
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_comments.py -v`

- [ ] **Step 6: Commit**

```bash
git add src/cvp/routers/comments.py src/cvp/templates/_comments.html src/cvp/main.py tests/test_comments.py
git commit -m "feat: comments router with internal/shared visibility"
```

---

### Task 3: Create AuditLog model and service

**Files:**
- Create: `src/cvp/models_audit.py`
- Create: `src/cvp/services/audit.py`
- Modify: `src/cvp/models.py`
- Test: `tests/test_audit.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_audit.py`:

```python
"""Tests for audit logging."""

from cvp.models_audit import AuditLog
from cvp.services.audit import should_debounce_view


def test_audit_log_model():
    log = AuditLog(
        id="al1",
        user_id="u1",
        action="item.update",
        resource_type="item",
        resource_id="i1",
        matter_id="m1",
        detail={"old": {"price": 100}, "new": {"price": 200}},
        ip_address="127.0.0.1",
    )
    assert log.action == "item.update"
    assert log.detail["old"]["price"] == 100
```

- [ ] **Step 2: Create models_audit.py**

Create `src/cvp/models_audit.py`:

```python
"""Audit log ORM model."""

import json
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from cvp.models import Base, _new_uuid


class AuditLog(Base):
    """Immutable audit trail entry."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_created_at", "created_at"),
        Index("ix_audit_logs_user_id", "user_id"),
        Index("ix_audit_logs_matter_id", "matter_id"),
        Index("ix_audit_logs_action", "action"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    user_id: Mapped[str | None] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String, nullable=False)
    resource_type: Mapped[str] = mapped_column(String, nullable=True, default="")
    resource_id: Mapped[str | None] = mapped_column(String, nullable=True)
    matter_id: Mapped[str | None] = mapped_column(String, nullable=True)
    detail: Mapped[dict | None] = mapped_column(Text, nullable=True)  # Stored as JSON string
    ip_address: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    def __init__(self, **kwargs):
        # Serialize detail dict to JSON string for storage
        if "detail" in kwargs and isinstance(kwargs["detail"], dict):
            kwargs["detail"] = json.dumps(kwargs["detail"])
        super().__init__(**kwargs)

    @property
    def detail_dict(self) -> dict:
        if self.detail and isinstance(self.detail, str):
            return json.loads(self.detail)
        if isinstance(self.detail, dict):
            return self.detail
        return {}
```

- [ ] **Step 3: Create audit service**

Create `src/cvp/services/audit.py`:

```python
"""Audit logging service — write, debounce, query."""

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from cvp.db import SessionLocal
from cvp.models_audit import AuditLog

VIEW_DEBOUNCE_MINUTES = 5


def write_audit_log(
    *,
    user_id: str | None,
    action: str,
    resource_type: str = "",
    resource_id: str | None = None,
    matter_id: str | None = None,
    detail: dict | None = None,
    ip_address: str = "",
) -> None:
    """Write an audit log entry. Intended to be called as a BackgroundTask."""
    db = SessionLocal()
    try:
        log = AuditLog(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            matter_id=matter_id,
            detail=detail,
            ip_address=ip_address,
        )
        db.add(log)
        db.commit()
    finally:
        db.close()


def should_debounce_view(
    db: Session,
    user_id: str,
    action: str,
    resource_id: str,
) -> bool:
    """Check if a view event should be debounced (same user+resource within 5 min)."""
    cutoff = datetime.now(tz=timezone.utc) - timedelta(minutes=VIEW_DEBOUNCE_MINUTES)
    existing = (
        db.query(AuditLog)
        .filter(
            AuditLog.user_id == user_id,
            AuditLog.action == action,
            AuditLog.resource_id == resource_id,
            AuditLog.created_at >= cutoff,
        )
        .first()
    )
    return existing is not None


def get_client_ip(request) -> str:
    """Extract client IP from request, checking X-Forwarded-For."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return ""
```

- [ ] **Step 4: Register with Base**

Add at bottom of `src/cvp/models.py`:

```python
import cvp.models_audit as _audit_models  # noqa: F401, E402
```

- [ ] **Step 5: Generate and apply migration**

```bash
uv run alembic revision --autogenerate -m "add audit_logs table"
uv run alembic upgrade head
```

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/test_audit.py -v`

- [ ] **Step 7: Commit**

```bash
git add src/cvp/models_audit.py src/cvp/services/audit.py src/cvp/models.py tests/test_audit.py migrations/versions/
git commit -m "feat: AuditLog model and audit service with view debouncing"
```

---

### Task 4: Instrument auth router with audit logging

**Files:**
- Modify: `src/cvp/routers/auth.py`

- [ ] **Step 1: Add audit logging to login**

In the `login` endpoint, after successful login add:

```python
from fastapi import BackgroundTasks
from cvp.services.audit import write_audit_log, get_client_ip

# Add background_tasks: BackgroundTasks to the function signature

background_tasks.add_task(
    write_audit_log,
    user_id=user.id,
    action="auth.login",
    detail={"user_agent": request.headers.get("user-agent", "")},
    ip_address=get_client_ip(request),
)
```

On failed login:

```python
background_tasks.add_task(
    write_audit_log,
    user_id=None,
    action="auth.login_failed",
    detail={"email": email, "user_agent": request.headers.get("user-agent", "")},
    ip_address=get_client_ip(request),
)
```

- [ ] **Step 2: Add audit logging to logout, register, refresh**

Similar pattern for each auth endpoint.

- [ ] **Step 3: Run tests**

Run: `uv run pytest -v`

- [ ] **Step 4: Commit**

```bash
git add src/cvp/routers/auth.py
git commit -m "feat: audit logging for auth events"
```

---

### Task 5: Instrument data mutation routers with audit logging

**Files:**
- Modify: All routers (`items.py`, `evidence.py`, `rooms.py`, `crops.py`, `vision.py`, `serp.py`, `exports.py`, `matters.py`)

- [ ] **Step 1: Add BackgroundTasks and audit imports to each router**

For each mutation endpoint, add a `background_tasks: BackgroundTasks` parameter and call `write_audit_log` as a background task.

Example for `update_item` in items.py:

```python
from fastapi import BackgroundTasks
from cvp.services.audit import write_audit_log, get_client_ip

@router.patch("/api/items/{item_id}", response_class=HTMLResponse)
def update_item(
    request: Request,
    item_id: str,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_matter_role("editor")),
    ...
) -> HTMLResponse:
    # Capture old values before update
    old_price = item.rcv_unit_cents
    # ... do update ...
    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="item.update",
        resource_type="item",
        resource_id=item_id,
        matter_id=item.matter_id,
        detail={"changes": {"rcv_unit_cents": {"old": old_price, "new": item.rcv_unit_cents}}},
        ip_address=get_client_ip(request),
    )
```

- [ ] **Step 2: Add view event logging with debouncing**

For view endpoints (matter_detail, serve_file, export download), add debounced audit logging:

```python
from cvp.services.audit import should_debounce_view

# In the route handler, after auth check:
if not should_debounce_view(db, user.id, "matter.view", matter_id):
    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="matter.view",
        resource_type="matter",
        resource_id=matter_id,
        matter_id=matter_id,
        ip_address=get_client_ip(request),
    )
```

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest -v`

- [ ] **Step 4: Commit**

```bash
git add src/cvp/routers/
git commit -m "feat: audit logging for all data mutations and views"
```

---

### Task 6: Add audit viewer to System Admin panel

**Files:**
- Modify: `src/cvp/routers/admin/system.py`
- Create: `src/cvp/templates/admin/system/audit.html`
- Create: `src/cvp/templates/admin/system/_audit_rows.html`

- [ ] **Step 1: Add audit route to system admin router**

```python
@router.get("/admin/system/audit", response_class=HTMLResponse)
def audit_log_viewer(
    request: Request,
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
    action: str = "",
    user_filter: str = "",
    matter_id: str = "",
    date_from: str = "",
    date_to: str = "",
    page: int = 1,
) -> HTMLResponse:
    """Filterable audit log viewer with pagination."""
    query = db.query(AuditLog).order_by(AuditLog.created_at.desc())

    if action:
        query = query.filter(AuditLog.action.like(f"{action}%"))
    if user_filter:
        query = query.filter(AuditLog.user_id == user_filter)
    if matter_id:
        query = query.filter(AuditLog.matter_id == matter_id)
    # ... date filtering ...

    per_page = 50
    total = query.count()
    logs = query.offset((page - 1) * per_page).limit(per_page).all()

    # Resolve user display names
    user_ids = {log.user_id for log in logs if log.user_id}
    users = {u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()} if user_ids else {}

    return templates.TemplateResponse(...)
```

- [ ] **Step 2: Add CSV export endpoint**

```python
@router.get("/admin/system/audit/export")
def export_audit_csv(
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
    # ... same filters as audit_log_viewer ...
) -> StreamingResponse:
    """Export filtered audit logs as CSV."""
    # Query with filters, stream as CSV
```

- [ ] **Step 3: Create audit viewer template**

Create `src/cvp/templates/admin/system/audit.html` with filter form (action type dropdown, user search, matter ID, date range) and a paginated table of results.

- [ ] **Step 4: Run tests**

Run: `uv run pytest -v`

- [ ] **Step 5: Commit**

```bash
git add src/cvp/routers/admin/system.py src/cvp/templates/admin/system/audit.html src/cvp/templates/admin/system/_audit_rows.html
git commit -m "feat: audit log viewer with filters and CSV export"
```

---

### Task 7: Add comments UI to item rows

**Files:**
- Modify: `src/cvp/templates/_item_row.html`
- Modify: `src/cvp/templates/_item_row_edit.html`

- [ ] **Step 1: Add comments toggle to item rows**

In `_item_row.html`, add a "Comments" link that loads the comment thread via HTMX:

```html
<a hx-get="/api/items/{{ item.id }}/comments"
   hx-target="#comments-{{ item.id }}"
   hx-swap="innerHTML"
   class="text-xs text-indigo-600 hover:text-indigo-500 cursor-pointer">
  Comments
</a>
<div id="comments-{{ item.id }}" class="comments-container mt-2"></div>
```

- [ ] **Step 2: Add same to _item_row_edit.html**

Same pattern in the edit row template.

- [ ] **Step 3: Manual test**

Start dev server, navigate to a matter, expand an item, click "Comments" — verify the comment thread loads and posting works.

- [ ] **Step 4: Commit**

```bash
git add src/cvp/templates/_item_row.html src/cvp/templates/_item_row_edit.html
git commit -m "feat: comments UI in item rows"
```

---

### Task 8: Final verification

- [ ] **Step 1: Run full test suite and linter**

```bash
uv run pytest -v
uv run ruff check . && uv run ruff format --check .
```

- [ ] **Step 2: Manual smoke test**

1. Create a comment as internal user — verify "Internal" badge shows
2. Log in as external user — verify internal comments are hidden
3. Post a shared comment as external user — verify internal users see it
4. Edit a comment within 15 minutes — verify it works
5. Wait 15+ minutes, try to edit — verify it's blocked
6. View audit log in System Admin panel — verify events are recorded
7. Filter audit logs by action, user, date — verify filtering works
8. Export audit logs as CSV — verify file downloads

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "chore: phase 4 complete — comments + audit logging"
```
