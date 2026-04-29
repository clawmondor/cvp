# Hosting & Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the CVP application deployable to Render (Web Starter + Postgres Standard) behind Cloudflare, with a Dockerfile, GitHub Actions CI, idempotent pre-deploy bootstrap, and the supporting documentation. Keep SQLite working for local development. Do not change application behavior beyond what the production deployment requires.

**Architecture:** Adopt Postgres in production while keeping SQLite for local dev (URL-driven). Containerize with a Dockerfile that includes WeasyPrint native libs. Add a `/healthz` route, a `bootstrap-admin` script, and a fix for client-IP handling behind Cloudflare's proxy. Wrap the whole thing in a GitHub Actions CI workflow (lint + test + secrets scan). Defer offsite backups and R2 evidence storage to a separate effort tracked in `docs/BACKLOG.md`.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.x, Alembic, uv, psycopg 3, Docker, GitHub Actions, gitleaks, Render, Cloudflare.

**Source spec:** `docs/superpowers/specs/2026-04-29-hosting-design.md` — read this first; it explains every "why" the tasks below assume.

**Recommended:** execute in a dedicated git worktree (`superpowers:using-git-worktrees`). All commits go on a feature branch; the final merge to `main` is the operator's call.

---

## Pre-flight

Before starting, the executor MUST:

1. Read `docs/superpowers/specs/2026-04-29-hosting-design.md` end-to-end.
2. Read `CLAUDE.md` end-to-end (project conventions).
3. Run `uv sync` and confirm `uv run pytest` is fully green on `main` before changing anything. If tests are red on `main`, stop and report — this plan assumes a green starting state.
4. Confirm Docker is available: `docker version`. If not, install Docker Desktop before reaching Task 13.
5. Note the base commit SHA for later reference: `git rev-parse HEAD > /tmp/base_sha.txt`.

---

## Task 1: Survey the existing codebase

**Files (read-only):**
- Read: `src/cvp/config.py`
- Read: `src/cvp/db.py`
- Read: `src/cvp/seed.py`
- Read: `src/cvp/seed_auth.py`
- Read: `src/cvp/middleware.py`
- Read: `src/cvp/models_auth.py`
- Read: `src/cvp/main.py`
- Read: `migrations/versions/` (all files)

- [ ] **Step 1: Read each of the files above and write a one-paragraph summary per file to `tmp/exploration-notes.md`.**

For each file capture:
- What is it responsible for?
- What types/functions does it export that other tasks may need to call?
- Anything that looks SQLite-specific or proxy-unaware?

Run: `mkdir -p tmp && touch tmp/exploration-notes.md`

- [ ] **Step 2: Grep for SQLite-specific patterns.**

Run: `rg -n "sqlite|SQLite|WAL|PRAGMA" src/ migrations/`
Append findings to `tmp/exploration-notes.md` under "SQLite-specific call sites".

- [ ] **Step 3: Grep for client-IP usage.**

Run: `rg -n "request\.client|client\.host|X-Forwarded|CF-Connecting" src/`
Append findings to `tmp/exploration-notes.md` under "Client IP call sites" — these are the spots Task 9 will fix.

- [ ] **Step 4: Grep for JSON column usage.**

Run: `rg -n "JSON|JSONB|sqlalchemy\.JSON" src/cvp/models*.py migrations/`
Append findings to `tmp/exploration-notes.md` under "JSON columns".

- [ ] **Step 5: Confirm tmp/ is gitignored.**

