# Claim Nickname Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every claim a required, group-unique nickname defined at creation and shown as the primary label wherever claims are listed.

**Architecture:** Add a `nickname` column to the `Claim` model with a case-insensitive unique index scoped to `owner_group_id`. A shared validation helper enforces required/length/uniqueness in the create and edit routers. Existing rows are backfilled (`Claim <id[:8]>`) by an Alembic migration and by the legacy `migrate-db` copy path. Templates switch to leading with the nickname.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.x, Alembic, Jinja2, pytest.

## Global Constraints

- Type hints everywhere; modern syntax (`X | None`, `list[str]`).
- Nickname is **internal only** — it must NOT appear in `report/preview.html` or `report/pdf.html` (attorney work product stays keyed on `policyholder_name`).
- No new dependencies. No inline JS event handlers in templates.
- Run `uv run ruff format .` and confirm `uv run ruff format --check .` reports zero reformatted files before every commit. CI enforces format.
- Uniqueness scope: case-insensitive, per `Claim.owner_group_id`. Nickname trimmed, non-empty, ≤ 100 chars (length validated in the router, not the DB).
- Run tests with `uv run pytest`.

---

### Task 1: Add `nickname` to the `Claim` model + unique index

**Files:**
- Modify: `src/claimos/models.py` (the `Claim` class, lines 32–63)
- Test: `tests/test_claim_nickname_model.py` (create)

**Interfaces:**
- Produces: `Claim.nickname: Mapped[str]` (NOT NULL) and a unique index `uq_claims_group_nickname_ci` on `(owner_group_id, lower(nickname))`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_claim_nickname_model.py`:

```python
"""The Claim model exposes a required nickname with a case-insensitive
per-group unique index."""

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from claimos.models import Base, Claim


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def test_nickname_column_exists_and_not_null(session):
    cols = {c["name"]: c for c in inspect(session.bind).get_columns("claims")}
    assert "nickname" in cols
    assert cols["nickname"]["nullable"] is False


