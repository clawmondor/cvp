# User Feedback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a logged-in-user feedback channel with a floating widget, a `system_admin` triage page, and a status/comment workflow — backed by two new tables, a reusable plain-text input validator, and the existing comments / admin / CSRF / HTMX patterns.

**Architecture:** Two new SQLAlchemy models (`Feedback`, `FeedbackComment`) in `src/cvp/models_feedback.py` with one Alembic migration. A reusable `assert_plain_text()` validator in a new `src/cvp/text_validation.py` module. One user-facing router (`src/cvp/routers/feedback.py`) and one admin router (`src/cvp/routers/admin/feedback.py`). A floating widget partial included once in `base.html` (gated on `user` + path), driven by HTMX + delegated listeners in `static/app.js` (no inline JS — CSP). Access control: author OR `system_admin` for read/write on a feedback; `system_admin` only for status change and submit-on-behalf.

**Tech Stack:** FastAPI, Jinja2, HTMX, SQLAlchemy 2.x, Alembic, Tailwind via CDN, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-06-03-user-feedback-design.md`

**Repo facts the engineer needs:**
- Migrations live under `migrations/versions/` (Alembic `script_location = migrations`, file template `YYYYMMDD_<rev>_<slug>.py`). The current head is `56a54cc0c202` (from `migrations/versions/20260522_56a54cc0c202_add_vision_job_tables.py`).
- `require_system_admin` and `require_active_user` already exist in `src/cvp/dependencies.py` (lines 133 and 155). Do NOT redefine them.
- All ORM modules must be imported by `tests/conftest.py` so `Base.metadata.create_all(engine)` picks them up.
- CSRF is wired globally in `static/app.js` via an `hx-headers` body attribute (HTMX) and a hidden `_csrf` field (plain forms). New `hx-post` calls just work — no per-form CSRF code needed.
- The admin sidebar is a per-page `{% block sidebar %}` (no shared partial). Adding the "Feedback" nav link means editing every existing `templates/admin/system/*.html` file's sidebar block. Mechanical.
- Delegated click handlers in `static/app.js` lines 225–275 are the **only** acceptable place for click logic. Never write `onclick=` / `onchange=` etc. in templates — CSP blocks them.

---

## File Structure

**Create:**
- `src/cvp/text_validation.py` — reusable `assert_plain_text(value, *, field_name)` helper. Project-wide; not feedback-specific.
- `src/cvp/models_feedback.py` — `Feedback` and `FeedbackComment` ORM models.
- `migrations/versions/20260603_<rev>_add_feedback_tables.py` — Alembic migration creating `feedback` + `feedback_comment`.
- `src/cvp/routers/feedback.py` — user-facing router (`/feedback/*`). Holds `_clean_page_url()`, `_check_feedback_access()`, and `ALLOWED_STATUSES`. Also exports `count_admin_unread(db)` and `has_author_unread(db, user_id)` helpers for badge rendering.
- `src/cvp/routers/admin/feedback.py` — admin router (`/admin/system/feedback/*`).
- `src/cvp/templates/_feedback_widget.html` — floating button + popover shell (loaded by base.html for authenticated pages).
- `src/cvp/templates/_feedback_widget_panel.html` — popover inner contents: new-feedback form + author's threads list. Loaded lazily via `hx-get="/feedback/widget"`.
- `src/cvp/templates/_feedback_thread.html` — shared thread partial (initial post + comments + composer). Used by both the user widget and the admin detail page; `is_admin_view` flag controls the status sidebar.
- `src/cvp/templates/_feedback_unread_badge.html` — single `<span>` rendered for the floating button's red dot (polled every 60s).
- `src/cvp/templates/admin/system/feedback.html` — admin list view (filters + sortable table).
- `src/cvp/templates/admin/system/feedback_detail.html` — admin single-thread page (extends admin/base, embeds `_feedback_thread.html`).
- `tests/test_text_validation.py` — exhaustive coverage of `assert_plain_text()`.
- `tests/test_models_feedback.py` — ORM defaults + status CHECK constraint.
- `tests/test_feedback_router.py` — user-facing endpoint integration tests.
- `tests/test_admin_feedback_router.py` — admin endpoint integration tests.
- `tests/test_feedback_sanitization.py` — `_clean_page_url()` + body length caps + status whitelist + HTML rejection at the endpoint layer.

**Modify:**
- `src/cvp/dependencies.py` — add `_check_feedback_access(user, feedback) -> bool` near `_check_matter_access`. Pure function, no DB hit.
- `src/cvp/main.py` — register two new routers.
- `src/cvp/templates/base.html` — include `_feedback_widget.html` when `user` and path is not in `{/, /login, /register, /splash}`.
- `src/cvp/templates/admin/system/dashboard.html`, `users.html`, `groups.html`, `matters.html`, `audit.html`, `user_detail.html`, `group_detail.html` — add the "Feedback" link with unread chip to each `{% block sidebar %}`.
- `src/cvp/static/app.js` — add delegated handlers under the existing pattern at lines 225–275.
- `tests/conftest.py` — add `import cvp.models_feedback`.
- `docs/BACKLOG.md` — append two entries (attachments + `assert_plain_text` rollout).

---

## Task ordering rationale

Tests come before code (TDD). Foundational pieces (validator, models, migration, conftest) come first so later tasks can write router tests that hit a real DB. The widget UI lands after the user endpoints exist so we can curl the API while wiring the template. The admin sidebar link comes last because it depends on the admin router being mounted.

---

## Task 1: Plain-text input validator

**Files:**
- Create: `src/cvp/text_validation.py`
- Test: `tests/test_text_validation.py`

- [ ] **Step 1: Write the failing tests**

Write `tests/test_text_validation.py`:

```python
"""Tests for the project-wide plain-text input validator."""

import pytest
from fastapi import HTTPException

from cvp.text_validation import assert_plain_text


def test_accepts_plain_ascii():
    assert_plain_text("Hello world, this is fine.", field_name="body")


def test_accepts_unicode_and_emoji():
    assert_plain_text("Café — résumé — 🎉 — Привет", field_name="body")


def test_accepts_newlines_tabs_and_carriage_returns():
    assert_plain_text("line one\nline two\twith tab\r\nline three", field_name="body")


def test_rejects_less_than():
    with pytest.raises(HTTPException) as exc:
        assert_plain_text("a < b", field_name="body")
    assert exc.value.status_code == 400
    assert "body" in exc.value.detail


def test_rejects_greater_than():
    with pytest.raises(HTTPException) as exc:
        assert_plain_text("a > b", field_name="body")
    assert exc.value.status_code == 400


def test_rejects_script_tag():
    with pytest.raises(HTTPException) as exc:
        assert_plain_text("<script>alert(1)</script>", field_name="body")
    assert exc.value.status_code == 400


def test_rejects_numeric_html_entity():
    with pytest.raises(HTTPException) as exc:
        assert_plain_text("&#60;script&#62;", field_name="body")
    assert exc.value.status_code == 400


def test_rejects_named_html_entity():
    with pytest.raises(HTTPException) as exc:
        assert_plain_text("AT&amp;T", field_name="body")
    assert exc.value.status_code == 400


def test_rejects_javascript_scheme_case_insensitive():
    with pytest.raises(HTTPException):
        assert_plain_text("click javascript:alert(1)", field_name="body")
    with pytest.raises(HTTPException):
        assert_plain_text("click JaVaScRiPt:alert(1)", field_name="body")


def test_rejects_data_scheme_case_insensitive():
    with pytest.raises(HTTPException):
        assert_plain_text("see data:text/html,foo", field_name="body")
    with pytest.raises(HTTPException):
        assert_plain_text("see DATA:text/html,foo", field_name="body")


def test_rejects_nul_byte():
    with pytest.raises(HTTPException):
        assert_plain_text("hello\x00world", field_name="body")


def test_rejects_escape_byte():
    with pytest.raises(HTTPException):
        assert_plain_text("hello\x1bworld", field_name="body")


def test_error_message_uses_field_name():
    with pytest.raises(HTTPException) as exc:
        assert_plain_text("<", field_name="Matter description")
    assert "Matter description" in exc.value.detail


def test_default_field_name_is_input():
    with pytest.raises(HTTPException) as exc:
        assert_plain_text("<")
    assert "input" in exc.value.detail
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_text_validation.py -v`
Expected: ImportError or FAIL — `cvp.text_validation` does not exist yet.

- [ ] **Step 3: Implement the validator**

Write `src/cvp/text_validation.py`:

```python
"""Reusable plain-text validator for free-form user input.

Rejects HTML markup, entity-encoded payloads, dangerous URL schemes embedded
in text, and most control characters. Intended for any free-form text field
where the storage and rendering layers treat the value as plain text (no
markdown, no link auto-detection, no `| safe`).
"""

import re

from fastapi import HTTPException

_HTML_ENTITY_RE = re.compile(r"&#?\w+;")
_FORBIDDEN_SUBSTRINGS = ("javascript:", "data:")

# C0 control characters are 0x00..0x1F. We allow \t (0x09), \n (0x0A), \r (0x0D).
_ALLOWED_CONTROL = {"\t", "\n", "\r"}


def _has_disallowed_control(value: str) -> bool:
    for ch in value:
        code = ord(ch)
        if code < 0x20 and ch not in _ALLOWED_CONTROL:
            return True
        if code == 0x7F:  # DEL
            return True
    return False


def assert_plain_text(value: str, *, field_name: str = "input") -> None:
    """Raise HTTPException(400) if `value` contains HTML, entities, dangerous schemes, or controls."""
    if "<" in value or ">" in value:
        _reject(field_name)
    if _HTML_ENTITY_RE.search(value):
        _reject(field_name)
    lowered = value.lower()
    for needle in _FORBIDDEN_SUBSTRINGS:
        if needle in lowered:
            _reject(field_name)
    if _has_disallowed_control(value):
        _reject(field_name)


def _reject(field_name: str) -> None:
    raise HTTPException(
        status_code=400,
        detail=f"{field_name} may not contain HTML or special markup. Please use plain text.",
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_text_validation.py -v`
Expected: 14 passed.

- [ ] **Step 5: Commit**

```bash
uv run ruff format .
uv run ruff format --check .
git add src/cvp/text_validation.py tests/test_text_validation.py
git commit -m "feat: add reusable plain-text input validator"
```

---

## Task 2: Feedback ORM models

**Files:**
- Create: `src/cvp/models_feedback.py`
- Test: `tests/test_models_feedback.py`
- Modify: `tests/conftest.py`

- [ ] **Step 1: Register the new module in conftest so its tables get created**

In `tests/conftest.py`, add `import cvp.models_feedback  # noqa: F401` next to the other model imports (after `import cvp.models_comments`).

Resulting block:

```python
import cvp.models  # noqa: F401
import cvp.models_access  # noqa: F401
import cvp.models_audit  # noqa: F401
import cvp.models_auth  # noqa: F401
import cvp.models_comments  # noqa: F401
import cvp.models_feedback  # noqa: F401
import cvp.models_vision  # noqa: F401
```

- [ ] **Step 2: Write the failing model tests**

Write `tests/test_models_feedback.py`:

```python
"""Tests for the feedback ORM models."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cvp.models_auth  # noqa: F401 — ensures users/groups tables exist
import cvp.models_feedback  # noqa: F401
from cvp.models import Base
from cvp.models_auth import Group, User
from cvp.models_feedback import Feedback, FeedbackComment


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # SQLite needs PRAGMA foreign_keys=ON for FK enforcement; CHECK works without it.
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    group = Group(id="g1", name="Internal", kind="internal")
    user = User(
        id="u1",
        email="u1@test.com",
        display_name="User One",
        system_role="internal_user",
        group_id="g1",
        is_active=True,
    )
    session.add_all([group, user])
    session.commit()
    yield session
    session.close()


def test_feedback_defaults(db):
    fb = Feedback(
        id="f1",
        author_user_id="u1",
        author_group_id="g1",
        page_url="/dashboard",
        body="Something is broken.",
    )
    db.add(fb)
    db.commit()
    db.refresh(fb)

    assert fb.status == "pending"
    assert fb.created_at is not None
    assert fb.deleted_at is None
    assert fb.deleted_by_user_id is None
    assert fb.last_admin_read_at is None
    assert fb.last_author_read_at is None
    assert fb.status_changed_at is None
    assert fb.status_changed_by_user_id is None


def test_feedback_status_check_rejects_unknown(db):
    fb = Feedback(
        id="f2",
        author_user_id="u1",
        author_group_id="g1",
        page_url="/x",
        body="hi",
        status="not-a-real-status",
    )
    db.add(fb)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_feedback_status_check_accepts_each_allowed_value(db):
    for i, status in enumerate(("pending", "reviewing", "backlog", "canceled", "done")):
        fb = Feedback(
            id=f"f-ok-{i}",
            author_user_id="u1",
            author_group_id="g1",
            page_url="/x",
            body="hi",
            status=status,
        )
        db.add(fb)
        db.commit()


def test_feedback_comment_defaults(db):
    fb = Feedback(
        id="f3",
        author_user_id="u1",
        author_group_id="g1",
        page_url="/x",
        body="hi",
    )
    db.add(fb)
    db.commit()
    c = FeedbackComment(
        id="c1",
        feedback_id="f3",
        author_user_id="u1",
        body="follow up",
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    assert c.created_at is not None
    assert c.deleted_at is None
    assert c.deleted_by_user_id is None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_models_feedback.py -v`
Expected: ImportError — `cvp.models_feedback` does not exist.

- [ ] **Step 4: Implement the models**

Write `src/cvp/models_feedback.py`:

```python
"""Feedback ORM models: top-level feedback items and comment threads."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from cvp.models import Base, _new_uuid

ALLOWED_STATUSES = ("pending", "reviewing", "backlog", "canceled", "done")


class Feedback(Base):
    """A single piece of feedback from a user, with status and a comment thread."""

    __tablename__ = "feedback"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','reviewing','backlog','canceled','done')",
            name="ck_feedback_status",
        ),
        Index("ix_feedback_author_created", "author_user_id", "created_at"),
        Index("ix_feedback_status_created", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    author_user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False
    )
    author_group_id: Mapped[str] = mapped_column(
        String, ForeignKey("groups.id"), nullable=False
    )
    page_url: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    status_changed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status_changed_by_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id"), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deleted_by_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id"), nullable=True
    )
    last_admin_read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_author_read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class FeedbackComment(Base):
    """A comment posted on a feedback thread."""

    __tablename__ = "feedback_comment"
    __table_args__ = (
        Index("ix_feedback_comment_feedback_created", "feedback_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    feedback_id: Mapped[str] = mapped_column(
        String, ForeignKey("feedback.id"), nullable=False
    )
    author_user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deleted_by_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id"), nullable=True
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_models_feedback.py tests/test_text_validation.py -v`
Expected: all passed (4 in models + 14 in text_validation).

- [ ] **Step 6: Commit**

```bash
uv run ruff format .
uv run ruff format --check .
git add src/cvp/models_feedback.py tests/test_models_feedback.py tests/conftest.py
git commit -m "feat: add Feedback and FeedbackComment ORM models"
```

---

## Task 3: Alembic migration

**Files:**
- Create: `migrations/versions/20260603_<rev>_add_feedback_tables.py` (rev generated by Alembic)

- [ ] **Step 1: Auto-generate the migration**

Run: `uv run alembic revision --autogenerate -m "add feedback tables"`

Expected output: a new file in `migrations/versions/` named like `20260603_<12hexchars>_add_feedback_tables.py`. Open it and confirm `down_revision = '56a54cc0c202'`. If autogenerate picked up unrelated changes (sometimes happens when models drift), edit the file to keep only the two new `op.create_table()` calls and the matching `op.drop_table()` calls in `downgrade()`.

- [ ] **Step 2: Verify the migration file body**

The `upgrade()` body should look like this (CHECK constraint must be present — Alembic doesn't always emit it from SQLAlchemy `CheckConstraint`, so edit by hand if missing):

```python
def upgrade() -> None:
    op.create_table(
        "feedback",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("author_user_id", sa.String(), nullable=False),
        sa.Column("author_group_id", sa.String(), nullable=False),
        sa.Column("page_url", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.String(),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("status_changed_at", sa.DateTime(), nullable=True),
        sa.Column("status_changed_by_user_id", sa.String(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_by_user_id", sa.String(), nullable=True),
        sa.Column("last_admin_read_at", sa.DateTime(), nullable=True),
        sa.Column("last_author_read_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["author_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["author_group_id"], ["groups.id"]),
        sa.ForeignKeyConstraint(["status_changed_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["deleted_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('pending','reviewing','backlog','canceled','done')",
            name="ck_feedback_status",
        ),
    )
    op.create_index(
        "ix_feedback_author_created", "feedback", ["author_user_id", "created_at"]
    )
    op.create_index(
        "ix_feedback_status_created", "feedback", ["status", "created_at"]
    )

    op.create_table(
        "feedback_comment",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("feedback_id", sa.String(), nullable=False),
        sa.Column("author_user_id", sa.String(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_by_user_id", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["feedback_id"], ["feedback.id"]),
        sa.ForeignKeyConstraint(["author_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["deleted_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_feedback_comment_feedback_created",
        "feedback_comment",
        ["feedback_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_feedback_comment_feedback_created", table_name="feedback_comment")
    op.drop_table("feedback_comment")
    op.drop_index("ix_feedback_status_created", table_name="feedback")
    op.drop_index("ix_feedback_author_created", table_name="feedback")
    op.drop_table("feedback")
```

- [ ] **Step 3: Run the migration up**

Run: `uv run alembic upgrade head`
Expected: `INFO  [alembic.runtime.migration] Running upgrade 56a54cc0c202 -> <rev>, add feedback tables`.

- [ ] **Step 4: Roundtrip — down then back up to verify downgrade**

Run: `uv run alembic downgrade -1 && uv run alembic upgrade head`
Expected: clean downgrade followed by clean upgrade, no errors.

- [ ] **Step 5: Commit**

```bash
uv run ruff format .
uv run ruff format --check .
git add migrations/versions/
git commit -m "feat: migration for feedback tables"
```

---

## Task 4: Feedback access helper

**Files:**
- Modify: `src/cvp/dependencies.py`
- Test: `tests/test_dependencies.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_dependencies.py`:

```python
def test_check_feedback_access_author_allowed():
    from cvp.dependencies import CurrentUser, _check_feedback_access
    from cvp.models_feedback import Feedback

    user = CurrentUser(
        id="u1", email="u@x", system_role="internal_user", group_id="g", group_kind="internal"
    )
    fb = Feedback(
        id="f", author_user_id="u1", author_group_id="g", page_url="/x", body="b"
    )
    assert _check_feedback_access(user, fb) is True


def test_check_feedback_access_admin_allowed():
    from cvp.dependencies import CurrentUser, _check_feedback_access
    from cvp.models_feedback import Feedback

    user = CurrentUser(
        id="admin", email="a@x", system_role="system_admin", group_id="g", group_kind="internal"
    )
    fb = Feedback(
        id="f", author_user_id="someone_else", author_group_id="g", page_url="/x", body="b"
    )
    assert _check_feedback_access(user, fb) is True


def test_check_feedback_access_other_user_denied():
    from cvp.dependencies import CurrentUser, _check_feedback_access
    from cvp.models_feedback import Feedback

    user = CurrentUser(
        id="u2", email="u@x", system_role="internal_admin", group_id="g", group_kind="internal"
    )
    fb = Feedback(
        id="f", author_user_id="u1", author_group_id="g", page_url="/x", body="b"
    )
    assert _check_feedback_access(user, fb) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_dependencies.py -v -k feedback`
Expected: ImportError on `_check_feedback_access`.

- [ ] **Step 3: Implement the helper**

In `src/cvp/dependencies.py`, append (below `_check_matter_access`):

```python
from cvp.models_feedback import Feedback  # noqa: E402


def _check_feedback_access(user: CurrentUser, feedback: Feedback) -> bool:
    """Author of the feedback OR a system_admin may read/write/delete it."""
    if user.system_role == "system_admin":
        return True
    return user.id == feedback.author_user_id
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_dependencies.py -v -k feedback`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
uv run ruff format .
uv run ruff format --check .
git add src/cvp/dependencies.py tests/test_dependencies.py
git commit -m "feat: add _check_feedback_access helper"
```

---

## Task 5: page_url cleaner + feedback router skeleton

**Files:**
- Create: `src/cvp/routers/feedback.py`
- Create: `tests/test_feedback_sanitization.py`
- Modify: `src/cvp/main.py`

- [ ] **Step 1: Write the failing tests for `_clean_page_url`**

Write `tests/test_feedback_sanitization.py`:

```python
"""Tests for feedback-router sanitization helpers."""

from cvp.routers.feedback import _clean_page_url


def test_accepts_simple_path():
    assert _clean_page_url("/dashboard") == "/dashboard"


def test_accepts_path_with_query():
    assert _clean_page_url("/matters/abc?tab=items") == "/matters/abc?tab=items"


def test_rejects_protocol_relative():
    assert _clean_page_url("//evil.com/x") == "/"


def test_rejects_absolute_http():
    assert _clean_page_url("http://evil.com/x") == "/"


def test_rejects_absolute_https():
    assert _clean_page_url("https://evil.com/x") == "/"


def test_rejects_javascript_scheme():
    assert _clean_page_url("javascript:alert(1)") == "/"


def test_rejects_data_scheme():
    assert _clean_page_url("data:text/html,foo") == "/"


def test_rejects_empty():
    assert _clean_page_url("") == "/"


def test_rejects_no_leading_slash():
    assert _clean_page_url("dashboard") == "/"


def test_truncates_over_2048_to_fallback():
    long_url = "/" + ("a" * 3000)
    assert _clean_page_url(long_url) == "/"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_feedback_sanitization.py -v`
Expected: ImportError on `cvp.routers.feedback`.

- [ ] **Step 3: Create the router skeleton with the helper**

Write `src/cvp/routers/feedback.py`:

```python
"""User-facing feedback router (floating widget + author thread access)."""

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from cvp.db import get_db
from cvp.dependencies import (
    CurrentUser,
    _check_feedback_access,
    require_active_user,
)
from cvp.models_auth import User
from cvp.models_feedback import ALLOWED_STATUSES, Feedback, FeedbackComment
from cvp.text_validation import assert_plain_text

router = APIRouter()

BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")

FEEDBACK_BODY_MAX = 5000
COMMENT_BODY_MAX = 2000
PAGE_URL_MAX = 2048


def _clean_page_url(raw: str) -> str:
    """Return a safe relative path, or '/' if the input is unsafe or malformed.

    Accepts only paths starting with a single '/'. Protocol-relative URLs
    ('//evil.com'), absolute URLs ('http://...'), bare schemes ('javascript:'),
    over-length input, and anything else fall back to '/'.
    """
    if not raw:
        return "/"
    if len(raw) > PAGE_URL_MAX:
        return "/"
    if not raw.startswith("/"):
        return "/"
    if raw.startswith("//"):
        return "/"
    return raw
```

Then register the router in `src/cvp/main.py`. Find the routers import block and the `app.include_router` calls; add:

```python
from cvp.routers import feedback as feedback_router
# ...
app.include_router(feedback_router.router, dependencies=[Depends(require_active_user)])
```

(Add the `Depends` import if missing — it's already imported in `main.py`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_feedback_sanitization.py -v`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
uv run ruff format .
uv run ruff format --check .
git add src/cvp/routers/feedback.py tests/test_feedback_sanitization.py src/cvp/main.py
git commit -m "feat: feedback router skeleton with page_url cleaner"
```

---

## Task 6: Submit feedback endpoint

**Files:**
- Modify: `src/cvp/routers/feedback.py`
- Test: `tests/test_feedback_router.py` (new)
- Create: `src/cvp/templates/_feedback_widget_panel.html`

- [ ] **Step 1: Write the failing tests**

Write `tests/test_feedback_router.py`:

```python
"""Integration tests for the user-facing feedback router."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cvp.models_auth  # noqa: F401
import cvp.models_feedback  # noqa: F401
from cvp.dependencies import CurrentUser, require_active_user
from cvp.models import Base
from cvp.models_auth import Group, User
from cvp.models_feedback import Feedback, FeedbackComment


def _session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _seed(db, *, role="internal_user"):
    group = Group(id="g1", name="Internal", kind="internal")
    user = User(
        id="u1",
        email="u1@test.com",
        display_name="User One",
        system_role=role,
        group_id="g1",
        is_active=True,
    )
    other = User(
        id="u2",
        email="u2@test.com",
        display_name="User Two",
        system_role="internal_user",
        group_id="g1",
        is_active=True,
    )
    db.add_all([group, user, other])
    db.commit()
    return user, other


@pytest.fixture
def client_and_db():
    from cvp.db import get_db
    from cvp.main import app

    db = _session()
    user, _other = _seed(db)

    async def fake_user():
        return CurrentUser(
            id=user.id,
            email=user.email,
            system_role=user.system_role,
            group_id=user.group_id,
            group_kind="internal",
        )

    def override_get_db():
        yield db

    app.dependency_overrides[require_active_user] = fake_user
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c, db
    app.dependency_overrides.clear()


def test_submit_feedback_creates_pending_row(client_and_db):
    client, db = client_and_db
    resp = client.post(
        "/feedback",
        data={"body": "The font is too small.", "page_url": "/dashboard"},
    )
    assert resp.status_code == 200
    rows = db.query(Feedback).all()
    assert len(rows) == 1
    assert rows[0].body == "The font is too small."
    assert rows[0].status == "pending"
    assert rows[0].page_url == "/dashboard"
    assert rows[0].author_user_id == "u1"
    assert rows[0].author_group_id == "g1"


def test_submit_feedback_rejects_html(client_and_db):
    client, _db = client_and_db
    resp = client.post(
        "/feedback",
        data={"body": "<script>x</script>", "page_url": "/dashboard"},
    )
    assert resp.status_code == 400


def test_submit_feedback_rejects_empty(client_and_db):
    client, _db = client_and_db
    resp = client.post("/feedback", data={"body": "   ", "page_url": "/dashboard"})
    assert resp.status_code == 400


def test_submit_feedback_rejects_oversize(client_and_db):
    client, _db = client_and_db
    resp = client.post(
        "/feedback",
        data={"body": "a" * 5001, "page_url": "/dashboard"},
    )
    assert resp.status_code == 400


def test_submit_feedback_sanitizes_bad_url_to_root(client_and_db):
    client, db = client_and_db
    resp = client.post(
        "/feedback",
        data={"body": "fine body", "page_url": "//evil.com"},
    )
    assert resp.status_code == 200
    assert db.query(Feedback).one().page_url == "/"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_feedback_router.py -v`
Expected: FAIL — no `POST /feedback` route.

- [ ] **Step 3: Add the submit endpoint**

Append to `src/cvp/routers/feedback.py`:

```python
@router.post("/feedback", response_class=HTMLResponse)
def submit_feedback(
    body: str = Form(...),
    page_url: str = Form(...),
    user: CurrentUser = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    cleaned_body = body.strip()
    if not cleaned_body:
        raise HTTPException(status_code=400, detail="Feedback body is required.")
    if len(cleaned_body) > FEEDBACK_BODY_MAX:
        raise HTTPException(
            status_code=400,
            detail=f"Feedback body must be {FEEDBACK_BODY_MAX} characters or fewer.",
        )
    assert_plain_text(cleaned_body, field_name="Feedback")

    if user.group_id is None:
        raise HTTPException(status_code=400, detail="Submitting user has no group.")

    fb = Feedback(
        author_user_id=user.id,
        author_group_id=user.group_id,
        page_url=_clean_page_url(page_url),
        body=cleaned_body,
    )
    db.add(fb)
    db.commit()
    db.refresh(fb)

    return _render_widget_panel(db, user)


def _render_widget_panel(db: Session, user: CurrentUser) -> HTMLResponse:
    """Render the popover panel HTML: new-feedback form + author's threads."""
    threads = (
        db.query(Feedback)
        .filter(
            Feedback.author_user_id == user.id,
            Feedback.deleted_at.is_(None),
        )
        .order_by(Feedback.created_at.desc())
        .all()
    )
    html = templates.get_template("_feedback_widget_panel.html").render(
        threads=threads,
        feedback_body_max=FEEDBACK_BODY_MAX,
    )
    return HTMLResponse(html)
```

Create `src/cvp/templates/_feedback_widget_panel.html`:

```html
<div class="space-y-4">
  <form hx-post="/feedback"
        hx-target="#feedback-panel-body"
        hx-swap="outerHTML"
        data-feedback-form
        class="space-y-2">
    <textarea name="body" rows="4" required maxlength="{{ feedback_body_max }}"
              placeholder="Tell us what's working, what's not, what you'd like to see…"
              class="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none"></textarea>
    <input type="hidden" name="page_url" value="" data-feedback-page-url />
    <div class="flex justify-end">
      <button type="submit"
              class="rounded-md bg-indigo-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-indigo-500">
        Send feedback
      </button>
    </div>
  </form>

  <div id="feedback-panel-body" class="space-y-2">
    <h4 class="text-xs font-semibold uppercase tracking-wide text-gray-500">My feedback</h4>
    {% if not threads %}
    <p class="text-sm text-gray-500">No feedback yet.</p>
    {% else %}
    <ul class="divide-y divide-gray-100 border border-gray-100 rounded-md">
      {% for fb in threads %}
      <li class="p-2 hover:bg-gray-50 cursor-pointer"
          data-feedback-open="{{ fb.id }}">
        <div class="flex items-center justify-between">
          {% set pill = {
            'pending':   'bg-gray-100 text-gray-800',
            'reviewing': 'bg-blue-100 text-blue-800',
            'backlog':   'bg-yellow-100 text-yellow-800',
            'canceled':  'bg-red-100 text-red-800',
            'done':      'bg-green-100 text-green-800',
          } %}
          <span class="inline-flex items-center rounded-full {{ pill[fb.status] }} px-2 py-0.5 text-xs font-medium">
            {{ fb.status }}
          </span>
          <span class="text-xs text-gray-500">{{ fb.created_at.strftime('%b %d') }}</span>
        </div>
        <p class="mt-1 text-sm text-gray-800 line-clamp-2">{{ fb.body[:80] }}{% if fb.body|length > 80 %}…{% endif %}</p>
      </li>
      {% endfor %}
    </ul>
    {% endif %}
  </div>
</div>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_feedback_router.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
uv run ruff format .
uv run ruff format --check .
git add src/cvp/routers/feedback.py src/cvp/templates/_feedback_widget_panel.html tests/test_feedback_router.py
git commit -m "feat: POST /feedback endpoint + widget panel template"
```

---

## Task 7: Widget GET (list own threads)

**Files:**
- Modify: `src/cvp/routers/feedback.py`
- Test: `tests/test_feedback_router.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_feedback_router.py`:

```python
def test_widget_get_returns_panel_with_own_threads(client_and_db):
    client, db = client_and_db
    db.add(
        Feedback(
            id="f1",
            author_user_id="u1",
            author_group_id="g1",
            page_url="/x",
            body="mine",
        )
    )
    db.add(
        Feedback(
            id="f2",
            author_user_id="u2",
            author_group_id="g1",
            page_url="/x",
            body="not mine",
        )
    )
    db.commit()
    resp = client.get("/feedback/widget")
    assert resp.status_code == 200
    assert "mine" in resp.text
    assert "not mine" not in resp.text


def test_widget_get_hides_authors_soft_deleted(client_and_db):
    from datetime import datetime, timezone

    client, db = client_and_db
    db.add(
        Feedback(
            id="f1",
            author_user_id="u1",
            author_group_id="g1",
            page_url="/x",
            body="visible-body",
        )
    )
    db.add(
        Feedback(
            id="f2",
            author_user_id="u1",
            author_group_id="g1",
            page_url="/x",
            body="deleted-body",
            deleted_at=datetime.now(timezone.utc),
            deleted_by_user_id="u1",
        )
    )
    db.commit()
    resp = client.get("/feedback/widget")
    assert "visible-body" in resp.text
    assert "deleted-body" not in resp.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_feedback_router.py::test_widget_get_returns_panel_with_own_threads -v`
Expected: 404 — no GET route exists.

- [ ] **Step 3: Add the GET endpoint**

Append to `src/cvp/routers/feedback.py`:

```python
@router.get("/feedback/widget", response_class=HTMLResponse)
def get_widget_panel(
    user: CurrentUser = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    return _render_widget_panel(db, user)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_feedback_router.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
uv run ruff format .
uv run ruff format --check .
git add src/cvp/routers/feedback.py tests/test_feedback_router.py
git commit -m "feat: GET /feedback/widget renders author's threads"
```

---

## Task 8: View single thread (GET /feedback/{id})

**Files:**
- Modify: `src/cvp/routers/feedback.py`
- Create: `src/cvp/templates/_feedback_thread.html`
- Test: `tests/test_feedback_router.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_feedback_router.py`:

```python
def test_get_thread_as_author_succeeds(client_and_db):
    client, db = client_and_db
    db.add(
        Feedback(
            id="fA",
            author_user_id="u1",
            author_group_id="g1",
            page_url="/x",
            body="my-body",
        )
    )
    db.commit()
    resp = client.get("/feedback/fA")
    assert resp.status_code == 200
    assert "my-body" in resp.text


def test_get_thread_as_other_user_403(client_and_db):
    client, db = client_and_db
    db.add(
        Feedback(
            id="fB",
            author_user_id="u2",
            author_group_id="g1",
            page_url="/x",
            body="other-body",
        )
    )
    db.commit()
    resp = client.get("/feedback/fB")
    assert resp.status_code == 403


def test_get_thread_404_when_missing(client_and_db):
    client, _db = client_and_db
    resp = client.get("/feedback/does-not-exist")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_feedback_router.py -v -k thread`
Expected: 3 failures (no route).

- [ ] **Step 3: Implement the endpoint and template**

Append to `src/cvp/routers/feedback.py`:

```python
def _load_feedback_or_404(feedback_id: str, db: Session) -> Feedback:
    fb = db.get(Feedback, feedback_id)
    if fb is None:
        raise HTTPException(status_code=404, detail="Feedback not found")
    return fb


def _render_thread(db: Session, user: CurrentUser, fb: Feedback, *, is_admin_view: bool) -> HTMLResponse:
    comments = (
        db.query(FeedbackComment)
        .filter(FeedbackComment.feedback_id == fb.id)
        .order_by(FeedbackComment.created_at.asc())
        .all()
    )
    user_ids = {fb.author_user_id} | {c.author_user_id for c in comments}
    users_by_id = {
        u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()
    }
    html = templates.get_template("_feedback_thread.html").render(
        feedback=fb,
        comments=comments,
        users=users_by_id,
        current_user=user,
        is_admin_view=is_admin_view,
        comment_body_max=COMMENT_BODY_MAX,
        allowed_statuses=ALLOWED_STATUSES,
    )
    return HTMLResponse(html)


@router.get("/feedback/{feedback_id}", response_class=HTMLResponse)
def get_thread(
    feedback_id: str,
    user: CurrentUser = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    fb = _load_feedback_or_404(feedback_id, db)
    if not _check_feedback_access(user, fb):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return _render_thread(db, user, fb, is_admin_view=False)
```

Create `src/cvp/templates/_feedback_thread.html`:

```html
<div class="space-y-4" id="feedback-thread-{{ feedback.id }}">
  {% set pill = {
    'pending':   'bg-gray-100 text-gray-800',
    'reviewing': 'bg-blue-100 text-blue-800',
    'backlog':   'bg-yellow-100 text-yellow-800',
    'canceled':  'bg-red-100 text-red-800',
    'done':      'bg-green-100 text-green-800',
  } %}

  <div class="flex items-center gap-2">
    <span class="inline-flex items-center rounded-full {{ pill[feedback.status] }} px-2 py-0.5 text-xs font-medium">
      {{ feedback.status }}
    </span>
    <span class="text-xs text-gray-500">{{ feedback.created_at.strftime('%b %d, %Y %H:%M') }}</span>
    <span class="text-xs text-gray-400">·</span>
    <a href="{{ feedback.page_url }}" class="text-xs text-indigo-600 hover:underline" rel="noopener noreferrer">{{ feedback.page_url }}</a>
  </div>

  <div class="rounded-md border border-gray-200 bg-gray-50 p-3 text-sm">
    <p class="font-medium text-gray-900">{{ users[feedback.author_user_id].display_name if feedback.author_user_id in users else 'Unknown' }}</p>
    {% if feedback.deleted_at %}
      {% if feedback.deleted_by_user_id == feedback.author_user_id %}
      <p class="italic text-gray-400">Removed by author</p>
      {% else %}
      <p class="italic text-gray-400">Removed by admin</p>
      {% endif %}
    {% else %}
    <p class="mt-1 whitespace-pre-wrap text-gray-800">{{ feedback.body }}</p>
    {% endif %}
  </div>

  <div class="space-y-2">
    {% for c in comments %}
    <div class="rounded-md border border-gray-100 p-2 text-sm">
      <div class="flex items-center justify-between">
        <span class="font-medium text-gray-900">{{ users[c.author_user_id].display_name if c.author_user_id in users else 'Unknown' }}</span>
        <span class="text-xs text-gray-500">{{ c.created_at.strftime('%b %d, %Y %H:%M') }}</span>
      </div>
      {% if c.deleted_at %}
        {% if c.deleted_by_user_id == c.author_user_id %}
        <p class="italic text-gray-400">Removed by author</p>
        {% else %}
        <p class="italic text-gray-400">Removed by admin</p>
        {% endif %}
      {% else %}
      <p class="mt-1 whitespace-pre-wrap text-gray-800">{{ c.body }}</p>
      {% endif %}
      {% if not c.deleted_at and (c.author_user_id == current_user.id or current_user.system_role == 'system_admin') %}
      <button type="button"
              class="mt-1 text-xs text-red-600 hover:underline"
              data-feedback-delete-comment="{{ c.id }}">Delete</button>
      {% endif %}
    </div>
    {% endfor %}
  </div>

  <form hx-post="/feedback/{{ feedback.id }}/comments"
        hx-target="#feedback-thread-{{ feedback.id }}"
        hx-swap="outerHTML"
        class="flex gap-2">
    <textarea name="body" rows="2" required maxlength="{{ comment_body_max }}"
              placeholder="Reply…"
              class="flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none"></textarea>
    <button type="submit"
            class="rounded-md bg-indigo-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-indigo-500">Post</button>
  </form>

  {% if is_admin_view %}
  <div class="rounded-md border border-gray-200 p-3">
    <h4 class="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">Status</h4>
    <div class="flex flex-wrap gap-2">
      {% for status in allowed_statuses %}
      <form method="post" action="/admin/system/feedback/{{ feedback.id }}/status" class="inline">
        <input type="hidden" name="status" value="{{ status }}" />
        <button type="submit"
                class="rounded-md px-3 py-1 text-xs font-medium
                       {% if status == feedback.status %}bg-indigo-600 text-white{% else %}bg-white border border-gray-300 text-gray-700 hover:bg-gray-50{% endif %}">
          {{ status }}
        </button>
      </form>
      {% endfor %}
    </div>
  </div>
  {% if not feedback.deleted_at %}
  <button type="button"
          class="text-xs text-red-600 hover:underline"
          data-feedback-delete="{{ feedback.id }}">Delete feedback</button>
  {% endif %}
  {% endif %}
</div>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_feedback_router.py -v -k thread`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
uv run ruff format .
uv run ruff format --check .
git add src/cvp/routers/feedback.py src/cvp/templates/_feedback_thread.html tests/test_feedback_router.py
git commit -m "feat: GET /feedback/{id} renders single thread"
```

---

## Task 9: Post comment endpoint

**Files:**
- Modify: `src/cvp/routers/feedback.py`
- Test: `tests/test_feedback_router.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_feedback_router.py`:

```python
def test_post_comment_as_author_succeeds(client_and_db):
    client, db = client_and_db
    db.add(
        Feedback(
            id="fC",
            author_user_id="u1",
            author_group_id="g1",
            page_url="/x",
            body="parent",
        )
    )
    db.commit()
    resp = client.post("/feedback/fC/comments", data={"body": "a reply"})
    assert resp.status_code == 200
    comments = db.query(FeedbackComment).all()
    assert len(comments) == 1
    assert comments[0].body == "a reply"
    assert comments[0].author_user_id == "u1"


def test_post_comment_rejects_html(client_and_db):
    client, db = client_and_db
    db.add(
        Feedback(
            id="fD",
            author_user_id="u1",
            author_group_id="g1",
            page_url="/x",
            body="parent",
        )
    )
    db.commit()
    resp = client.post("/feedback/fD/comments", data={"body": "<img onerror=x>"})
    assert resp.status_code == 400


def test_post_comment_rejects_oversize(client_and_db):
    client, db = client_and_db
    db.add(
        Feedback(
            id="fE",
            author_user_id="u1",
            author_group_id="g1",
            page_url="/x",
            body="parent",
        )
    )
    db.commit()
    resp = client.post("/feedback/fE/comments", data={"body": "a" * 2001})
    assert resp.status_code == 400


def test_post_comment_on_others_thread_403(client_and_db):
    client, db = client_and_db
    db.add(
        Feedback(
            id="fF",
            author_user_id="u2",
            author_group_id="g1",
            page_url="/x",
            body="not mine",
        )
    )
    db.commit()
    resp = client.post("/feedback/fF/comments", data={"body": "hi"})
    assert resp.status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_feedback_router.py -v -k post_comment`
Expected: failures (no route).

- [ ] **Step 3: Add the endpoint**

Append to `src/cvp/routers/feedback.py`:

```python
@router.post("/feedback/{feedback_id}/comments", response_class=HTMLResponse)
def post_comment(
    feedback_id: str,
    body: str = Form(...),
    user: CurrentUser = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    fb = _load_feedback_or_404(feedback_id, db)
    if not _check_feedback_access(user, fb):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    cleaned = body.strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="Comment body is required.")
    if len(cleaned) > COMMENT_BODY_MAX:
        raise HTTPException(
            status_code=400,
            detail=f"Comment must be {COMMENT_BODY_MAX} characters or fewer.",
        )
    assert_plain_text(cleaned, field_name="Comment")

    c = FeedbackComment(
        feedback_id=fb.id,
        author_user_id=user.id,
        body=cleaned,
    )
    db.add(c)
    db.commit()
    db.refresh(fb)
    return _render_thread(db, user, fb, is_admin_view=user.system_role == "system_admin")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_feedback_router.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
uv run ruff format .
uv run ruff format --check .
git add src/cvp/routers/feedback.py tests/test_feedback_router.py
git commit -m "feat: POST /feedback/{id}/comments endpoint"
```

---

## Task 10: Mark-read endpoint

**Files:**
- Modify: `src/cvp/routers/feedback.py`
- Test: `tests/test_feedback_router.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_feedback_router.py`:

```python
def test_mark_read_as_author_updates_author_cursor(client_and_db):
    client, db = client_and_db
    db.add(
        Feedback(
            id="fR",
            author_user_id="u1",
            author_group_id="g1",
            page_url="/x",
            body="b",
        )
    )
    db.commit()
    resp = client.post("/feedback/fR/read")
    assert resp.status_code == 200
    db.expire_all()
    fb = db.get(Feedback, "fR")
    assert fb.last_author_read_at is not None
    assert fb.last_admin_read_at is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_feedback_router.py::test_mark_read_as_author_updates_author_cursor -v`
Expected: 404.

- [ ] **Step 3: Add the endpoint**

Append to `src/cvp/routers/feedback.py`:

```python
from fastapi.responses import JSONResponse  # add at top of file if missing


@router.post("/feedback/{feedback_id}/read", response_class=JSONResponse)
def mark_read(
    feedback_id: str,
    user: CurrentUser = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    fb = _load_feedback_or_404(feedback_id, db)
    if not _check_feedback_access(user, fb):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    now = datetime.now(tz=timezone.utc)
    if user.system_role == "system_admin":
        fb.last_admin_read_at = now
    else:
        fb.last_author_read_at = now
    db.commit()
    return JSONResponse({"ok": True})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_feedback_router.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
uv run ruff format .
uv run ruff format --check .
git add src/cvp/routers/feedback.py tests/test_feedback_router.py
git commit -m "feat: POST /feedback/{id}/read updates read cursor"
```

---

## Task 11: Soft-delete feedback + soft-delete comment endpoints

**Files:**
- Modify: `src/cvp/routers/feedback.py`
- Test: `tests/test_feedback_router.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_feedback_router.py`:

```python
def test_soft_delete_feedback_as_author(client_and_db):
    client, db = client_and_db
    db.add(
        Feedback(
            id="fS",
            author_user_id="u1",
            author_group_id="g1",
            page_url="/x",
            body="b",
        )
    )
    db.commit()
    resp = client.post("/feedback/fS/delete")
    assert resp.status_code == 200
    db.expire_all()
    fb = db.get(Feedback, "fS")
    assert fb.deleted_at is not None
    assert fb.deleted_by_user_id == "u1"


def test_soft_delete_feedback_as_other_403(client_and_db):
    client, db = client_and_db
    db.add(
        Feedback(
            id="fS2",
            author_user_id="u2",
            author_group_id="g1",
            page_url="/x",
            body="b",
        )
    )
    db.commit()
    resp = client.post("/feedback/fS2/delete")
    assert resp.status_code == 403


def test_soft_delete_comment_as_comment_author(client_and_db):
    client, db = client_and_db
    db.add(
        Feedback(
            id="fC2",
            author_user_id="u1",
            author_group_id="g1",
            page_url="/x",
            body="b",
        )
    )
    db.add(
        FeedbackComment(id="cD", feedback_id="fC2", author_user_id="u1", body="mine")
    )
    db.commit()
    resp = client.post("/feedback/comments/cD/delete")
    assert resp.status_code == 200
    db.expire_all()
    c = db.get(FeedbackComment, "cD")
    assert c.deleted_at is not None
    assert c.deleted_by_user_id == "u1"


def test_soft_delete_other_user_comment_403(client_and_db):
    client, db = client_and_db
    db.add(
        Feedback(
            id="fC3",
            author_user_id="u1",
            author_group_id="g1",
            page_url="/x",
            body="b",
        )
    )
    db.add(
        FeedbackComment(id="cE", feedback_id="fC3", author_user_id="u2", body="theirs")
    )
    db.commit()
    resp = client.post("/feedback/comments/cE/delete")
    assert resp.status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_feedback_router.py -v -k delete`
Expected: 404s.

- [ ] **Step 3: Add the endpoints**

Append to `src/cvp/routers/feedback.py`:

```python
@router.post("/feedback/{feedback_id}/delete", response_class=JSONResponse)
def delete_feedback(
    feedback_id: str,
    user: CurrentUser = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    fb = _load_feedback_or_404(feedback_id, db)
    if not _check_feedback_access(user, fb):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    if fb.deleted_at is None:
        fb.deleted_at = datetime.now(tz=timezone.utc)
        fb.deleted_by_user_id = user.id
        db.commit()
    return JSONResponse({"ok": True})


@router.post("/feedback/comments/{comment_id}/delete", response_class=JSONResponse)
def delete_comment(
    comment_id: str,
    user: CurrentUser = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    c = db.get(FeedbackComment, comment_id)
    if c is None:
        raise HTTPException(status_code=404, detail="Comment not found")
    is_admin = user.system_role == "system_admin"
    if not is_admin and c.author_user_id != user.id:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    if c.deleted_at is None:
        c.deleted_at = datetime.now(tz=timezone.utc)
        c.deleted_by_user_id = user.id
        db.commit()
    return JSONResponse({"ok": True})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_feedback_router.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
uv run ruff format .
uv run ruff format --check .
git add src/cvp/routers/feedback.py tests/test_feedback_router.py
git commit -m "feat: soft-delete feedback and comments"
```

---

## Task 12: Unread-state helpers + badge endpoint

**Files:**
- Modify: `src/cvp/routers/feedback.py`
- Create: `src/cvp/templates/_feedback_unread_badge.html`
- Test: `tests/test_feedback_router.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_feedback_router.py`:

```python
def test_unread_badge_no_dot_when_no_feedback(client_and_db):
    client, _db = client_and_db
    resp = client.get("/feedback/unread")
    assert resp.status_code == 200
    assert "feedback-badge-dot" not in resp.text


def test_unread_badge_shows_dot_after_admin_comment(client_and_db):
    from datetime import datetime, timezone

    client, db = client_and_db
    # Author's own feedback with admin comment that's newer than last_author_read_at
    db.add(
        Feedback(
            id="fU",
            author_user_id="u1",
            author_group_id="g1",
            page_url="/x",
            body="b",
            last_author_read_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        )
    )
    # Add an admin-authored comment after that cursor
    db.add(
        User(
            id="admin",
            email="a@x",
            display_name="Admin",
            system_role="system_admin",
            group_id="g1",
            is_active=True,
        )
    )
    db.add(
        FeedbackComment(
            id="cU",
            feedback_id="fU",
            author_user_id="admin",
            body="thanks for the feedback",
        )
    )
    db.commit()
    resp = client.get("/feedback/unread")
    assert "feedback-badge-dot" in resp.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_feedback_router.py -v -k unread`
Expected: 404s.

- [ ] **Step 3: Add the helpers, endpoint, and template**

Append to `src/cvp/routers/feedback.py`:

```python
from sqlalchemy import and_, or_  # add to existing sqlalchemy imports


def has_author_unread(db: Session, user_id: str) -> bool:
    """Return True if the user has any feedback with admin activity newer than their read cursor."""
    rows = (
        db.query(Feedback)
        .filter(
            Feedback.author_user_id == user_id,
            Feedback.deleted_at.is_(None),
        )
        .all()
    )
    for fb in rows:
        cursor = fb.last_author_read_at
        if fb.status_changed_at is not None and (cursor is None or fb.status_changed_at > cursor):
            return True
        latest_other = (
            db.query(FeedbackComment)
            .filter(
                FeedbackComment.feedback_id == fb.id,
                FeedbackComment.author_user_id != fb.author_user_id,
                FeedbackComment.deleted_at.is_(None),
            )
            .order_by(FeedbackComment.created_at.desc())
            .first()
        )
        if latest_other is not None and (cursor is None or latest_other.created_at > cursor):
            return True
    return False


def count_admin_unread(db: Session) -> int:
    """Return the count of feedback rows with non-admin activity newer than the admin read cursor."""
    rows = (
        db.query(Feedback)
        .filter(Feedback.deleted_at.is_(None))
        .all()
    )
    n = 0
    for fb in rows:
        cursor = fb.last_admin_read_at
        if cursor is None or fb.created_at > cursor:
            n += 1
            continue
        latest_non_admin = (
            db.query(FeedbackComment)
            .join(User, User.id == FeedbackComment.author_user_id)
            .filter(
                FeedbackComment.feedback_id == fb.id,
                FeedbackComment.deleted_at.is_(None),
                User.system_role != "system_admin",
            )
            .order_by(FeedbackComment.created_at.desc())
            .first()
        )
        if latest_non_admin is not None and latest_non_admin.created_at > cursor:
            n += 1
    return n


@router.get("/feedback/unread", response_class=HTMLResponse)
def get_unread_badge(
    user: CurrentUser = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    show_dot = has_author_unread(db, user.id)
    html = templates.get_template("_feedback_unread_badge.html").render(show_dot=show_dot)
    return HTMLResponse(html)
```

Create `src/cvp/templates/_feedback_unread_badge.html`:

```html
{% if show_dot %}
<span id="feedback-badge-dot"
      class="absolute top-1 right-1 inline-block h-2.5 w-2.5 rounded-full bg-red-500 ring-2 ring-white"></span>
{% else %}
<span id="feedback-badge-dot" class="hidden"></span>
{% endif %}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_feedback_router.py -v -k unread`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
uv run ruff format .
uv run ruff format --check .
git add src/cvp/routers/feedback.py src/cvp/templates/_feedback_unread_badge.html tests/test_feedback_router.py
git commit -m "feat: unread-badge endpoint and helpers"
```

---

## Task 13: Floating widget shell + base.html include + JS handlers

**Files:**
- Create: `src/cvp/templates/_feedback_widget.html`
- Modify: `src/cvp/templates/base.html`
- Modify: `src/cvp/static/app.js`

- [ ] **Step 1: Create the widget shell**

Write `src/cvp/templates/_feedback_widget.html`:

```html
<div data-feedback-widget class="fixed bottom-4 right-4 z-50">
  <button type="button"
          data-feedback-toggle
          aria-label="Feedback"
          class="relative inline-flex h-12 w-12 items-center justify-center rounded-full bg-indigo-600 text-white shadow-lg hover:bg-indigo-500">
    <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
      <path stroke-linecap="round" stroke-linejoin="round" d="M7 8h10M7 12h6m4 8l-4-4H6a2 2 0 01-2-2V6a2 2 0 012-2h12a2 2 0 012 2v8a2 2 0 01-2 2h-1l-2 4z" />
    </svg>
    <span hx-get="/feedback/unread"
          hx-trigger="load, every 60s"
          hx-swap="outerHTML"></span>
  </button>

  <div data-feedback-popover
       class="hidden absolute bottom-14 right-0 w-96 max-h-[480px] overflow-y-auto rounded-lg bg-white p-4 shadow-xl ring-1 ring-black/5">
    <div class="flex items-center justify-between mb-3">
      <h3 class="text-sm font-semibold text-gray-900">Feedback</h3>
      <button type="button" data-feedback-close class="text-gray-400 hover:text-gray-600">&times;</button>
    </div>
    <div data-feedback-panel-root
         hx-get="/feedback/widget"
         hx-trigger="revealed"
         hx-swap="innerHTML">
      <p class="text-sm text-gray-500">Loading…</p>
    </div>
  </div>
</div>
```

- [ ] **Step 2: Include the widget in `base.html`**

In `src/cvp/templates/base.html`, before the closing `</body>`:

```html
  {% if user and request.url.path not in ("/", "/login", "/register", "/splash") %}
  {% include "_feedback_widget.html" %}
  {% endif %}
</body>
```

- [ ] **Step 3: Wire delegated click + page_url handlers in `static/app.js`**

Append the following to `src/cvp/static/app.js` (place at end of file or after the existing delegated-click block):

```javascript
// Feedback widget: open/close popover
document.addEventListener('click', function (e) {
    var toggle = e.target.closest('[data-feedback-toggle]');
    if (toggle) {
        var pop = toggle.parentElement.querySelector('[data-feedback-popover]');
        if (pop) pop.classList.toggle('hidden');
        return;
    }
    var closeBtn = e.target.closest('[data-feedback-close]');
    if (closeBtn) {
        var p = closeBtn.closest('[data-feedback-popover]');
        if (p) p.classList.add('hidden');
        return;
    }
    var openRow = e.target.closest('[data-feedback-open]');
    if (openRow) {
        var id = openRow.dataset.feedbackOpen;
        htmx.ajax('GET', '/feedback/' + encodeURIComponent(id), {
            target: openRow,
            swap: 'outerHTML',
        });
        return;
    }
    var delFb = e.target.closest('[data-feedback-delete]');
    if (delFb) {
        if (!confirm('Delete this feedback?')) return;
        var fid = delFb.dataset.feedbackDelete;
        htmx.ajax('POST', '/feedback/' + encodeURIComponent(fid) + '/delete', {
            target: 'body',
            swap: 'none',
        });
        location.reload();
        return;
    }
    var delC = e.target.closest('[data-feedback-delete-comment]');
    if (delC) {
        if (!confirm('Delete this comment?')) return;
        var cid = delC.dataset.feedbackDeleteComment;
        htmx.ajax('POST', '/feedback/comments/' + encodeURIComponent(cid) + '/delete', {
            target: 'body',
            swap: 'none',
        });
        location.reload();
    }
});

// Feedback widget: populate the hidden page_url field whenever a feedback form is rendered
document.addEventListener('htmx:afterSwap', function (e) {
    var inputs = e.detail.elt && e.detail.elt.querySelectorAll
        ? e.detail.elt.querySelectorAll('[data-feedback-page-url]')
        : [];
    inputs.forEach(function (input) {
        input.value = window.location.pathname + window.location.search;
    });
});

// Also populate immediately on initial render of any panel content already in the DOM
document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-feedback-page-url]').forEach(function (input) {
        input.value = window.location.pathname + window.location.search;
    });
});
```

- [ ] **Step 4: Manual smoke test**

Run: `uv run dev` (in another shell). Open `http://localhost:8000/dashboard` while logged in as any user. Confirm:
- A round indigo button appears at the bottom right.
- Clicking it opens the popover, which fetches `/feedback/widget` and shows the form.
- Submitting a short body creates a row and the list updates.
- The hidden `page_url` form value reflects `window.location.pathname`.
- The "Removed by author" tombstone appears after soft-deleting (page reloads after the action).

Kill the dev server.

- [ ] **Step 5: Commit**

```bash
uv run ruff format .
uv run ruff format --check .
git add src/cvp/templates/_feedback_widget.html src/cvp/templates/base.html src/cvp/static/app.js
git commit -m "feat: floating feedback widget UI and delegated handlers"
```

---

## Task 14: Admin router skeleton + list view

**Files:**
- Create: `src/cvp/routers/admin/feedback.py`
- Create: `src/cvp/templates/admin/system/feedback.html`
- Create: `tests/test_admin_feedback_router.py`
- Modify: `src/cvp/main.py`

- [ ] **Step 1: Write the failing tests**

Write `tests/test_admin_feedback_router.py`:

```python
"""Integration tests for the admin feedback router."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cvp.models_auth  # noqa: F401
import cvp.models_feedback  # noqa: F401
from cvp.dependencies import CurrentUser, require_active_user, require_system_admin
from cvp.models import Base
from cvp.models_auth import Group, User
from cvp.models_feedback import Feedback


def _session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


@pytest.fixture
def admin_client():
    from cvp.db import get_db
    from cvp.main import app

    db = _session()
    g = Group(id="g1", name="Internal", kind="internal")
    admin = User(
        id="admin",
        email="a@test.com",
        display_name="Admin",
        system_role="system_admin",
        group_id="g1",
        is_active=True,
    )
    u = User(
        id="u1",
        email="u@test.com",
        display_name="User",
        system_role="internal_user",
        group_id="g1",
        is_active=True,
    )
    db.add_all([g, admin, u])
    db.commit()

    admin_cu = CurrentUser(
        id="admin", email="a@test.com", system_role="system_admin",
        group_id="g1", group_kind="internal",
    )

    async def fake_active():
        return admin_cu

    async def fake_admin():
        return admin_cu

    def override_db():
        yield db

    app.dependency_overrides[require_active_user] = fake_active
    app.dependency_overrides[require_system_admin] = fake_admin
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as c:
        yield c, db
    app.dependency_overrides.clear()


@pytest.fixture
def nonadmin_client():
    from cvp.db import get_db
    from cvp.main import app

    db = _session()
    g = Group(id="g1", name="Internal", kind="internal")
    u = User(
        id="u1",
        email="u@test.com",
        display_name="User",
        system_role="internal_admin",  # internal_admin is not system_admin
        group_id="g1",
        is_active=True,
    )
    db.add_all([g, u])
    db.commit()

    cu = CurrentUser(
        id="u1", email="u@test.com", system_role="internal_admin",
        group_id="g1", group_kind="internal",
    )

    async def fake_active():
        return cu

    def override_db():
        yield db

    app.dependency_overrides[require_active_user] = fake_active
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as c:
        yield c, db
    app.dependency_overrides.clear()


def test_admin_list_renders(admin_client):
    client, db = admin_client
    db.add(
        Feedback(
            id="f1",
            author_user_id="u1",
            author_group_id="g1",
            page_url="/x",
            body="hello-from-user",
        )
    )
    db.commit()
    resp = client.get("/admin/system/feedback")
    assert resp.status_code == 200
    assert "hello-from-user" in resp.text


def test_admin_list_filters_by_status(admin_client):
    client, db = admin_client
    db.add(
        Feedback(
            id="f1", author_user_id="u1", author_group_id="g1",
            page_url="/x", body="pending-one", status="pending",
        )
    )
    db.add(
        Feedback(
            id="f2", author_user_id="u1", author_group_id="g1",
            page_url="/x", body="done-one", status="done",
        )
    )
    db.commit()
    resp = client.get("/admin/system/feedback?status=pending")
    assert "pending-one" in resp.text
    assert "done-one" not in resp.text


def test_internal_admin_gets_403(nonadmin_client):
    client, _db = nonadmin_client
    resp = client.get("/admin/system/feedback")
    assert resp.status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_admin_feedback_router.py -v`
Expected: 404s/500s — no admin feedback router exists.

- [ ] **Step 3: Implement the admin router and list template**

Write `src/cvp/routers/admin/feedback.py`:

```python
"""Admin feedback router: list, filter/sort, change status, soft-delete, submit-as."""

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from cvp.db import get_db
from cvp.dependencies import CurrentUser, require_system_admin
from cvp.models_auth import Group, User
from cvp.models_feedback import ALLOWED_STATUSES, Feedback
from cvp.routers.feedback import (
    FEEDBACK_BODY_MAX,
    _clean_page_url,
    _load_feedback_or_404,
    _render_thread,
    count_admin_unread,
)
from cvp.text_validation import assert_plain_text

router = APIRouter(prefix="/admin/system/feedback")

BASE_DIR = Path(__file__).parent.parent.parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")

ALLOWED_SORTS = {"created_at", "status", "group", "author"}


@router.get("", response_class=HTMLResponse)
def list_feedback(
    request: Request,
    status: list[str] = Query(default_factory=list),
    group_id: str | None = Query(default=None),
    author_q: str | None = Query(default=None),
    include_deleted: bool = Query(default=False),
    sort: str = Query(default="created_at"),
    order: str = Query(default="desc"),
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    q = db.query(Feedback)
    if not include_deleted:
        q = q.filter(Feedback.deleted_at.is_(None))
    valid_statuses = [s for s in status if s in ALLOWED_STATUSES]
    if valid_statuses:
        q = q.filter(Feedback.status.in_(valid_statuses))
    if group_id:
        q = q.filter(Feedback.author_group_id == group_id)
    if author_q:
        like = f"%{author_q.lower()}%"
        author_ids = [
            u.id
            for u in db.query(User)
            .filter(
                (User.email.ilike(like))
                | (User.display_name.ilike(like))
            )
            .all()
        ]
        if not author_ids:
            q = q.filter(Feedback.author_user_id == "__none__")
        else:
            q = q.filter(Feedback.author_user_id.in_(author_ids))

    sort_key = sort if sort in ALLOWED_SORTS else "created_at"
    column = {
        "created_at": Feedback.created_at,
        "status": Feedback.status,
        "group": Feedback.author_group_id,
        "author": Feedback.author_user_id,
    }[sort_key]
    q = q.order_by(column.desc() if order != "asc" else column.asc())

    rows = q.all()
    user_ids = {r.author_user_id for r in rows}
    users_by_id = {
        u.id: u
        for u in db.query(User).filter(User.id.in_(user_ids)).all()
    } if user_ids else {}
    group_ids = {r.author_group_id for r in rows}
    groups_by_id = {
        g.id: g
        for g in db.query(Group).filter(Group.id.in_(group_ids)).all()
    } if group_ids else {}
    all_groups = db.query(Group).order_by(Group.name.asc()).all()

    html = templates.get_template("admin/system/feedback.html").render(
        request=request,
        user=user,
        panel_title="System",
        breadcrumbs=[{"label": "Feedback", "url": "/admin/system/feedback"}],
        rows=rows,
        users=users_by_id,
        groups=groups_by_id,
        all_groups=all_groups,
        selected_statuses=valid_statuses,
        selected_group_id=group_id,
        author_q=author_q or "",
        include_deleted=include_deleted,
        sort=sort_key,
        order=order,
        allowed_statuses=ALLOWED_STATUSES,
        unread_count=count_admin_unread(db),
    )
    return HTMLResponse(html)
```

Create `src/cvp/templates/admin/system/feedback.html`:

```html
{% extends "admin/base.html" %}
{% block title %}Feedback{% endblock %}
{% block sidebar %}
<a href="/admin/system/" class="block px-3 py-2 rounded text-sm text-slate-300 hover:bg-slate-700 hover:text-white">Dashboard</a>
<a href="/admin/system/users" class="block px-3 py-2 rounded text-sm text-slate-300 hover:bg-slate-700 hover:text-white">Users</a>
<a href="/admin/system/groups" class="block px-3 py-2 rounded text-sm text-slate-300 hover:bg-slate-700 hover:text-white">Groups</a>
<a href="/admin/system/matters" class="block px-3 py-2 rounded text-sm text-slate-300 hover:bg-slate-700 hover:text-white">Matters</a>
<a href="/admin/system/feedback" class="block px-3 py-2 rounded text-sm bg-slate-700 text-white">
  Feedback{% if unread_count %} <span class="ml-1 inline-flex items-center rounded-full bg-red-500 px-1.5 py-0.5 text-xs">{{ unread_count }}</span>{% endif %}
</a>
<a href="/admin/system/audit" class="block px-3 py-2 rounded text-sm text-slate-300 hover:bg-slate-700 hover:text-white">Audit Log</a>
<a href="/admin/vision-models" class="block px-3 py-2 rounded text-sm text-slate-300 hover:bg-slate-700 hover:text-white">Vision Models</a>
{% endblock %}
{% block content %}
<div class="flex items-center justify-between mb-4">
  <h1 class="text-2xl font-bold text-gray-900">Feedback</h1>
  <a href="/admin/system/feedback/new"
     class="rounded-md bg-indigo-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-indigo-500">New feedback</a>
</div>

<form method="get" action="/admin/system/feedback" class="mb-4 flex flex-wrap items-end gap-3 bg-white p-3 rounded shadow-sm">
  <div>
    <label class="block text-xs font-medium text-gray-600">Status</label>
    <div class="flex flex-wrap gap-2 mt-1">
      {% for s in allowed_statuses %}
      <label class="inline-flex items-center gap-1 text-sm">
        <input type="checkbox" name="status" value="{{ s }}"
               {% if s in selected_statuses %}checked{% endif %} />
        {{ s }}
      </label>
      {% endfor %}
    </div>
  </div>
  <div>
    <label class="block text-xs font-medium text-gray-600">Group</label>
    <select name="group_id" class="mt-1 rounded-md border border-gray-300 px-2 py-1 text-sm">
      <option value="">All groups</option>
      {% for g in all_groups %}
      <option value="{{ g.id }}" {% if g.id == selected_group_id %}selected{% endif %}>{{ g.name }}</option>
      {% endfor %}
    </select>
  </div>
  <div>
    <label class="block text-xs font-medium text-gray-600">Author</label>
    <input type="text" name="author_q" value="{{ author_q }}" placeholder="email or name"
           class="mt-1 rounded-md border border-gray-300 px-2 py-1 text-sm" />
  </div>
  <label class="inline-flex items-center gap-1 text-sm">
    <input type="checkbox" name="include_deleted" value="1" {% if include_deleted %}checked{% endif %} />
    Include deleted
  </label>
  <input type="hidden" name="sort" value="{{ sort }}" />
  <input type="hidden" name="order" value="{{ order }}" />
  <button type="submit" class="rounded-md bg-slate-800 px-3 py-1.5 text-sm font-semibold text-white">Apply</button>
</form>

<table class="min-w-full bg-white rounded shadow-sm">
  <thead class="bg-gray-50 text-xs uppercase tracking-wide text-gray-500">
    <tr>
      {% set sort_link = '/admin/system/feedback?sort=%s&order=%s' %}
      <th class="px-3 py-2 text-left"><a href="{{ sort_link % ('status', 'asc' if sort == 'status' and order == 'desc' else 'desc') }}">Status</a></th>
      <th class="px-3 py-2 text-left"><a href="{{ sort_link % ('author', 'asc' if sort == 'author' and order == 'desc' else 'desc') }}">Author</a></th>
      <th class="px-3 py-2 text-left">Page</th>
      <th class="px-3 py-2 text-left">Excerpt</th>
      <th class="px-3 py-2 text-left"><a href="{{ sort_link % ('created_at', 'asc' if sort == 'created_at' and order == 'desc' else 'desc') }}">Created</a></th>
    </tr>
  </thead>
  <tbody>
    {% set pill = {
      'pending':   'bg-gray-100 text-gray-800',
      'reviewing': 'bg-blue-100 text-blue-800',
      'backlog':   'bg-yellow-100 text-yellow-800',
      'canceled':  'bg-red-100 text-red-800',
      'done':      'bg-green-100 text-green-800',
    } %}
    {% for fb in rows %}
    <tr class="border-t border-gray-100 hover:bg-gray-50 cursor-pointer"
        data-feedback-admin-row="{{ fb.id }}">
      <td class="px-3 py-2"><span class="inline-flex items-center rounded-full {{ pill[fb.status] }} px-2 py-0.5 text-xs font-medium">{{ fb.status }}</span></td>
      <td class="px-3 py-2 text-sm">
        {{ users[fb.author_user_id].email if fb.author_user_id in users else 'Unknown' }}
        <div class="text-xs text-gray-500">{{ groups[fb.author_group_id].name if fb.author_group_id in groups else '' }}</div>
      </td>
      <td class="px-3 py-2 text-sm"><a href="{{ fb.page_url }}" target="_blank" rel="noopener noreferrer" class="text-indigo-600 hover:underline">{{ fb.page_url }}</a></td>
      <td class="px-3 py-2 text-sm">{{ fb.body[:120] }}{% if fb.body|length > 120 %}…{% endif %}</td>
      <td class="px-3 py-2 text-xs text-gray-500">{{ fb.created_at.strftime('%b %d, %Y') }}</td>
    </tr>
    {% endfor %}
  </tbody>
</table>
{% endblock %}
```

The `<tr>` uses `data-feedback-admin-row="{{ fb.id }}"` rather than `onclick=` — CSP blocks inline event handlers. Wire the row-click in `src/cvp/static/app.js`:

```javascript
// Admin feedback list: row click navigates to detail
document.addEventListener('click', function (e) {
    var row = e.target.closest('[data-feedback-admin-row]');
    if (row) {
        window.location.href = '/admin/system/feedback/' + encodeURIComponent(row.dataset.feedbackAdminRow);
    }
});
```

Register the router in `src/cvp/main.py` — find the admin router include block (look for `admin_system`, etc.) and add:

```python
from cvp.routers.admin import feedback as admin_feedback
# ...
app.include_router(admin_feedback.router, dependencies=[Depends(require_active_user)])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_admin_feedback_router.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
uv run ruff format .
uv run ruff format --check .
git add src/cvp/routers/admin/feedback.py src/cvp/templates/admin/system/feedback.html src/cvp/static/app.js src/cvp/main.py tests/test_admin_feedback_router.py
git commit -m "feat: admin feedback list with filters and sort"
```

---

## Task 15: Admin thread detail view

**Files:**
- Modify: `src/cvp/routers/admin/feedback.py`
- Create: `src/cvp/templates/admin/system/feedback_detail.html`
- Test: `tests/test_admin_feedback_router.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_admin_feedback_router.py`:

```python
def test_admin_detail_renders(admin_client):
    client, db = admin_client
    db.add(
        Feedback(
            id="fX", author_user_id="u1", author_group_id="g1",
            page_url="/x", body="detail-body",
        )
    )
    db.commit()
    resp = client.get("/admin/system/feedback/fX")
    assert resp.status_code == 200
    assert "detail-body" in resp.text
    # Admin sidebar should expose status buttons
    for s in ("pending", "reviewing", "backlog", "canceled", "done"):
        assert s in resp.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_admin_feedback_router.py::test_admin_detail_renders -v`
Expected: 404.

- [ ] **Step 3: Add the endpoint and template**

Append to `src/cvp/routers/admin/feedback.py`:

```python
@router.get("/{feedback_id}", response_class=HTMLResponse)
def admin_thread(
    feedback_id: str,
    request: Request,
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    fb = _load_feedback_or_404(feedback_id, db)
    inner_html = _render_thread(db, user, fb, is_admin_view=True).body.decode("utf-8")
    html = templates.get_template("admin/system/feedback_detail.html").render(
        request=request,
        user=user,
        panel_title="System",
        breadcrumbs=[
            {"label": "Feedback", "url": "/admin/system/feedback"},
            {"label": fb.id[:8], "url": f"/admin/system/feedback/{fb.id}"},
        ],
        feedback=fb,
        thread_html=inner_html,
        unread_count=count_admin_unread(db),
    )
    return HTMLResponse(html)
```

Create `src/cvp/templates/admin/system/feedback_detail.html`:

```html
{% extends "admin/base.html" %}
{% block title %}Feedback Detail{% endblock %}
{% block sidebar %}
<a href="/admin/system/" class="block px-3 py-2 rounded text-sm text-slate-300 hover:bg-slate-700 hover:text-white">Dashboard</a>
<a href="/admin/system/users" class="block px-3 py-2 rounded text-sm text-slate-300 hover:bg-slate-700 hover:text-white">Users</a>
<a href="/admin/system/groups" class="block px-3 py-2 rounded text-sm text-slate-300 hover:bg-slate-700 hover:text-white">Groups</a>
<a href="/admin/system/matters" class="block px-3 py-2 rounded text-sm text-slate-300 hover:bg-slate-700 hover:text-white">Matters</a>
<a href="/admin/system/feedback" class="block px-3 py-2 rounded text-sm bg-slate-700 text-white">
  Feedback{% if unread_count %} <span class="ml-1 inline-flex items-center rounded-full bg-red-500 px-1.5 py-0.5 text-xs">{{ unread_count }}</span>{% endif %}
</a>
<a href="/admin/system/audit" class="block px-3 py-2 rounded text-sm text-slate-300 hover:bg-slate-700 hover:text-white">Audit Log</a>
<a href="/admin/vision-models" class="block px-3 py-2 rounded text-sm text-slate-300 hover:bg-slate-700 hover:text-white">Vision Models</a>
{% endblock %}
{% block content %}
<div class="bg-white rounded shadow-sm p-4">
  {{ thread_html | safe }}
</div>
{% endblock %}
```

(Justification for the single `| safe` here: `thread_html` is the rendered output of `_render_thread()`, which itself ran through Jinja autoescape on every untrusted field. We're inserting already-escaped HTML, not raw user input.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_admin_feedback_router.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
uv run ruff format .
uv run ruff format --check .
git add src/cvp/routers/admin/feedback.py src/cvp/templates/admin/system/feedback_detail.html tests/test_admin_feedback_router.py
git commit -m "feat: admin feedback detail page"
```

---

## Task 16: Admin change status endpoint

**Files:**
- Modify: `src/cvp/routers/admin/feedback.py`
- Test: `tests/test_admin_feedback_router.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_admin_feedback_router.py`:

```python
def test_change_status_updates_row(admin_client):
    client, db = admin_client
    db.add(
        Feedback(
            id="fS",
            author_user_id="u1",
            author_group_id="g1",
            page_url="/x",
            body="b",
        )
    )
    db.commit()
    resp = client.post(
        "/admin/system/feedback/fS/status",
        data={"status": "reviewing"},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)
    db.expire_all()
    fb = db.get(Feedback, "fS")
    assert fb.status == "reviewing"
    assert fb.status_changed_at is not None
    assert fb.status_changed_by_user_id == "admin"


def test_change_status_rejects_invalid(admin_client):
    client, db = admin_client
    db.add(
        Feedback(
            id="fS2", author_user_id="u1", author_group_id="g1",
            page_url="/x", body="b",
        )
    )
    db.commit()
    resp = client.post(
        "/admin/system/feedback/fS2/status",
        data={"status": "totally-fake"},
    )
    assert resp.status_code == 400


def test_change_status_internal_admin_forbidden(nonadmin_client):
    client, db = nonadmin_client
    db.add(
        Feedback(
            id="fS3", author_user_id="u1", author_group_id="g1",
            page_url="/x", body="b",
        )
    )
    db.commit()
    resp = client.post("/admin/system/feedback/fS3/status", data={"status": "done"})
    assert resp.status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_admin_feedback_router.py -v -k change_status`
Expected: 404s.

- [ ] **Step 3: Add the endpoint**

Append to `src/cvp/routers/admin/feedback.py`:

```python
@router.post("/{feedback_id}/status")
def change_status(
    feedback_id: str,
    status: str = Form(...),
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    if status not in ALLOWED_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    fb = _load_feedback_or_404(feedback_id, db)
    fb.status = status
    fb.status_changed_at = datetime.now(tz=timezone.utc)
    fb.status_changed_by_user_id = user.id
    db.commit()
    return RedirectResponse(
        url=f"/admin/system/feedback/{fb.id}", status_code=303
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_admin_feedback_router.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
uv run ruff format .
uv run ruff format --check .
git add src/cvp/routers/admin/feedback.py tests/test_admin_feedback_router.py
git commit -m "feat: admin POST /admin/system/feedback/{id}/status"
```

---

## Task 17: Admin submit-on-behalf endpoint and new-feedback form

**Files:**
- Modify: `src/cvp/routers/admin/feedback.py`
- Test: `tests/test_admin_feedback_router.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_admin_feedback_router.py`:

```python
def test_admin_submit_as_other_user(admin_client):
    client, db = admin_client
    resp = client.post(
        "/admin/system/feedback/new-as",
        data={"body": "speaking for u1", "page_url": "/admin/system/feedback", "author_user_id": "u1"},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)
    rows = db.query(Feedback).all()
    assert len(rows) == 1
    assert rows[0].author_user_id == "u1"
    assert rows[0].author_group_id == "g1"  # snapshot from u1's group


def test_admin_submit_rejects_unknown_user(admin_client):
    client, _db = admin_client
    resp = client.post(
        "/admin/system/feedback/new-as",
        data={"body": "x", "page_url": "/x", "author_user_id": "nope"},
    )
    assert resp.status_code == 400


def test_admin_submit_rejects_html_body(admin_client):
    client, _db = admin_client
    resp = client.post(
        "/admin/system/feedback/new-as",
        data={"body": "<svg onload=x>", "page_url": "/x", "author_user_id": "u1"},
    )
    assert resp.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_admin_feedback_router.py -v -k admin_submit`
Expected: 404s.

- [ ] **Step 3: Add the endpoint**

Append to `src/cvp/routers/admin/feedback.py`:

```python
@router.get("/new", response_class=HTMLResponse)
def admin_new_form(
    request: Request,
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    users = db.query(User).filter(User.is_active.is_(True)).order_by(User.email.asc()).all()
    html = templates.get_template("admin/system/feedback_new.html").render(
        request=request,
        user=user,
        panel_title="System",
        breadcrumbs=[
            {"label": "Feedback", "url": "/admin/system/feedback"},
            {"label": "New", "url": "/admin/system/feedback/new"},
        ],
        users=users,
        feedback_body_max=FEEDBACK_BODY_MAX,
        unread_count=count_admin_unread(db),
    )
    return HTMLResponse(html)


@router.post("/new-as")
def admin_submit_as(
    body: str = Form(...),
    page_url: str = Form(...),
    author_user_id: str = Form(...),
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    author = db.get(User, author_user_id)
    if author is None or not author.is_active or author.group_id is None:
        raise HTTPException(status_code=400, detail="Author must be an active user with a group.")

    cleaned = body.strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="Feedback body is required.")
    if len(cleaned) > FEEDBACK_BODY_MAX:
        raise HTTPException(status_code=400, detail="Feedback body too long.")
    assert_plain_text(cleaned, field_name="Feedback")

    fb = Feedback(
        author_user_id=author.id,
        author_group_id=author.group_id,
        page_url=_clean_page_url(page_url),
        body=cleaned,
    )
    db.add(fb)
    db.commit()
    db.refresh(fb)
    return RedirectResponse(url=f"/admin/system/feedback/{fb.id}", status_code=303)
```

Create `src/cvp/templates/admin/system/feedback_new.html`:

```html
{% extends "admin/base.html" %}
{% block title %}New Feedback{% endblock %}
{% block sidebar %}
<a href="/admin/system/" class="block px-3 py-2 rounded text-sm text-slate-300 hover:bg-slate-700 hover:text-white">Dashboard</a>
<a href="/admin/system/users" class="block px-3 py-2 rounded text-sm text-slate-300 hover:bg-slate-700 hover:text-white">Users</a>
<a href="/admin/system/groups" class="block px-3 py-2 rounded text-sm text-slate-300 hover:bg-slate-700 hover:text-white">Groups</a>
<a href="/admin/system/matters" class="block px-3 py-2 rounded text-sm text-slate-300 hover:bg-slate-700 hover:text-white">Matters</a>
<a href="/admin/system/feedback" class="block px-3 py-2 rounded text-sm bg-slate-700 text-white">
  Feedback{% if unread_count %} <span class="ml-1 inline-flex items-center rounded-full bg-red-500 px-1.5 py-0.5 text-xs">{{ unread_count }}</span>{% endif %}
</a>
<a href="/admin/system/audit" class="block px-3 py-2 rounded text-sm text-slate-300 hover:bg-slate-700 hover:text-white">Audit Log</a>
<a href="/admin/vision-models" class="block px-3 py-2 rounded text-sm text-slate-300 hover:bg-slate-700 hover:text-white">Vision Models</a>
{% endblock %}
{% block content %}
<h1 class="text-2xl font-bold text-gray-900 mb-4">New feedback</h1>
<form method="post" action="/admin/system/feedback/new-as" class="space-y-3 bg-white p-4 rounded shadow-sm max-w-2xl">
  <div>
    <label class="block text-xs font-medium text-gray-600">Author</label>
    <select name="author_user_id" required class="mt-1 w-full rounded-md border border-gray-300 px-2 py-1 text-sm">
      {% for u in users %}
      <option value="{{ u.id }}" {% if u.id == user.id %}selected{% endif %}>{{ u.email }} — {{ u.display_name }}</option>
      {% endfor %}
    </select>
  </div>
  <div>
    <label class="block text-xs font-medium text-gray-600">Page URL</label>
    <input type="text" name="page_url" value="/" class="mt-1 w-full rounded-md border border-gray-300 px-2 py-1 text-sm" />
  </div>
  <div>
    <label class="block text-xs font-medium text-gray-600">Body</label>
    <textarea name="body" rows="6" required maxlength="{{ feedback_body_max }}"
              class="mt-1 w-full rounded-md border border-gray-300 px-2 py-1 text-sm"></textarea>
  </div>
  <div class="flex justify-end">
    <button type="submit" class="rounded-md bg-indigo-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-indigo-500">Create</button>
  </div>
</form>
{% endblock %}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_admin_feedback_router.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
uv run ruff format .
uv run ruff format --check .
git add src/cvp/routers/admin/feedback.py src/cvp/templates/admin/system/feedback_new.html tests/test_admin_feedback_router.py
git commit -m "feat: admin submit-on-behalf endpoint and form"
```

---

## Task 18: Sidebar nav link with unread chip on every admin/system page

**Files:**
- Modify: `src/cvp/templates/admin/system/dashboard.html`
- Modify: `src/cvp/templates/admin/system/users.html`
- Modify: `src/cvp/templates/admin/system/groups.html`
- Modify: `src/cvp/templates/admin/system/matters.html`
- Modify: `src/cvp/templates/admin/system/audit.html`
- Modify: `src/cvp/templates/admin/system/user_detail.html`
- Modify: `src/cvp/templates/admin/system/group_detail.html`
- Modify: `src/cvp/routers/admin/system.py` (pass `unread_count` from `count_admin_unread`)

- [ ] **Step 1: Wire `count_admin_unread` into the existing admin/system routes**

For each route in `src/cvp/routers/admin/system.py` that renders one of the templates above, add `unread_count=count_admin_unread(db)` to the render context. Import at top:

```python
from cvp.routers.feedback import count_admin_unread
```

Use the editor's search to find every `templates.TemplateResponse(...)` or `templates.get_template(...).render(...)` call in `src/cvp/routers/admin/system.py` and add `unread_count=count_admin_unread(db)` to the kwargs. If a route doesn't already have `db: Session = Depends(get_db)`, add it.

- [ ] **Step 2: Add the Feedback link to each `{% block sidebar %}`**

For each of the listed templates, locate the sidebar block (the `<a>` list between `{% block sidebar %}` and `{% endblock %}`). Insert this link after the "Matters" link and before "Audit Log":

```html
<a href="/admin/system/feedback" class="block px-3 py-2 rounded text-sm text-slate-300 hover:bg-slate-700 hover:text-white">
  Feedback{% if unread_count %} <span class="ml-1 inline-flex items-center rounded-full bg-red-500 px-1.5 py-0.5 text-xs">{{ unread_count }}</span>{% endif %}
</a>
```

Use `Edit` per file. Confirm by viewing the modified file diff that the link is now present.

- [ ] **Step 3: Manual smoke test**

Run: `uv run dev`. Log in as a system_admin. Confirm:
- `/admin/system/` shows the Feedback link in the sidebar with no chip when there's no unread.
- Submit a feedback as a non-admin user (via the floating widget).
- Refresh `/admin/system/`: the link now shows a red chip with `1`.
- Click into `/admin/system/feedback`, then into the detail page; the badge polling continues to work.
- Stop the dev server.

- [ ] **Step 4: Commit**

```bash
uv run ruff format .
uv run ruff format --check .
git add src/cvp/templates/admin/system/ src/cvp/routers/admin/system.py
git commit -m "feat: admin sidebar Feedback link with unread chip"
```

---

## Task 19: BACKLOG entries + final lint and test suite

**Files:**
- Modify: `docs/BACKLOG.md`

- [ ] **Step 1: Append BACKLOG entries**

Open `docs/BACKLOG.md` and append (preserve whatever structure exists; create the file if it does not — but it should):

```markdown
## Feedback feature deferrals

- **Feedback attachments** — allow optional multiple screenshot uploads on a feedback submission and on each comment. Reuse the evidence-file upload pattern. Deferred from the v0 feedback feature.
- **Apply `assert_plain_text()` to other free-form text inputs** — the feedback feature ships a reusable plain-text validator in `src/cvp/text_validation.py`. Audit existing user-input fields (matter name + description, item name + description, room name, profile display name, item comments, vision model display name, any other free-form `Text`/`String` columns receiving user input) and add the validator at each write endpoint. Roll out per-field so each adoption can be reviewed against the field's existing data (e.g., a matter description that already contains `<` would 400 on next edit).
```

- [ ] **Step 2: Run lint + full test suite**

Run in parallel:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
```

Expected: ruff check passes, format --check reports `0 files would be reformatted`, pytest reports all tests passing (existing + the new feedback tests).

If any test outside the feedback suite has been broken by changes (most likely candidate: anything that asserted on admin sidebar HTML), fix the specific test — do not skip or weaken it.

- [ ] **Step 3: Final commit**

```bash
git add docs/BACKLOG.md
git commit -m "docs: backlog entries for feedback attachments and plain-text rollout"
```

- [ ] **Step 4: Manual end-to-end smoke**

`uv run dev`. With a non-admin user logged in:
1. Visit `/dashboard`. The floating button appears.
2. Open the widget. Type "Test feedback". Submit. Confirm the "My feedback" list updates with the new entry.
3. Click the entry. The thread expands. Post a comment "Test comment". Confirm it appears.
4. Soft-delete the comment via the Delete link. Confirm "Removed by author" appears.
5. Log out, log in as system_admin.
6. Visit `/admin/system/`. The sidebar shows "Feedback" with a `1` chip.
7. Click into `/admin/system/feedback`. The list shows the test feedback.
8. Click into the detail page. Change status to "reviewing", then "done". Verify the pill updates.
9. Click "New feedback" from the list page. Choose another user as author. Submit "Filed on behalf of you." Verify redirect to the new detail page and that the row belongs to that user.

Stop the dev server.

---

## Self-review checklist (executed by plan author)

- **Spec coverage:** every spec requirement has a task. The 5 status values are in `ALLOWED_STATUSES` (Task 2), the access model is enforced via `_check_feedback_access` (Task 4), the page URL cleaner is in Task 5, body length caps and HTML rejection are in Tasks 6, 9, and 17, the widget is in Task 13, the admin list with filter/sort is in Task 14, the admin detail with status sidebar is in Task 15, status change is in Task 16, submit-on-behalf is in Task 17, and the sidebar link / unread chip is in Task 18.
- **Placeholders:** none.
- **Type consistency:** `Feedback`, `FeedbackComment`, `ALLOWED_STATUSES`, `_clean_page_url`, `_check_feedback_access`, `_load_feedback_or_404`, `_render_thread`, `_render_widget_panel`, `has_author_unread`, `count_admin_unread` use the same names everywhere they appear.