Run: `git check-ignore tmp/exploration-notes.md`
Expected: prints the path (means it's ignored). If not ignored, add `tmp/` to `.gitignore` as a separate first commit.

- [ ] **Step 6: No commit for this task.** Exploration notes stay local.

---

## Task 2: Add psycopg and DATABASE_URL config

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/cvp/config.py`
- Modify: `tests/test_config.py` (create if missing)

- [ ] **Step 1: Add psycopg dependency to pyproject.toml.**

In the `[project]` `dependencies = [...]` list, add `"psycopg[binary]>=3.2",`. Keep the alphabetical / existing ordering convention.

Run: `uv lock && uv sync`
Expected: lockfile updates, install succeeds.

- [ ] **Step 2: Write a failing test for DATABASE_URL handling.**

Open `tests/test_config.py` (create if it doesn't exist). Add:

```python
import os
from cvp.config import get_settings


def test_default_database_url_is_sqlite(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.database_url.startswith("sqlite:///")


def test_database_url_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h:5432/db")
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.database_url == "postgresql+psycopg://u:p@h:5432/db"
    get_settings.cache_clear()
```

- [ ] **Step 3: Run the test — expect failure.**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL — either `database_url` attribute missing or `get_settings.cache_clear` missing.

- [ ] **Step 4: Modify config.py.**

Read the current `src/cvp/config.py` and add a `database_url` field to the Settings class with a SQLite default. Use this pattern (adapt naming to whatever pydantic-settings idiom is already in the file — `BaseSettings`, `SettingsConfigDict`, etc.):

```python
database_url: str = "sqlite:///./data/cvp.db"
```

If the file uses `@lru_cache` for `get_settings`, that's already correct — the test calls `cache_clear()`. If it doesn't, wrap `get_settings` in `@functools.lru_cache(maxsize=1)`.

- [ ] **Step 5: Run the test — expect pass.**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS, both tests.

- [ ] **Step 6: Run the full test suite — must stay green.**

Run: `uv run pytest`
Expected: same green state as before this task.

- [ ] **Step 7: Commit.**

```bash
git add pyproject.toml uv.lock src/cvp/config.py tests/test_config.py
git commit -m "feat(config): support DATABASE_URL env var with sqlite default"
```

---

## Task 3: Make db.py dialect-aware (WAL only on SQLite)

**Files:**
- Modify: `src/cvp/db.py`
- Test: `tests/test_db.py` (create if missing)

- [ ] **Step 1: Re-read `src/cvp/db.py`.** Find the WAL PRAGMA call and the engine creation.

- [ ] **Step 2: Write a failing test.**

Create or extend `tests/test_db.py`:

```python
from cvp.db import _is_sqlite_url


def test_is_sqlite_url_true_for_sqlite():
    assert _is_sqlite_url("sqlite:///./data/cvp.db") is True
    assert _is_sqlite_url("sqlite+pysqlite:///./data/cvp.db") is True


def test_is_sqlite_url_false_for_postgres():
    assert _is_sqlite_url("postgresql+psycopg://u:p@h/d") is False
    assert _is_sqlite_url("postgresql://u:p@h/d") is False
```

- [ ] **Step 3: Run the test — expect failure (function doesn't exist).**

Run: `uv run pytest tests/test_db.py -v`
Expected: FAIL — `ImportError` or `AttributeError`.

- [ ] **Step 4: Implement `_is_sqlite_url` and gate the WAL PRAGMA on it.**

In `src/cvp/db.py`, add the helper near the top of the file (after imports):

```python
def _is_sqlite_url(url: str) -> bool:
    return url.startswith("sqlite:") or url.startswith("sqlite+")
```

Find the existing WAL PRAGMA listener (likely uses `event.listens_for(engine, "connect")` or similar). Wrap its body so it only runs when `_is_sqlite_url(settings.database_url)` is true.

For Postgres engines, set `pool_pre_ping=True` and `pool_size=5, max_overflow=5` on `create_engine(...)`. Keep SQLite's `connect_args={"check_same_thread": False}` only when the URL is SQLite.

Pattern (adapt to existing code structure):

```python
from cvp.config import get_settings

_settings = get_settings()
_is_sqlite = _is_sqlite_url(_settings.database_url)

engine_kwargs = {}
if _is_sqlite:
    engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    engine_kwargs["pool_pre_ping"] = True
    engine_kwargs["pool_size"] = 5
    engine_kwargs["max_overflow"] = 5

engine = create_engine(_settings.database_url, **engine_kwargs)

if _is_sqlite:
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
```

- [ ] **Step 5: Run db tests — expect pass.**

Run: `uv run pytest tests/test_db.py -v`
Expected: PASS.

- [ ] **Step 6: Run full test suite — must stay green.**

Run: `uv run pytest`
Expected: green.

- [ ] **Step 7: Commit.**

```bash
git add src/cvp/db.py tests/test_db.py
git commit -m "feat(db): make engine dialect-aware (WAL pragmas SQLite-only)"
```

---

## Task 4: Audit JSON columns for cross-dialect safety

**Files:**
- Modify: `src/cvp/models*.py` (whichever files declare JSON columns)
- Modify: `migrations/versions/*.py` (any migration that adds a JSON column)

- [ ] **Step 1: Re-read `tmp/exploration-notes.md` "JSON columns" section.**

Identify every column declared as a JSON or JSONB type.

- [ ] **Step 2: For each JSON column, ensure it uses `sqlalchemy.JSON` (not `JSONB` directly).**

`sqlalchemy.JSON` (the dialect-agnostic type) chooses `JSONB` on Postgres and `TEXT`-with-JSON-functions on SQLite automatically. Direct `JSONB` from `sqlalchemy.dialects.postgresql` would break SQLite.

For each model file that imports `JSONB`:
- Replace `from sqlalchemy.dialects.postgresql import JSONB` with `from sqlalchemy import JSON`.
- Replace `Mapped[dict] = mapped_column(JSONB, ...)` with `Mapped[dict] = mapped_column(JSON, ...)`.
- Same change in any migration file using `postgresql.JSONB`.

If no JSONB usage exists (current code already uses `JSON`), this task is a no-op — record that in the commit message.

- [ ] **Step 3: Run the full test suite.**

Run: `uv run pytest`
Expected: green.

- [ ] **Step 4: Commit.**

```bash
git add src/cvp/models*.py migrations/versions/
git commit -m "refactor(models): use dialect-agnostic sqlalchemy.JSON for cross-DB support"
```

If no changes were needed: skip the commit and note "Task 4: no JSONB usage found, no changes required" in the executor's report.

---

## Task 5: Audit Alembic migrations for SQLite-specific SQL

**Files:**
- Read/Modify: `migrations/versions/*.py`

- [ ] **Step 1: Grep for risky patterns.**

Run: `rg -n "AUTOINCREMENT|PRAGMA|sqlite_|batch_alter_table" migrations/versions/`

For each match:
- `AUTOINCREMENT` — SQLite-specific. SQLAlchemy's `Integer` primary keys auto-increment on Postgres without it. Remove the keyword if used in raw SQL.
- `PRAGMA` — SQLite-only. If found, wrap in a dialect check (see below).
- `batch_alter_table` — used for SQLite ALTER TABLE workarounds. Safe on Postgres but unnecessary; leave as-is to preserve SQLite compatibility.
- `sqlite_*` — any SQLite-specific function/feature.

- [ ] **Step 2: If any raw SQL is dialect-specific, gate it on the connection's dialect.**

Pattern for inside an Alembic migration:

```python
from alembic import op


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        op.execute("...sqlite-specific SQL...")
    else:
        op.execute("...portable or postgres-specific SQL...")
```

- [ ] **Step 3: Run migrations against a fresh SQLite DB to confirm no regression.**

```bash
rm -f data/test_cvp.db
DATABASE_URL="sqlite:///./data/test_cvp.db" uv run alembic upgrade head
```

Expected: completes without error.

- [ ] **Step 4: Commit (only if any migrations changed).**

```bash
git add migrations/versions/
git commit -m "fix(migrations): make Alembic migrations dialect-portable"
```

If no changes were needed, skip the commit and note "Task 5: migrations already portable" in the report.

---

## Task 6: Make `seed` script idempotent against Postgres

**Files:**
- Modify: `src/cvp/seed.py`
- Test: `tests/test_seed.py` (create if missing)

- [ ] **Step 1: Re-read `src/cvp/seed.py` and identify the insert pattern.**

If it uses `session.add(Category(...))` without checking existence, it will fail on second run against Postgres (unique constraint violation on the category code/slug column).

- [ ] **Step 2: Write a failing test for double-run idempotency.**

Create or extend `tests/test_seed.py`:

```python
from sqlalchemy import func, select

from cvp.db import SessionLocal
from cvp.models import Category  # adjust import path if Category lives elsewhere
from cvp.seed import main as run_seed


def test_seed_is_idempotent_on_double_run(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/seed_test.db")
    # Force config + engine to pick up the test URL.
    from cvp.config import get_settings
    get_settings.cache_clear()

    # Run migrations against the temp DB
    from alembic import command
    from alembic.config import Config as AlembicConfig
    cfg = AlembicConfig("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{tmp_path}/seed_test.db")
    command.upgrade(cfg, "head")

    run_seed()
    run_seed()  # second run must not raise

    with SessionLocal() as session:
        count = session.scalar(select(func.count()).select_from(Category))
    assert count == 42
    get_settings.cache_clear()
```

If the actual `Category` model is named differently or the test plumbing above doesn't fit, simplify: open a session manually, count rows, assert 42 after two runs.

- [ ] **Step 3: Run the test — expect failure (or success, if seed is already idempotent).**

Run: `uv run pytest tests/test_seed.py -v`

If it already passes, the seed is genuinely idempotent — record that and skip to Step 5.

- [ ] **Step 4: Convert the seed to upsert.**

Replace the insert pattern with one of these:

**Pattern A (portable, uses SELECT-then-INSERT):**

```python
def main():
    with SessionLocal() as session:
        for row in CATEGORIES:
            existing = session.execute(
                select(Category).where(Category.code == row["code"])
            ).scalar_one_or_none()
            if existing is None:
                session.add(Category(**row))
        session.commit()
```

**Pattern B (Postgres-only, uses ON CONFLICT):** more efficient but requires dialect branching. Pattern A is fine for 42 rows; prefer it for simplicity.

- [ ] **Step 5: Run the seed test — expect pass.**

Run: `uv run pytest tests/test_seed.py -v`
Expected: PASS.

- [ ] **Step 6: Run full test suite.**

Run: `uv run pytest`
Expected: green.

- [ ] **Step 7: Commit.**

```bash
git add src/cvp/seed.py tests/test_seed.py
git commit -m "feat(seed): make category seed idempotent (safe to re-run)"
```

---

## Task 7: Add `/healthz` route

**Files:**
- Create: `src/cvp/routers/health.py`
- Modify: `src/cvp/main.py` (register the router)
- Test: `tests/test_health.py`

- [ ] **Step 1: Write the failing test.**

Create `tests/test_health.py`:

```python
from fastapi.testclient import TestClient

from cvp.main import app


def test_healthz_returns_200():
    client = TestClient(app)
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: Run the test — expect failure (404).**

Run: `uv run pytest tests/test_health.py -v`
Expected: FAIL with 404.

- [ ] **Step 3: Create the health router.**

`src/cvp/routers/health.py`:

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from cvp.db import get_session

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz(session: Session = Depends(get_session)) -> dict[str, str]:
    try:
        session.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="db unhealthy") from exc
    return {"status": "ok"}
```

If `get_session` is named differently in `db.py` (e.g., `get_db`), use that name.

- [ ] **Step 4: Register the router in main.py.**

In `src/cvp/main.py`, find the section where other routers are included (`app.include_router(...)`). Add:

```python
from cvp.routers import health
# ...
app.include_router(health.router)
```

`/healthz` must NOT be behind auth — it's polled by Render's load balancer with no credentials. Confirm it's added before any global auth middleware that would block it, or that auth middleware exempts `/healthz`. If not exempt, add it to the exempt list.

- [ ] **Step 5: Run the test — expect pass.**

Run: `uv run pytest tests/test_health.py -v`
Expected: PASS.

- [ ] **Step 6: Verify `/healthz` is unauthenticated.**

Run: `uv run pytest`
Expected: full suite green.

Manually test (optional but recommended):

```bash
uv run dev &
sleep 2
curl -i http://localhost:8000/healthz
kill %1
```

Expected: `HTTP/1.1 200 OK` with body `{"status":"ok"}`, no redirect to login.

- [ ] **Step 7: Commit.**

```bash
git add src/cvp/routers/health.py src/cvp/main.py tests/test_health.py
git commit -m "feat(health): add /healthz endpoint for Render healthcheck"
```

---

## Task 8: Fix client-IP handling for proxied requests

**Files:**
- Modify: `src/cvp/middleware.py` (or wherever the rate limiter / client-IP logic lives — see exploration notes)
- Test: `tests/test_client_ip.py`

- [ ] **Step 1: Identify all call sites that read `request.client.host`.**

Re-check `tmp/exploration-notes.md` "Client IP call sites". Each one needs to change.

- [ ] **Step 2: Write a failing test.**

Create `tests/test_client_ip.py`:

```python
from cvp.middleware import get_client_ip


class _FakeClient:
    def __init__(self, host):
        self.host = host


class _FakeRequest:
    def __init__(self, headers, host="127.0.0.1"):
        self.headers = headers
        self.client = _FakeClient(host)


def test_get_client_ip_prefers_cf_connecting_ip():
    req = _FakeRequest(headers={"CF-Connecting-IP": "203.0.113.42"})
    assert get_client_ip(req) == "203.0.113.42"


def test_get_client_ip_falls_back_to_request_client():
    req = _FakeRequest(headers={}, host="127.0.0.1")
    assert get_client_ip(req) == "127.0.0.1"


def test_get_client_ip_handles_case_insensitive_header():
    req = _FakeRequest(headers={"cf-connecting-ip": "198.51.100.7"})
    assert get_client_ip(req) == "198.51.100.7"
```

- [ ] **Step 3: Run the test — expect failure.**

Run: `uv run pytest tests/test_client_ip.py -v`
Expected: FAIL — `get_client_ip` doesn't exist.

- [ ] **Step 4: Implement `get_client_ip`.**

In `src/cvp/middleware.py` (or create `src/cvp/utils/request.py` if a util location is more idiomatic for the codebase — pick one, stick with it):

```python
from fastapi import Request


def get_client_ip(request: Request) -> str:
    cf_ip = request.headers.get("cf-connecting-ip") or request.headers.get("CF-Connecting-IP")
    if cf_ip:
        return cf_ip.strip()
    if request.client is not None:
        return request.client.host
    return "unknown"
```

FastAPI's `Headers` is already case-insensitive, so the above redundancy is just defensive — keep `cf-connecting-ip` as the primary lookup; the second `or` is harmless.

- [ ] **Step 5: Run the IP test — expect pass.**

Run: `uv run pytest tests/test_client_ip.py -v`
Expected: PASS.

- [ ] **Step 6: Replace every `request.client.host` call site with `get_client_ip(request)`.**

For each match from `tmp/exploration-notes.md` "Client IP call sites":
- Add `from cvp.middleware import get_client_ip` (or wherever you placed it).
- Replace `request.client.host` with `get_client_ip(request)`.

The most important call sites: rate limiter (added in commit `033ae94`) and audit log (commit history mentions audit logging in `models_audit.py`).

- [ ] **Step 7: Configure Uvicorn for proxy headers.**

In `src/cvp/main.py`, find the `run_dev` function (per `pyproject.toml` it's the entry for `uv run dev`). The production deployment passes `--proxy-headers --forwarded-allow-ips=*` via the Dockerfile CMD — local dev does not need this. No change needed in `main.py` itself, but verify the function exists and uses uvicorn so we know the production CMD will work. If `run_dev` calls `uvicorn.run(...)` directly, that's fine.

- [ ] **Step 8: Run full suite.**

Run: `uv run pytest`
Expected: green.

- [ ] **Step 9: Commit.**

```bash
git add src/cvp/middleware.py src/cvp/routers/ src/cvp/services/ src/cvp/auth.py tests/test_client_ip.py
git commit -m "fix(middleware): read CF-Connecting-IP for client IP behind Cloudflare"
```

(Adjust the `git add` paths to match the actual files you modified.)

---

## Task 9: Add `bootstrap-admin` script

**Files:**
- Create: `src/cvp/bootstrap_admin.py`
- Modify: `pyproject.toml` (add script entry)
- Test: `tests/test_bootstrap_admin.py`

- [ ] **Step 1: Re-read `src/cvp/seed_auth.py` and `src/cvp/models_auth.py` to learn:**
- The User model name and module.
- The role enum / column name and what value represents "system admin".
- The password-hashing function used (likely `bcrypt.hashpw` or a wrapper in `auth.py`).
- Whether `seed_auth` already creates an admin user — if it does, the new `bootstrap-admin` script is a thin wrapper that reads env vars and delegates.

- [ ] **Step 2: Write the failing tests.**

Create `tests/test_bootstrap_admin.py`:

```python
import pytest

from cvp.bootstrap_admin import main as bootstrap_admin


def test_skips_when_admin_already_exists(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/bootstrap.db")
    monkeypatch.setenv("INITIAL_ADMIN_EMAIL", "first@example.com")
    monkeypatch.setenv("INITIAL_ADMIN_PASSWORD", "correct-horse-battery-staple")

    # Run migrations
    from alembic import command
    from alembic.config import Config as AlembicConfig
    cfg = AlembicConfig("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{tmp_path}/bootstrap.db")
    command.upgrade(cfg, "head")

    bootstrap_admin()  # creates admin
    bootstrap_admin()  # second run skips

    out = capsys.readouterr().out
    assert "skipped" in out.lower()


def test_raises_when_env_vars_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/bootstrap2.db")
    monkeypatch.delenv("INITIAL_ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("INITIAL_ADMIN_PASSWORD", raising=False)

    from alembic import command
    from alembic.config import Config as AlembicConfig
    cfg = AlembicConfig("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{tmp_path}/bootstrap2.db")
    command.upgrade(cfg, "head")

    with pytest.raises(SystemExit):
        bootstrap_admin()
```

- [ ] **Step 3: Run — expect failure.**

Run: `uv run pytest tests/test_bootstrap_admin.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 4: Create the script.**

`src/cvp/bootstrap_admin.py` — adjust imports for the actual User model name and the actual password-hashing helper:

```python
"""Idempotent admin bootstrap. Called from Render pre-deploy command."""
from __future__ import annotations

import os
import sys

from sqlalchemy import select

from cvp.auth import hash_password  # adjust if the helper has a different name
from cvp.config import get_settings
from cvp.db import SessionLocal
from cvp.models_auth import User, UserRole  # adjust to actual exports


def main() -> None:
    get_settings.cache_clear()

    email = os.environ.get("INITIAL_ADMIN_EMAIL")
    password = os.environ.get("INITIAL_ADMIN_PASSWORD")

    with SessionLocal() as session:
        existing_admin = session.execute(
            select(User).where(User.role == UserRole.SYSTEM_ADMIN).limit(1)
        ).scalar_one_or_none()

        if existing_admin is not None:
            print("bootstrap-admin: skipped (existing admin present)")
            return

        if not email or not password:
            print(
                "bootstrap-admin: error — no admin exists and "
                "INITIAL_ADMIN_EMAIL / INITIAL_ADMIN_PASSWORD are not set",
                file=sys.stderr,
            )
            sys.exit(1)

        admin = User(
            email=email,
            password_hash=hash_password(password),
            role=UserRole.SYSTEM_ADMIN,
            mfa_enrolled=False,
        )
        session.add(admin)
        session.commit()

        print(f"bootstrap-admin: created initial admin {email}")
```

If the actual User model has additional required NOT NULL fields (e.g., `display_name`, `org_id`), set sensible defaults — the script must succeed without prompting. Read the model carefully.

- [ ] **Step 5: Add the script entry in pyproject.toml.**

Under `[project.scripts]`:

```toml
bootstrap-admin = "cvp.bootstrap_admin:main"
```

Run: `uv sync` (refreshes the script entry points).

- [ ] **Step 6: Run tests — expect pass.**

Run: `uv run pytest tests/test_bootstrap_admin.py -v`
Expected: PASS, both tests.

- [ ] **Step 7: Run full suite.**

Run: `uv run pytest`
Expected: green.

- [ ] **Step 8: Commit.**

```bash
git add src/cvp/bootstrap_admin.py pyproject.toml uv.lock tests/test_bootstrap_admin.py
git commit -m "feat(bootstrap): add idempotent bootstrap-admin script for first deploy"
```

---

## Task 10: Local Postgres smoke verification

**Files (no code changes — verification only):**

- [ ] **Step 1: Start a local Postgres container.**

```bash
docker run -d --name cvp-pg-test \
  -e POSTGRES_PASSWORD=test \
  -e POSTGRES_USER=cvp \
  -e POSTGRES_DB=cvp \
  -p 5433:5432 \
  postgres:16-alpine
sleep 3
```

(Port 5433 to avoid clashing with any local Postgres on 5432.)

- [ ] **Step 2: Apply migrations against Postgres.**

```bash
DATABASE_URL="postgresql+psycopg://cvp:test@localhost:5433/cvp" \
  uv run alembic upgrade head
```

Expected: completes without error. **If this fails, stop and fix the offending migration.** Common failures: SQLite-specific SQL, JSONB references, AUTOINCREMENT keyword. Re-run Tasks 4 and 5 to find the missed case.

- [ ] **Step 3: Run the seed against Postgres.**

```bash
DATABASE_URL="postgresql+psycopg://cvp:test@localhost:5433/cvp" \
  uv run seed
DATABASE_URL="postgresql+psycopg://cvp:test@localhost:5433/cvp" \
  uv run seed
```

Expected: both runs succeed. The second run is the idempotency proof.

- [ ] **Step 4: Run bootstrap-admin against Postgres.**

```bash
DATABASE_URL="postgresql+psycopg://cvp:test@localhost:5433/cvp" \
INITIAL_ADMIN_EMAIL="smoke-test@example.com" \
INITIAL_ADMIN_PASSWORD="not-a-real-password-9d3f" \
  uv run bootstrap-admin
```

Expected: `bootstrap-admin: created initial admin smoke-test@example.com`

Run again:

```bash
DATABASE_URL="postgresql+psycopg://cvp:test@localhost:5433/cvp" \
INITIAL_ADMIN_EMAIL="smoke-test@example.com" \
INITIAL_ADMIN_PASSWORD="not-a-real-password-9d3f" \
  uv run bootstrap-admin
```

Expected: `bootstrap-admin: skipped (existing admin present)`

- [ ] **Step 5: Boot the app against Postgres and hit /healthz.**

```bash
DATABASE_URL="postgresql+psycopg://cvp:test@localhost:5433/cvp" \
  uv run uvicorn cvp.main:app --port 8001 &
sleep 3
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8001/healthz
kill %1
```

Expected: `200`

- [ ] **Step 6: Tear down Postgres.**

```bash
docker rm -f cvp-pg-test
```

- [ ] **Step 7: No commit.** Smoke verification doesn't change files.

If anything in this task failed, fix the offending code and re-run the smoke from the failing step.

---

## Task 11: Create the Dockerfile

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`

- [ ] **Step 1: Create `.dockerignore`.**

```
.git
.venv
.venv-*
venv
data
backups
tmp
__pycache__
*.pyc
.pytest_cache
.ruff_cache
.env
.env.*
!.env.example
docs
tests
.github
```

(Excluding `tests` and `docs` shrinks the image; they're never needed at runtime.)

- [ ] **Step 2: Create `Dockerfile`.**

```dockerfile
# syntax=docker/dockerfile:1.7
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# WeasyPrint native deps + libpq for psycopg
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libcairo2 \
        libffi8 \
        libpq5 \
        fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# uv binary (matches local toolchain)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Dependency layer — re-runs only when pyproject.toml or uv.lock changes
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# App layer
COPY . .
RUN uv sync --frozen --no-dev

EXPOSE 8000

# proxy-headers needed because we sit behind Cloudflare + Render's LB
CMD ["uv", "run", "uvicorn", "cvp.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--proxy-headers", \
     "--forwarded-allow-ips", "*"]
```

- [ ] **Step 3: Build the image locally.**

```bash
docker build -t cvp:test .
```

Expected: build succeeds. Inspect total layers and size:

```bash
docker images cvp:test
```

Expected size: 250–350 MB.

- [ ] **Step 4: Smoke-run the image with SQLite (no DB required).**

```bash
docker run --rm -d --name cvp-image-smoke \
  -p 8002:8000 \
  -e DATABASE_URL="sqlite:////tmp/cvp.db" \
  -e ENVIRONMENT="development" \
  -e SECRET_KEY="not-real-just-smoke-test-key-1234567890abcdef" \
  -e ANTHROPIC_API_KEY="not-real" \
  -e APP_BASE_URL="http://localhost:8002" \
  cvp:test
sleep 4
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8002/healthz
docker rm -f cvp-image-smoke
```

Expected: `200`. If it's anything else, exec into the running container and inspect logs:

```bash
docker logs cvp-image-smoke
```

- [ ] **Step 5: Commit.**

```bash
git add Dockerfile .dockerignore
git commit -m "feat(docker): add production Dockerfile for Render deployment"
```

---

## Task 12: Create `.env.example`

**Files:**
- Create: `.env.example`

- [ ] **Step 1: Write the file.**

`.env.example`:

```
# Copy to .env for local dev. Never commit the real .env.

# Local dev defaults to a SQLite file under ./data/. Set DATABASE_URL
# only when pointing at Postgres for testing.
# DATABASE_URL=postgresql+psycopg://cvp:cvp@localhost:5432/cvp

# Random 64-byte string. Generate with:
#   python -c "import secrets; print(secrets.token_hex(64))"
SECRET_KEY=

# Anthropic API key (for vision calls).
ANTHROPIC_API_KEY=

# Public base URL of the app (used by MFA QR issuer, email links, etc.).
APP_BASE_URL=http://localhost:8000

# development | production
ENVIRONMENT=development

# Used ONLY by `uv run bootstrap-admin` on first deploy.
# Remove after the first admin has logged in and created additional accounts.
INITIAL_ADMIN_EMAIL=
INITIAL_ADMIN_PASSWORD=
```

- [ ] **Step 2: Commit.**

```bash
git add .env.example
git commit -m "docs: add .env.example with all required env vars"
```

---

## Task 13: Create GitHub Actions CI workflow

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Write the workflow.**

`.github/workflows/ci.yml`:

```yaml
name: ci

on:
  push:
    branches: [main]
  pull_request:

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

jobs:
  lint:
    name: lint
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
        with:
          version: latest
      - name: Install deps
        run: uv sync --frozen
      - name: Ruff check
        run: uv run ruff check .
      - name: Ruff format check
        run: uv run ruff format --check .

  test:
    name: test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
        with:
          version: latest
      - name: Install deps
        run: uv sync --frozen
      - name: System libs for WeasyPrint
        run: |
          sudo apt-get update
          sudo apt-get install -y libpango-1.0-0 libpangoft2-1.0-0 libcairo2 libffi8 fonts-liberation
      - name: Run pytest
        run: uv run pytest

  secrets:
    name: secrets-scan
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: gitleaks/gitleaks-action@v2
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

- [ ] **Step 2: Validate locally where possible.**

You cannot run the workflow locally without `act`. As a sanity check, ensure the YAML parses:

```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"
```

Expected: no output (valid YAML).

- [ ] **Step 3: Commit.**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add lint + test + secrets-scan GitHub Actions workflow"
```

The workflow won't actually run until pushed to GitHub on a branch CI watches.

---

## Task 14: Create `docs/RUNBOOK.md`

**Files:**
- Create: `docs/RUNBOOK.md`

- [ ] **Step 1: Write the runbook.**

`docs/RUNBOOK.md`:

```markdown
# Production Runbook

Operational runbook for the production deployment on Render. Linked from `docs/superpowers/specs/2026-04-29-hosting-design.md`.

---

## First-time deployment

1. **Provision Render Web Service**
   - New → Web Service → connect to GitHub repo, `main` branch.
   - Runtime: Docker (auto-detected from Dockerfile).
   - Plan: Starter ($7/mo).
   - Region: Oregon (or Virginia — pick once and stick with it).
   - Health check path: `/healthz`.
   - Pre-deploy command: `uv run alembic upgrade head && uv run seed && uv run bootstrap-admin`.
   - Persistent disk: 10 GB, mount path `/app/data`.

2. **Provision Render Postgres**
   - New → Postgres → Standard tier ($19/mo).
   - Same region as the web service.
   - Render auto-injects `DATABASE_URL` into the web service when linked.

3. **Set environment variables (Secret type)**
   - `ANTHROPIC_API_KEY`
   - `SECRET_KEY` (generate fresh: `python -c "import secrets; print(secrets.token_hex(64))"`)
   - `INITIAL_ADMIN_EMAIL`
   - `INITIAL_ADMIN_PASSWORD`
   - `APP_BASE_URL` (e.g. `https://cvp.your-domain.tld`)
   - `ENVIRONMENT` = `production`

4. **Configure Cloudflare DNS**
   - In Cloudflare dashboard → DNS for your-domain.tld:
     - Add CNAME `cvp` → `<app-name>.onrender.com`, **proxied (orange cloud)**.
   - SSL/TLS → Overview → encryption mode: **Full (strict)**.
   - Page Rules / Cache Rules → "Bypass cache" for `cvp.your-domain.tld/*`.
   - If first cert issuance hangs (Render shows "issuing"), gray-cloud the
     CNAME for ~5 minutes until Render shows the cert as live, then orange
     it again.

5. **First login**
   - Visit `https://cvp.your-domain.tld`.
   - Sign in with the bootstrap admin credentials.
   - Complete MFA setup via the user-profile flow.
   - Create real admin accounts for any other founders.
   - **Remove `INITIAL_ADMIN_PASSWORD` from Render env vars.**

---

## Disaster recovery

### Scenario 1: Bad deploy went live

1. Render dashboard → Web Service → Events.
2. Find the previous successful deploy → "Rollback to this deploy".
3. ~30 seconds to swap. Healthcheck verifies before traffic moves.

### Scenario 2: Wrong matter deleted (data loss in last 7 days)

**Destructive — all data after the recovery point will be lost. Coordinate with the team before clicking.**

1. Render dashboard → Postgres service → Recovery → Point-in-time recovery.
2. Pick the timestamp just before the deletion.
3. Render restores into a NEW database. Verify the data, then update the web service's `DATABASE_URL` to point at the new instance, OR have Render swap.
4. Decommission the old DB once the new one is verified.

### Scenario 3: Render is down (extended)

For outages over a few hours, restore the most recent Postgres snapshot to a temporary host and redeploy the container elsewhere. Don't pre-build automation for this — it's vanishingly rare. Re-evaluate if it ever happens once.

---

## Routine operations

### Updating the bootstrap admin password (forgot the password before MFA was set)

1. SSH into Render Shell.
2. Set `INITIAL_ADMIN_PASSWORD` to a new value in env vars.
3. Open a Render Shell → run `uv run bootstrap-admin`. **It will skip** because the admin already exists.
4. Better path: use the admin password-reset flow added in commit `001b760` from another admin account.
5. If no other admin exists and password is lost: connect to Postgres directly (Render dashboard → Connect → External connection string) and update the `password_hash` for the user. This is a last-resort manual operation.

### Manually re-running the seed

Pre-deploy already runs it on every deploy; manual re-runs are rarely needed. If required:

```
Render Shell → uv run seed
```

Idempotent; safe to run anytime.
```

- [ ] **Step 2: Commit.**

```bash
git add docs/RUNBOOK.md
git commit -m "docs: add production runbook for first deploy and disaster recovery"
```

---

## Task 15: Update README with first-deploy quickstart

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Read existing `README.md`** to find the right section to insert deployment instructions (likely after "Local development" or at the end).

- [ ] **Step 2: Add a "Production deployment" section.**

Insert this block at an appropriate spot:

```markdown
## Production deployment

This app is designed to run on Render (web + Postgres) behind Cloudflare. See `docs/RUNBOOK.md` for the full first-deploy runbook and `docs/superpowers/specs/2026-04-29-hosting-design.md` for the architecture rationale.

Quick summary:

1. Create a Render Web Service from this repo (Dockerfile auto-detected).
2. Provision Render Postgres Standard, link it to the web service.
3. Set required env vars (see `.env.example` — `SECRET_KEY`, `ANTHROPIC_API_KEY`, `APP_BASE_URL`, `INITIAL_ADMIN_EMAIL`, `INITIAL_ADMIN_PASSWORD`, `ENVIRONMENT=production`).
4. Configure pre-deploy command: `uv run alembic upgrade head && uv run seed && uv run bootstrap-admin`.
5. Configure healthcheck path: `/healthz`.
6. Add 10 GB persistent disk mounted at `/app/data`.
7. Configure Cloudflare CNAME (proxied) and SSL mode Full (strict).
8. Deploy. Log in with bootstrap credentials, complete MFA, **then remove `INITIAL_ADMIN_PASSWORD` from Render env vars**.
```

- [ ] **Step 3: Commit.**

```bash
git add README.md
git commit -m "docs: add production deployment section to README"
```

---

## Task 16: Update CLAUDE.md per spec §9

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Re-read spec §9** of `docs/superpowers/specs/2026-04-29-hosting-design.md` for the canonical list of changes.

- [ ] **Step 2: Apply each change to `CLAUDE.md`.**

Specifically:

1. In "Tech stack" section: change "SQLite + SQLAlchemy 2.x + Alembic" → "Postgres in production (Render); SQLite supported for local development. SQLAlchemy 2.x + Alembic."

2. In "Tech stack" section, "Do not add" line: remove `Postgres` from the deny list. (Leave Docker if currently denied — Docker for the production runtime is now approved; update the line accordingly.)

3. In "Immutable domain rules" section, **rule 7**: replace with —

```
7. **Approved cloud services: Anthropic API, Render (web + Postgres + persistent disk), Cloudflare (DNS, registrar, proxy).** Not approved without re-discussion: S3/R2, Redis, Vercel, Celery, additional managed services. Docker is approved as the production runtime; local development still runs on host Python.
```

4. In "Immutable domain rules" section, **rule 6** (the "no customer-facing auth" rule): replace with —

```
6. **No public registration. Attorneys do not log in (they receive PDF/CSV by email). Internal specialists and approved external collaborators authenticate via the existing auth/MFA/RBAC system.**
```

5. In "Commands" section: add a row for `uv run bootstrap-admin` next to the seed commands. Suggested text: `uv run bootstrap-admin   # idempotent first-deploy admin bootstrap (see docs/RUNBOOK.md)`.

6. In "Project layout" section: add the new top-level files to the directory tree:
   - `Dockerfile`
   - `docs/RUNBOOK.md`
   - `docs/BACKLOG.md`
   - `.github/workflows/ci.yml`
   - `.env.example`

7. In "Useful references" section, add:
   - `@docs/RUNBOOK.md` — production runbook
   - `@docs/BACKLOG.md` — deferred work tracker
   - `@docs/superpowers/specs/2026-04-29-hosting-design.md` — hosting design

- [ ] **Step 3: Commit.**

```bash
git add CLAUDE.md
git commit -m "docs(claude): update project rules to reflect Render+Postgres deployment"
```

---

## Task 17: Pre-publication secrets scan

**Files (no code changes):**

- [ ] **Step 1: Install gitleaks if not present.**

```bash
brew install gitleaks
```

- [ ] **Step 2: Scan the full git history.**

```bash
gitleaks detect --source . --redact --verbose
```

Expected: no findings. If anything is reported:
1. **Stop and report to the operator.** Do not auto-rewrite history.
2. Operator decides whether to use `git filter-repo` to scrub before public release.

- [ ] **Step 3: Document the scan result.**

Append a note to the executor's final report:

```
gitleaks scan: <PASS / FAIL with summary>
Scan command: gitleaks detect --source . --redact --verbose
Date: <YYYY-MM-DD>
```

- [ ] **Step 4: No commit unless the scan turned up something requiring a fix.**

---

## Task 18: Final verification

**Files (no code changes — verification only):**

- [ ] **Step 1: Run the full test suite.**

```bash
uv run pytest
```

Expected: green.

- [ ] **Step 2: Run lint.**

```bash
uv run ruff check .
uv run ruff format --check .
```

Expected: no findings.

- [ ] **Step 3: Re-run the local Postgres smoke (Task 10).**

This time the runs should reflect every code change made during the implementation, not just the early ones.

- [ ] **Step 4: Re-build and smoke the Docker image.**

```bash
docker build -t cvp:final .
docker run --rm -d --name cvp-final \
  -p 8003:8000 \
  -e DATABASE_URL="sqlite:////tmp/cvp.db" \
  -e ENVIRONMENT="development" \
  -e SECRET_KEY="not-real-just-final-smoke-key-1234567890abcdef" \
  -e ANTHROPIC_API_KEY="not-real" \
  -e APP_BASE_URL="http://localhost:8003" \
  cvp:final
sleep 4
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8003/healthz
docker logs cvp-final | tail -20
docker rm -f cvp-final
```

Expected: `200` from healthz; clean log output.

- [ ] **Step 5: Cross-check spec acceptance criteria.**

Open `docs/superpowers/specs/2026-04-29-hosting-design.md` §11 and tick off each acceptance criterion against the work done. Any unchecked criterion is a missing task — go back and fix.

- [ ] **Step 6: Final report to operator.**

Output a summary covering:
- Tasks completed.
- Test suite status.
- gitleaks scan result.
- Local Postgres smoke result.
- Docker smoke result.
- Any spec acceptance criteria still open (should be none).
- Any TODOs added to `docs/BACKLOG.md` during execution.

The operator then takes over for the actual Render + Cloudflare provisioning (Task 14 runbook).

---

## Done

The implementation phase is complete when Task 18 passes cleanly. Provisioning the Render and Cloudflare resources is a manual operator step; the runbook in `docs/RUNBOOK.md` walks through it.

The R2 evidence-storage migration and offsite-backup work are tracked in `docs/BACKLOG.md` and are explicitly out of scope for this plan.