def test_unique_index_is_case_insensitive_per_group(session):
    session.add(Claim(id="c1", owner_group_id="g1", nickname="Smith File"))
    session.commit()
    # Same group, different case -> collides at the DB level.
    session.add(Claim(id="c2", owner_group_id="g1", nickname="smith file"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_same_nickname_allowed_in_different_group(session):
    session.add(Claim(id="c1", owner_group_id="g1", nickname="Smith File"))
    session.add(Claim(id="c2", owner_group_id="g2", nickname="Smith File"))
    session.commit()  # must not raise
    assert session.query(Claim).count() == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_claim_nickname_model.py -v`
Expected: FAIL — `nickname` column missing / index absent (`AttributeError` or the not-null/uniqueness assertions fail).

- [ ] **Step 3: Add the column and index**

In `src/claimos/models.py`, add `text` to the top-level `sqlalchemy` import block (lines 6–16), so it reads:

```python
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
```

In the `Claim` class, immediately after `__tablename__ = "claims"` (line 35), add:

```python
    __table_args__ = (
        Index(
            "uq_claims_group_nickname_ci",
            "owner_group_id",
            text("lower(nickname)"),
            unique=True,
        ),
    )
```

And add the column — place it right after the `id` column (after line 37):

```python
    nickname: Mapped[str] = mapped_column(String, nullable=False)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_claim_nickname_model.py -v`
Expected: PASS (all three tests).

- [ ] **Step 5: Format and commit**

```bash
uv run ruff format . && uv run ruff format --check .
git add src/claimos/models.py tests/test_claim_nickname_model.py
git commit -m "feat: add required group-unique nickname column to Claim"
```

---

### Task 2: Alembic migration — add column, backfill, enforce NOT NULL, create index

**Files:**
- Create: `migrations/versions/20260723_<hash>_claim_nickname.py` (generated by Alembic, then edited)
- Test: `tests/test_claim_nickname_migration.py` (create)

**Interfaces:**
- Consumes: `Claim.nickname` and the `uq_claims_group_nickname_ci` index from Task 1.
- Produces: a migration whose `down_revision` is `515c6c0e7711` (current head) that backfills existing rows to `Claim <id[:8]>`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_claim_nickname_migration.py`:

```python
"""Upgrading across the nickname migration backfills existing claims to a
non-null 'Claim <id[:8]>' value and creates the unique index."""

import pathlib

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine, inspect

PREV_REVISION = "515c6c0e7711"  # retail_value_shipping (head before nickname)


def _cfg(db_url: str) -> AlembicConfig:
    cfg = AlembicConfig("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def test_backfill_and_index(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    db_url = f"sqlite:///{tmp_path}/nick.db"
    import claimos.config as config_module

    monkeypatch.setattr(config_module.settings, "database_url", db_url)
    cfg = _cfg(db_url)

    # Migrate up to the revision *before* nickname, then seed a claim with no nickname.
    command.upgrade(cfg, PREV_REVISION)
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    with engine.begin() as c:
        c.exec_driver_sql(
            "INSERT INTO claims (id, owner_group_id) VALUES ('abcdef1234567890', 'g1')"
        )

    # Now run the nickname migration.
    command.upgrade(cfg, "head")

    with engine.connect() as c:
        nickname = c.exec_driver_sql(
            "SELECT nickname FROM claims WHERE id = 'abcdef1234567890'"
        ).scalar_one()
    assert nickname == "Claim abcdef12"

    indexes = {ix["name"] for ix in inspect(engine).get_indexes("claims")}
    assert "uq_claims_group_nickname_ci" in indexes
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_claim_nickname_migration.py -v`
Expected: FAIL — there is no migration adding `nickname`, so either the column is missing after upgrade or the head still equals `PREV_REVISION`.

- [ ] **Step 3: Generate the migration skeleton**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib uv run alembic revision -m "claim nickname"`

This creates a new file under `migrations/versions/`. Note its path (call it `<newfile>`).

- [ ] **Step 4: Write the migration body**

Replace the body of `<newfile>` with (keep the auto-generated `revision`/`down_revision` header that Alembic wrote — `down_revision` must be `'515c6c0e7711'`):

```python
"""claim nickname

Revision ID: <keep generated>
Revises: 515c6c0e7711
Create Date: <keep generated>

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "<keep generated>"
down_revision: Union[str, None] = "515c6c0e7711"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add nullable so existing rows survive the ALTER.
    op.add_column("claims", sa.Column("nickname", sa.String(), nullable=True))
    # 2. Backfill every existing row to a unique, non-null placeholder.
    op.execute("UPDATE claims SET nickname = 'Claim ' || substr(id, 1, 8)")
    # 3. Enforce NOT NULL now that no nulls remain (batch mode for SQLite).
    with op.batch_alter_table("claims") as batch_op:
        batch_op.alter_column("nickname", existing_type=sa.String(), nullable=False)
    # 4. Case-insensitive per-group unique index.
    op.create_index(
        "uq_claims_group_nickname_ci",
        "claims",
        ["owner_group_id", sa.text("lower(nickname)")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_claims_group_nickname_ci", table_name="claims")
    with op.batch_alter_table("claims") as batch_op:
        batch_op.drop_column("nickname")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_claim_nickname_migration.py -v`
Expected: PASS.

- [ ] **Step 6: Confirm no other migration test broke**

Run: `uv run pytest tests/test_seed.py -v`
Expected: PASS (migrations still upgrade cleanly to head).

- [ ] **Step 7: Format and commit**

```bash
uv run ruff format . && uv run ruff format --check .
git add migrations/versions/ tests/test_claim_nickname_migration.py
git commit -m "feat: migration backfills nickname and adds unique index"
```

---

### Task 3: Backfill nickname in the legacy `migrate-db` copy path

**Files:**
- Modify: `src/claimos/migrate_db.py` (`_copy_table`, lines 81–124)
- Test: `tests/test_migrate_db.py` (modify `_make_claimos_db` + add a test)

**Interfaces:**
- Consumes: nothing new.
- Produces: every claim row copied from legacy gets `nickname = f"Claim {id[:8]}"` (source `matters` has no nickname column).

- [ ] **Step 1: Write the failing test**

In `tests/test_migrate_db.py`, update `_make_claimos_db` so the target `claims` table has a `nickname` column (add it to the CREATE TABLE at lines 45–48):

```python
        c.exec_driver_sql(
            "CREATE TABLE claims (id TEXT PRIMARY KEY, policyholder_name TEXT, "
            "owner_group_id TEXT, status TEXT, nickname TEXT)"
        )
```

Then add a new test at the end of the file:

```python
def test_migrate_backfills_nickname(tmp_path):
    src = f"sqlite:///{tmp_path / 'legacy.db'}"
    tgt = f"sqlite:///{tmp_path / 'claimos.db'}"
    _make_legacy_db(src)
    _make_claimos_db(tgt)

    migrate(src, tgt, only_tables=["groups", "claims", "rooms"])

    eng = sa.create_engine(tgt)
    with eng.connect() as c:
        nickname = c.exec_driver_sql(
            "SELECT nickname FROM claims WHERE id = 'm1'"
        ).scalar_one()
    assert nickname == "Claim m1"  # legacy id 'm1' -> 'Claim ' + 'm1'[:8]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_migrate_db.py::test_migrate_backfills_nickname -v`
Expected: FAIL — `nickname` is NULL for the copied row (the copy path never sets it).

- [ ] **Step 3: Inject nickname for the claims table in `_copy_table`**

In `src/claimos/migrate_db.py`, inside `_copy_table`, in the row loop (lines 92–94), after building `d`, add a claims-specific derive. Replace:

```python
    for row in rows:
        d = {renames.get(k, k): v for k, v in dict(row).items()}
        out.append(d)
```

with:

```python
    for row in rows:
        d = {renames.get(k, k): v for k, v in dict(row).items()}
        # Legacy `matters` has no nickname; every ClaimOS claim requires a
        # unique, non-null one. Derive a placeholder from the id (specialists
        # rename later). Mirrors the Alembic backfill.
        if target_table == "claims" and not d.get("nickname"):
            d["nickname"] = f"Claim {str(d['id'])[:8]}"
        out.append(d)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_migrate_db.py -v`
Expected: PASS (new test passes; `test_migrate_copies_and_remaps` still passes — it only selects `id, policyholder_name`).

- [ ] **Step 5: Format and commit**

```bash
uv run ruff format . && uv run ruff format --check .
git add src/claimos/migrate_db.py tests/test_migrate_db.py
git commit -m "feat: backfill claim nickname in legacy migrate-db copy"
```

---

### Task 4: Nickname validation helper

**Files:**
- Modify: `src/claimos/routers/claims.py` (add helper near the top, after line 43)
- Test: `tests/test_claim_nickname_validation.py` (create)

**Interfaces:**
- Consumes: `Claim` (imported at `claims.py:20-28`), `func` (imported at `claims.py:9`).
- Produces:
  `validate_nickname(db, raw: str, owner_group_id: str | None, exclude_claim_id: str | None = None) -> tuple[str, str | None]`
  — returns `(cleaned_nickname, error_message_or_None)`. Later tasks call it in the create and update routers.

- [ ] **Step 1: Write the failing test**

Create `tests/test_claim_nickname_validation.py`:

```python
"""Unit tests for validate_nickname: required, length cap, case-insensitive
per-group uniqueness, and self-exclusion on edit."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from claimos.models import Base, Claim
from claimos.routers.claims import validate_nickname


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    s.add(Claim(id="c1", owner_group_id="g1", nickname="Smith File"))
    s.commit()
    yield s
    s.close()


def test_strips_and_returns_clean_value(db):
    cleaned, err = validate_nickname(db, "  Jones File  ", "g1")
    assert cleaned == "Jones File"
    assert err is None


def test_empty_is_rejected(db):
    cleaned, err = validate_nickname(db, "   ", "g1")
    assert err == "Nickname is required."


def test_too_long_is_rejected(db):
    cleaned, err = validate_nickname(db, "x" * 101, "g1")
    assert err == "Nickname must be 100 characters or fewer."


def test_case_insensitive_duplicate_in_same_group_rejected(db):
    cleaned, err = validate_nickname(db, "smith file", "g1")
    assert err == "That nickname is already used in your group."


def test_same_nickname_other_group_allowed(db):
    cleaned, err = validate_nickname(db, "Smith File", "g2")
    assert err is None


def test_self_excluded_on_edit(db):
    # Re-saving c1 with its own (case-varied) nickname must pass.
    cleaned, err = validate_nickname(db, "SMITH FILE", "g1", exclude_claim_id="c1")
    assert err is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_claim_nickname_validation.py -v`
Expected: FAIL — `ImportError: cannot import name 'validate_nickname'`.

- [ ] **Step 3: Implement the helper**

In `src/claimos/routers/claims.py`, after the `LOSS_EVENTS` line (line 43), add:

```python
NICKNAME_MAX_LEN = 100


def validate_nickname(
    db,
    raw: str,
    owner_group_id: str | None,
    exclude_claim_id: str | None = None,
) -> tuple[str, str | None]:
    """Clean and validate a claim nickname.

    Returns (cleaned_nickname, error_message). error_message is None when valid.
    Uniqueness is case-insensitive and scoped to owner_group_id; exclude_claim_id
    lets an edit skip the claim's own row.
    """
    nickname = (raw or "").strip()
    if not nickname:
        return nickname, "Nickname is required."
    if len(nickname) > NICKNAME_MAX_LEN:
        return nickname, "Nickname must be 100 characters or fewer."
    query = db.query(Claim).filter(
        Claim.owner_group_id == owner_group_id,
        func.lower(Claim.nickname) == nickname.lower(),
    )
    if exclude_claim_id is not None:
        query = query.filter(Claim.id != exclude_claim_id)
    if db.query(query.exists()).scalar():
        return nickname, "That nickname is already used in your group."
    return nickname, None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_claim_nickname_validation.py -v`
Expected: PASS (all six tests).

- [ ] **Step 5: Format and commit**

```bash
uv run ruff format . && uv run ruff format --check .
git add src/claimos/routers/claims.py tests/test_claim_nickname_validation.py
git commit -m "feat: add validate_nickname helper"
```

---

### Task 5: Wire nickname into claim creation

**Files:**
- Modify: `src/claimos/routers/claims.py` (`new_claim_form` lines 46–58, `create_claim` lines 61–120)
- Modify: `src/claimos/templates/claim_new.html` (add field + error banner)
- Test: `tests/test_claim_nickname_create.py` (create)

**Interfaces:**
- Consumes: `validate_nickname` from Task 4.
- Produces: `POST /claims` requires a valid nickname; on failure re-renders `claim_new.html` (HTTP 200) with `error` and preserved `form` values; on success persists `claim.nickname`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_claim_nickname_create.py`:

```python
"""POST /claims enforces a required, group-unique nickname."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import claimos.models_auth  # noqa: F401
from claimos.models import Base, Claim
from claimos.models_auth import Group, User


@pytest.fixture
def seeded_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    s.add(Group(id="ig", name="Internal", kind="internal"))
    s.add(User(id="ia", email="ia@t.com", display_name="A", system_role="internal_admin", group_id="ig"))
    s.commit()
    yield s
    s.close()


@pytest.fixture
def client(seeded_db, monkeypatch):
    from claimos.dependencies import CurrentUser, require_active_user
    from claimos.main import app

    async def mock_user():
        return CurrentUser(
            id="ia", email="ia@t.com", system_role="internal_admin",
            group_id="ig", group_kind="internal",
        )

    app.dependency_overrides[require_active_user] = mock_user
    monkeypatch.setattr("claimos.routers.claims.SessionLocal", lambda: seeded_db)
    yield TestClient(app, follow_redirects=False)
    app.dependency_overrides.clear()


def test_create_with_nickname_succeeds(client, seeded_db):
    resp = client.post("/claims", data={"nickname": "Jones File", "policyholder_name": "Jones"})
    assert resp.status_code == 303  # redirect to the new claim
    row = seeded_db.query(Claim).filter(func.lower(Claim.nickname) == "jones file").one()
    assert row.owner_group_id == "ig"


def test_create_without_nickname_rejected(client, seeded_db):
    resp = client.post("/claims", data={"nickname": "   ", "policyholder_name": "X"})
    assert resp.status_code == 200  # re-rendered form, not a redirect
    assert "Nickname is required." in resp.text
    assert seeded_db.query(Claim).count() == 0


def test_create_duplicate_nickname_rejected(client, seeded_db):
    seeded_db.add(Claim(id="c1", owner_group_id="ig", nickname="Smith File"))
    seeded_db.commit()
    resp = client.post("/claims", data={"nickname": "smith file"})
    assert resp.status_code == 200
    assert "already used in your group" in resp.text
    assert seeded_db.query(Claim).count() == 1  # no second row created
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_claim_nickname_create.py -v`
Expected: FAIL — `create_claim` has no `nickname` param, so it is ignored; the required/duplicate cases are not enforced and no error text appears.

- [ ] **Step 3: Add the `nickname` param, validation, and error re-render to `create_claim`**

In `src/claimos/routers/claims.py`, add a `nickname` form param to `create_claim` — insert it as the first `Form` param (after `user`, before `firm_name`, around line 66):

```python
    nickname: str = Form(default=""),
```

Then, at the very start of the `db = SessionLocal()` try block (right after line 82 `try:` and before `claim = Claim(`), validate and short-circuit on error:

```python
        nickname_clean, nickname_error = validate_nickname(db, nickname, user.group_id)
        if nickname_error:
            return templates.TemplateResponse(
                request=request,
                name="claim_new.html",
                context={
                    "loss_types": LOSS_TYPES,
                    "loss_events": LOSS_EVENTS,
                    "user": user,
                    "error": nickname_error,
                    "form": {
                        "nickname": nickname,
                        "firm_name": firm_name,
                        "attorney_name": attorney_name,
                        "attorney_email": attorney_email,
                        "policyholder_name": policyholder_name,
                        "loss_location": loss_location,
                        "loss_type": loss_type,
                        "loss_event": loss_event,
                        "loss_date": loss_date,
                        "carrier": carrier,
                        "policy_number": policy_number,
                        "claim_number": claim_number,
                        "coverage_c_limit_dollars": coverage_c_limit_dollars,
                        "firm_file_number": firm_file_number,
                        "target_delivery_date": target_delivery_date,
                    },
                },
                status_code=200,
            )
```

Note: this `return` is inside the `try:`, so the `finally: db.close()` still runs — good.

Then set the field on the new `Claim(...)` — add as the first kwarg after `id=...` (around line 85):

```python
            nickname=nickname_clean,
```

The `create_claim` return type annotation is `-> RedirectResponse`; broaden it to `-> RedirectResponse | HTMLResponse` (the template response). Update the signature line (line 80):

```python
) -> RedirectResponse | HTMLResponse:
```

- [ ] **Step 4: Make `new_claim_form` and the template render the field + error**

In `new_claim_form` (`claims.py` lines 50–58), add `"error": None` and `"form": {}` to the context dict so the GET render has defaults:

```python
        context={
            "loss_types": LOSS_TYPES,
            "loss_events": LOSS_EVENTS,
            "user": user,
            "error": None,
            "form": {},
        },
```

In `src/claimos/templates/claim_new.html`, add an error banner and a nickname fieldset as the **first** thing inside the `<form ...>` (after line 13 `<form method="post" action="/claims" class="space-y-8">`):

```html
    {% if error %}
    <div class="mb-4 rounded-md bg-error-surface p-4">
      <p class="text-sm text-error-strong">{{ error }}</p>
    </div>
    {% endif %}

    <fieldset class="space-y-4">
      <legend class="text-sm font-semibold text-neutral-900 border-b border-neutral-200 pb-1 w-full">Claim nickname</legend>
      <div>
        <label for="nickname" class="block text-sm font-medium text-neutral-700">Nickname <span class="text-error-strong">*</span></label>
        <input type="text" name="nickname" id="nickname" required maxlength="100"
               value="{{ form.nickname if form else '' }}"
               class="input mt-1 w-full" />
        <p class="mt-1 text-xs text-neutral-500">A short label unique to your group. Shown wherever claims are listed.</p>
      </div>
    </fieldset>
```

Then update the existing inputs in `claim_new.html` to preserve values on re-render by adding `value="{{ form.<name> if form else '' }}"` to each text/email input. Do this for `firm_name`, `firm_file_number`, `attorney_name`, `attorney_email`, and `policyholder_name` (the fields asserted-adjacent and most likely re-entered). Example for `firm_name` (line 20–21):

```html
          <input type="text" name="firm_name" id="firm_name" value="{{ form.firm_name if form else '' }}"
                 class="input mt-1 w-full" />
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_claim_nickname_create.py -v`
Expected: PASS (all three).

- [ ] **Step 6: Guard against regressions in the create flow**

Run: `uv run pytest tests/test_app_shell.py -v`
Expected: PASS (no claim-create callers broke).

- [ ] **Step 7: Format and commit**

```bash
uv run ruff format . && uv run ruff format --check .
git add src/claimos/routers/claims.py src/claimos/templates/claim_new.html tests/test_claim_nickname_create.py
git commit -m "feat: require nickname when creating a claim"
```

---

### Task 6: Wire nickname into claim editing (overview tab)

**Files:**
- Modify: `src/claimos/routers/claims.py` (`update_claim` lines 286–342)
- Modify: `src/claimos/templates/_tab_overview.html` (add field + error banner)
- Test: `tests/test_claim_nickname_update.py` (create)

**Interfaces:**
- Consumes: `validate_nickname` from Task 4.
- Produces: `POST /claims/{id}/update` validates the nickname; on failure it does NOT commit and redirects to `/claims/{id}?nickname_error=<msg>#overview`; on success sets `claim.nickname` and redirects as today.

- [ ] **Step 1: Write the failing test**

Create `tests/test_claim_nickname_update.py`:

```python
"""POST /claims/{id}/update validates the nickname without a heavy re-render."""

from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import claimos.dependencies as deps
import claimos.models_auth  # noqa: F401
from claimos.models import Base, Claim
from claimos.models_auth import Group, User


@pytest.fixture
def seeded_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    s.add(Group(id="ig", name="Internal", kind="internal"))
    s.add(User(id="ia", email="ia@t.com", display_name="A", system_role="internal_admin", group_id="ig"))
    s.add(Claim(id="c1", owner_group_id="ig", nickname="Smith File"))
    s.add(Claim(id="c2", owner_group_id="ig", nickname="Jones File"))
    s.commit()
    yield s
    s.close()


@pytest.fixture
def client(seeded_db, monkeypatch):
    from claimos.dependencies import CurrentUser, require_active_user
    from claimos.main import app

    async def mock_user():
        return CurrentUser(
            id="ia", email="ia@t.com", system_role="internal_admin",
            group_id="ig", group_kind="internal",
        )

    app.dependency_overrides[require_active_user] = mock_user
    monkeypatch.setattr(deps, "_check_claim_access", lambda *a, **k: True)
    monkeypatch.setattr("claimos.routers.claims.SessionLocal", lambda: seeded_db)
    yield TestClient(app, follow_redirects=False)
    app.dependency_overrides.clear()


def _form(**over):
    data = {"nickname": "Smith File", "policyholder_name": "Smith"}
    data.update(over)
    return data


def test_update_rename_succeeds(client, seeded_db):
    resp = client.post("/claims/c1/update", data=_form(nickname="Smith Residence"))
    assert resp.status_code == 303
    assert "nickname_error" not in resp.headers["location"]
    assert seeded_db.get(Claim, "c1").nickname == "Smith Residence"


def test_update_keeping_same_nickname_succeeds(client, seeded_db):
    resp = client.post("/claims/c1/update", data=_form(nickname="smith file"))
    assert resp.status_code == 303
    assert seeded_db.get(Claim, "c1").nickname == "smith file"


def test_update_to_duplicate_rejected(client, seeded_db):
    resp = client.post("/claims/c1/update", data=_form(nickname="Jones File"))
    assert resp.status_code == 303
    assert "nickname_error" in unquote(resp.headers["location"])
    # Unchanged in DB.
    assert seeded_db.get(Claim, "c1").nickname == "Smith File"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_claim_nickname_update.py -v`
Expected: FAIL — `update_claim` has no `nickname` param; renames don't persist and duplicates aren't rejected.

- [ ] **Step 3: Add validation to `update_claim`**

In `src/claimos/routers/claims.py`, add a `nickname` form param to `update_claim` — insert after `user` (before `firm_name`, around line 292):

```python
    nickname: str = Form(default=""),
```

Then, inside the try block right after the `if claim is None: return ...` check (after line 312) and before `claim.firm_name = firm_name`, validate and redirect on error:

```python
        nickname_clean, nickname_error = validate_nickname(
            db, nickname, claim.owner_group_id, exclude_claim_id=claim.id
        )
        if nickname_error:
            from urllib.parse import quote

            return RedirectResponse(
                url=f"/claims/{claim_id}?nickname_error={quote(nickname_error)}#overview",
                status_code=303,
            )
        claim.nickname = nickname_clean
```

(Place `claim.nickname = nickname_clean` alongside the other `claim.<field> = ...` assignments.)

- [ ] **Step 4: Render the field + error banner in the overview tab**

In `src/claimos/templates/_tab_overview.html`, add an error banner and nickname field as the **first** children inside the edit `<form ...>` (after line 39 `<form method="post" action="/claims/{{ claim.id }}/update" class="space-y-8">`):

```html
  {% if request.query_params.get('nickname_error') %}
  <div class="mb-4 rounded-md bg-error-surface p-4">
    <p class="text-sm text-error-strong">{{ request.query_params.get('nickname_error') }}</p>
  </div>
  {% endif %}

  <fieldset class="space-y-4">
    <legend class="text-sm font-semibold text-neutral-900 border-b border-neutral-200 pb-1 w-full">Claim nickname</legend>
    <div>
      <label for="nickname" class="block text-sm font-medium text-neutral-700">Nickname <span class="text-error-strong">*</span></label>
      <input type="text" name="nickname" id="nickname" required maxlength="100" value="{{ claim.nickname }}"
             class="input mt-1 w-full" />
      <p class="mt-1 text-xs text-neutral-500">A short label unique to your group.</p>
    </div>
  </fieldset>
```

(`request` is already in the template context — `claim_detail` renders via `templates.TemplateResponse(request=request, ...)`.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_claim_nickname_update.py -v`
Expected: PASS (all three).

- [ ] **Step 6: Format and commit**

```bash
uv run ruff format . && uv run ruff format --check .
git add src/claimos/routers/claims.py src/claimos/templates/_tab_overview.html tests/test_claim_nickname_update.py
git commit -m "feat: validate nickname on claim edit"
```

---

### Task 7: Show nickname as the primary label in listings and headers

**Files:**
- Modify: `src/claimos/templates/dashboard.html` (lines 19, 29–34)
- Modify: `src/claimos/templates/claim_detail.html` (lines 3–4, 10–16)
- Modify: `src/claimos/templates/team/_claims_table.html` (line 14)
- Modify: `src/claimos/templates/admin/org/user_detail.html` (line 99)
- Test: `tests/test_claim_nickname_display.py` (create)

**Interfaces:**
- Consumes: `Claim.nickname`.
- Produces: nickname is the primary/clickable label; `policyholder_name` demoted to secondary text. Report templates untouched.

- [ ] **Step 1: Write the failing test**

Create `tests/test_claim_nickname_display.py`:

```python
"""The dashboard lists claims by nickname (primary), policyholder secondary."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import claimos.models_auth  # noqa: F401
from claimos.models import Base, Claim
from claimos.models_auth import Group, User


@pytest.fixture
def seeded_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    s.add(Group(id="ig", name="Internal", kind="internal"))
    s.add(User(id="ia", email="ia@t.com", display_name="A", system_role="internal_admin", group_id="ig"))
    s.add(Claim(id="c1", owner_group_id="ig", nickname="Smith Residence", policyholder_name="Jane Smith"))
    s.commit()
    yield s
    s.close()


@pytest.fixture
def client(seeded_db):
    from claimos.db import get_db
    from claimos.dependencies import CurrentUser, require_active_user
    from claimos.main import app

    async def mock_user():
        return CurrentUser(
            id="ia", email="ia@t.com", system_role="internal_admin",
            group_id="ig", group_kind="internal",
        )

    def override_db():
        yield seeded_db

    # The /dashboard route (main.py) reads claims via the get_db dependency.
    app.dependency_overrides[require_active_user] = mock_user
    app.dependency_overrides[get_db] = override_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_dashboard_shows_nickname_as_link(client):
    html = client.get("/dashboard").text
    # Nickname appears as the clickable label; policyholder as secondary text.
    link_idx = html.find("Smith Residence")
    ph_idx = html.find("Jane Smith")
    assert link_idx != -1 and ph_idx != -1
    assert link_idx < ph_idx  # nickname rendered before policyholder in the row
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_claim_nickname_display.py -v`
Expected: FAIL — nickname is not rendered; only `Jane Smith` appears, so `link_idx == -1`.

- [ ] **Step 3: Update `dashboard.html`**

In `src/claimos/templates/dashboard.html`, change the column header (line 19) from `Firm / Policyholder` to `Claim`:

```html
        <th class="px-4 py-3 text-left text-xs font-medium text-neutral-500 uppercase tracking-wide">Claim</th>
```

Change the cell (lines 29–34) so the link text is the nickname and policyholder/firm are the secondary line:

```html
        <td class="px-4 py-3">
          <a href="/claims/{{ claim.id }}" class="font-medium text-primary hover:text-primary-strong">
            {{ claim.nickname }}
          </a>
          <p class="text-xs text-neutral-500">{{ claim.policyholder_name or "—" }}{% if claim.firm_name %} · {{ claim.firm_name }}{% endif %}</p>
        </td>
```

- [ ] **Step 4: Update `claim_detail.html`**

In `src/claimos/templates/claim_detail.html`, change the title/topbar (lines 3–4):

```html
{% block title %}{{ claim.nickname }}{% endblock %}
{% block topbar_title %}{{ claim.nickname }}{% endblock %}
```

Change the header (lines 10–16) to lead with nickname and show policyholder in the sub-line:

```html
    <h1 class="text-2xl font-semibold text-neutral-900">
      {{ claim.nickname }}
    </h1>
    <p class="mt-0.5 text-sm text-neutral-500">
      {{ claim.policyholder_name or "(unnamed policyholder)" }}
      {% if claim.firm_name %}&mdash; {{ claim.firm_name }}{% endif %}
      {% if claim.loss_event %}&mdash; {{ claim.loss_event }}{% endif %}
    </p>
```

- [ ] **Step 5: Update `team/_claims_table.html` and `admin/org/user_detail.html`**

In `src/claimos/templates/team/_claims_table.html` line 14, change the link text from `{{ c.policyholder_name }}` to `{{ c.nickname }}`:

```html
          <a href="/team/claims/{{ c.id }}/access" class="text-success hover:underline">{{ c.nickname }}</a>
```

In `src/claimos/templates/admin/org/user_detail.html` line 99, change the option label:

```html
          <option value="{{ claim.id }}">{{ claim.nickname }} ({{ claim.id }})</option>
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_claim_nickname_display.py tests/test_team_claims.py tests/test_app_shell.py -v`
Expected: PASS. (If `test_team_claims.py` or `test_app_shell.py` create claims without a nickname and now render `None`, update those fixtures to pass `nickname=...`.)

- [ ] **Step 7: Format and commit**

```bash
uv run ruff format . && uv run ruff format --check .
git add src/claimos/templates/ tests/test_claim_nickname_display.py
git commit -m "feat: show claim nickname as primary label in listings"
```

---

### Task 8: Full-suite regression sweep

**Files:** none (verification only).

- [ ] **Step 1: Run the whole suite**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib uv run pytest`
Expected: PASS. Any failure is almost certainly a pre-existing test that constructs a `Claim(...)` without `nickname` (now NOT NULL) or that asserts on `policyholder_name` as a primary label. For each: add `nickname="<something unique>"` to the `Claim(...)` in that test's fixture, or update the assertion to the nickname. Do not weaken the model.

- [ ] **Step 2: Lint**

Run: `uv run ruff check .`
Expected: no errors.

- [ ] **Step 3: Format check**

Run: `uv run ruff format --check .`
Expected: `0 files would be reformatted`.

- [ ] **Step 4: Commit any fixture fixups**

```bash
git add -A
git commit -m "test: backfill nickname in existing claim fixtures"
```

---

## Self-Review

**Spec coverage:**
- Required + NOT NULL → Task 1 (column), Task 5 (create enforcement). ✓
- Case-insensitive per-group uniqueness + DB index → Task 1 (index), Task 4 (helper), Task 2 (migration index). ✓
- Primary-label display → Task 7. ✓
- Internal-only (no report leakage) → Global Constraints + Task 7 leaves report templates untouched; no task edits `report/`. ✓
- Backfill = short id (Alembic + migrate-db) → Task 2, Task 3. ✓
- Create re-renders with preserved values; update redirects with error banner → Task 5, Task 6. ✓
- Tests: unit helper, create/edit integration, migration → Tasks 4, 5, 6, 2, 3. ✓

**Placeholder scan:** No "TBD"/"handle edge cases"/"similar to". All routes/modules are resolved to exact paths (dashboard = `GET /dashboard` in `main.py` via `get_db`; create/update use `claimos.routers.claims.SessionLocal`). ✓

**Type consistency:** `validate_nickname(db, raw, owner_group_id, exclude_claim_id=None) -> tuple[str, str | None]` is defined in Task 4 and called with those exact names/arities in Tasks 5 and 6. Index name `uq_claims_group_nickname_ci` is identical in Tasks 1 and 2. Backfill string `"Claim " + id[:8]` matches between Task 2 (`substr(id,1,8)`) and Task 3 (`str(d['id'])[:8]`). ✓
