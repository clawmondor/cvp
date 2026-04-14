# Phase 1 — Skeleton and Data Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Boot the FastAPI app on `localhost:8000` with a dashboard page showing "No matters yet", SQLite database with all 6 tables migrated, 42 categories seeded, and `uv run pytest` passing with seed confirmation tests.

**Architecture:** Python package `cvp` under `src/cvp/`, FastAPI with Jinja2 server-side rendering, SQLAlchemy 2.x ORM with Alembic migrations, pydantic-settings for config. All state in a local SQLite file under `./data/`.

**Tech Stack:** Python 3.11+, uv, FastAPI, Jinja2, Tailwind CSS CDN, HTMX, SQLAlchemy 2.x, Alembic, pydantic-settings, pytest, ruff.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `pyproject.toml` | Create | Package metadata, dependencies, entry-point scripts, dev tools |
| `.gitignore` | Create | Exclude .env, data/, backups/, __pycache__ |
| `.env.example` | Create | Template for all required env vars |
| `alembic.ini` | Create | Alembic configuration |
| `src/cvp/__init__.py` | Create | Package marker |
| `src/cvp/config.py` | Create | pydantic-settings Settings class; read from .env |
| `src/cvp/models.py` | Create | SQLAlchemy 2.x declarative models for all 6 tables |
| `src/cvp/db.py` | Create | Engine + WAL mode + SessionLocal + get_db dependency |
| `src/cvp/seed.py` | Create | 42-category constant + idempotent seed_categories() + main() |
| `src/cvp/main.py` | Create | FastAPI app, startup dir-creation, dashboard route, run_dev() |
| `src/cvp/routers/__init__.py` | Create | Package marker |
| `src/cvp/templates/base.html` | Create | HTML shell — Tailwind CDN, HTMX, nav with "New matter" button |
| `src/cvp/templates/dashboard.html` | Create | Matters table or "No matters yet" empty state |
| `src/cvp/static/app.js` | Create | Minimal JS placeholder |
| `migrations/env.py` | Create | Alembic env.py — imports models, overrides DB URL from config |
| `migrations/script.py.mako` | Create | Alembic migration file template |
| `tests/__init__.py` | Create | Package marker |
| `tests/test_seed.py` | Create | 4 seed confirmation tests |

---

## Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.env.example`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "cvp"
version = "0.1.0"
description = "Contents Valuation Prototype — internal ops tool"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "jinja2>=3.1",
    "python-multipart>=0.0.9",
    "sqlalchemy>=2.0",
    "alembic>=1.13",
    "pydantic-settings>=2.0",
    "anthropic>=0.40",
    "weasyprint>=62",
    "pandas>=2.2",
]

[dependency-groups]
dev = [
    "pytest>=8.0",
    "ruff>=0.6",
    "httpx>=0.27",
]

[project.scripts]
dev = "cvp.main:run_dev"
seed = "cvp.seed:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatchling.build.targets.wheel]
packages = ["src/cvp"]

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.ruff]
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I"]
```

- [ ] **Step 2: Create `.gitignore`**

```
.env
data/
backups/
__pycache__/
*.pyc
.venv/
*.egg-info/
dist/
.ruff_cache/
.pytest_cache/
```

- [ ] **Step 3: Create `.env.example`**

```
ANTHROPIC_API_KEY=sk-ant-...
VISION_MODEL=claude-opus-4-6
VISION_MODEL_FALLBACK=claude-sonnet-4-6
DATABASE_URL=sqlite:///./data/cvp.db
UPLOAD_DIR=./data/uploads
EXPORT_DIR=./data/exports
COMPANY_NAME=Acme Contents Valuation LLC
COMPANY_ADDRESS=123 Main St, El Segundo, CA 90245
COMPANY_EMAIL=hello@example.com
COMPANY_PHONE=+1 (555) 555-0100
```

- [ ] **Step 4: Install dependencies**

```bash
cd /Users/cmondor/consulting/tor
uv sync
```

Expected: Resolves and installs all packages into `.venv/`. No errors.

- [ ] **Step 5: Commit**

```bash
git init
git add pyproject.toml .gitignore .env.example
git commit -m "chore: initial project scaffold"
```

---

## Task 2: Configuration module

**Files:**
- Create: `src/cvp/__init__.py`
- Create: `src/cvp/config.py`

- [ ] **Step 1: Create `src/cvp/__init__.py`**

Empty file — marks `src/cvp` as a Python package.

- [ ] **Step 2: Create `src/cvp/config.py`**

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    anthropic_api_key: str = ""
    vision_model: str = "claude-opus-4-6"
    vision_model_fallback: str = "claude-sonnet-4-6"
    database_url: str = "sqlite:///./data/cvp.db"
    upload_dir: str = "./data/uploads"
    export_dir: str = "./data/exports"
    company_name: str = "Contents Valuation LLC"
    company_address: str = ""
    company_email: str = ""
    company_phone: str = ""


settings = Settings()
```

- [ ] **Step 3: Verify import**

```bash
uv run python -c "from cvp.config import settings; print(settings.database_url)"
```

Expected output: `sqlite:///./data/cvp.db`

---

## Task 3: ORM models

**Files:**
- Create: `src/cvp/models.py`

- [ ] **Step 1: Create `src/cvp/models.py`**

```python
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


def _new_uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Matter(Base):
    __tablename__ = "matters"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    firm_name: Mapped[str] = mapped_column(String, default="")
    attorney_name: Mapped[str] = mapped_column(String, default="")
    attorney_email: Mapped[str] = mapped_column(String, default="")
    policyholder_name: Mapped[str] = mapped_column(String, default="")
    loss_location: Mapped[str] = mapped_column(String, default="")
    loss_type: Mapped[str] = mapped_column(String, default="total_loss")
    loss_event: Mapped[str] = mapped_column(String, default="")
    loss_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    carrier: Mapped[str] = mapped_column(String, default="")
    policy_number: Mapped[str] = mapped_column(String, default="")
    claim_number: Mapped[str] = mapped_column(String, default="")
    coverage_c_limit: Mapped[int] = mapped_column(Integer, default=0)
    firm_file_number: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default="draft")
    target_delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    delivered_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    invoice_amount_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    internal_notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    rooms: Mapped[list["Room"]] = relationship(
        "Room", back_populates="matter", cascade="all, delete-orphan"
    )
    items: Mapped[list["Item"]] = relationship(
        "Item", back_populates="matter", cascade="all, delete-orphan"
    )
    evidence_files: Mapped[list["EvidenceFile"]] = relationship(
        "EvidenceFile", back_populates="matter", cascade="all, delete-orphan"
    )
    vision_runs: Mapped[list["VisionRun"]] = relationship(
        "VisionRun", back_populates="matter", cascade="all, delete-orphan"
    )


class Room(Base):
    __tablename__ = "rooms"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    matter_id: Mapped[str] = mapped_column(String, ForeignKey("matters.id"), nullable=False)
    name: Mapped[str] = mapped_column(String)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    matter: Mapped["Matter"] = relationship("Matter", back_populates="rooms")
    items: Mapped[list["Item"]] = relationship("Item", back_populates="room")


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    useful_life_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    acv_floor_pct: Mapped[float] = mapped_column(Float, nullable=False)
    notes: Mapped[str] = mapped_column(String, default="")

    items: Mapped[list["Item"]] = relationship("Item", back_populates="category")


class Item(Base):
    __tablename__ = "items"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    matter_id: Mapped[str] = mapped_column(String, ForeignKey("matters.id"), nullable=False)
    room_id: Mapped[str | None] = mapped_column(String, ForeignKey("rooms.id"), nullable=True)
    category_id: Mapped[int] = mapped_column(Integer, ForeignKey("categories.id"), nullable=False)
    line_number: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[str] = mapped_column(String, default="")
    brand: Mapped[str | None] = mapped_column(String, nullable=True)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    age_years: Mapped[float] = mapped_column(Float, default=0.0)
    condition: Mapped[str] = mapped_column(String, default="average")
    rcv_unit_cents: Mapped[int] = mapped_column(Integer, default=0)
    rcv_total_cents: Mapped[int] = mapped_column(Integer, default=0)
    acv_total_cents: Mapped[int] = mapped_column(Integer, default=0)
    acv_override_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    acv_override_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    match_type: Mapped[str] = mapped_column(String, default="exact")
    source_retailer: Mapped[str] = mapped_column(String, default="")
    source_url: Mapped[str] = mapped_column(String, default="")
    source_captured_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source_screenshot_path: Mapped[str | None] = mapped_column(String, nullable=True)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    excluded: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    matter: Mapped["Matter"] = relationship("Matter", back_populates="items")
    room: Mapped["Room | None"] = relationship("Room", back_populates="items")
    category: Mapped["Category"] = relationship("Category", back_populates="items")


class EvidenceFile(Base):
    __tablename__ = "evidence_files"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    matter_id: Mapped[str] = mapped_column(String, ForeignKey("matters.id"), nullable=False)
    filename: Mapped[str] = mapped_column(String)
    stored_path: Mapped[str] = mapped_column(String)
    mime_type: Mapped[str] = mapped_column(String, default="")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[str] = mapped_column(String, default="other")
    scanned: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    matter: Mapped["Matter"] = relationship("Matter", back_populates="evidence_files")
    vision_runs: Mapped[list["VisionRun"]] = relationship(
        "VisionRun", back_populates="evidence_file"
    )


class VisionRun(Base):
    __tablename__ = "vision_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    matter_id: Mapped[str] = mapped_column(String, ForeignKey("matters.id"), nullable=False)
    evidence_file_id: Mapped[str] = mapped_column(
        String, ForeignKey("evidence_files.id"), nullable=False
    )
    model: Mapped[str] = mapped_column(String, default="")
    prompt_version: Mapped[str] = mapped_column(String, default="")
    raw_response: Mapped[str] = mapped_column(Text, default="")
    items_created: Mapped[int] = mapped_column(Integer, default=0)
    ran_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    matter: Mapped["Matter"] = relationship("Matter", back_populates="vision_runs")
    evidence_file: Mapped["EvidenceFile"] = relationship(
        "EvidenceFile", back_populates="vision_runs"
    )
```

- [ ] **Step 2: Verify all 6 models import**

```bash
uv run python -c "
from cvp.models import Base, Matter, Room, Category, Item, EvidenceFile, VisionRun
print('OK — 6 models imported')
print('Tables:', list(Base.metadata.tables.keys()))
"
```

Expected:
```
OK — 6 models imported
Tables: ['matters', 'rooms', 'categories', 'items', 'evidence_files', 'vision_runs']
```

---

## Task 4: Database session

**Files:**
- Create: `src/cvp/db.py`

- [ ] **Step 1: Create `src/cvp/db.py`**

```python
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from cvp.config import settings


def _ensure_data_dirs() -> None:
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.export_dir).mkdir(parents=True, exist_ok=True)
    db_file = settings.database_url.replace("sqlite:///", "")
    Path(db_file).parent.mkdir(parents=True, exist_ok=True)


_ensure_data_dirs()

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def _set_wal_mode(dbapi_connection, connection_record) -> None:  # noqa: ANN001
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

- [ ] **Step 2: Verify engine and data directory creation**

```bash
uv run python -c "
from cvp.db import engine
import pathlib
print('Engine URL:', engine.url)
print('data/ exists:', pathlib.Path('./data').exists())
print('data/uploads/ exists:', pathlib.Path('./data/uploads').exists())
print('data/exports/ exists:', pathlib.Path('./data/exports').exists())
"
```

Expected:
```
Engine URL: sqlite:///./data/cvp.db
data/ exists: True
data/uploads/ exists: True
data/exports/ exists: True
```

---

## Task 5: Alembic setup

**Files:**
- Create: `alembic.ini`
- Create: `migrations/env.py`
- Create: `migrations/script.py.mako`

- [ ] **Step 1: Create `alembic.ini`**

```ini
[alembic]
script_location = migrations
prepend_sys_path = .
file_template = %%(year)d%%(month).2d%%(day).2d_%%(rev)s_%%(slug)s
truncate_slug_length = 40
timezone = UTC

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

- [ ] **Step 2: Create `migrations/env.py`**

```python
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from cvp.config import settings
from cvp.models import Base  # noqa: F401 — imported so autogenerate sees all tables

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 3: Create `migrations/script.py.mako`**

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

# revision identifiers, used by Alembic.
revision: str = ${repr(up_revision)}
down_revision: Union[str, None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

- [ ] **Step 4: Create versions directory**

```bash
mkdir -p /Users/cmondor/consulting/tor/migrations/versions
```

---

## Task 6: Generate and apply the initial migration

- [ ] **Step 1: Autogenerate the migration from the models**

```bash
cd /Users/cmondor/consulting/tor
uv run alembic revision --autogenerate -m "initial"
```

Expected: A file like `migrations/versions/20260414_<hash>_initial.py` is created with `op.create_table(...)` calls for all 6 tables.

If the command fails with `ModuleNotFoundError`, confirm `uv sync` ran successfully and the package is installed.

- [ ] **Step 2: Apply the migration**

```bash
uv run alembic upgrade head
```

Expected output ends with: `Running upgrade  -> <hash>, initial`

- [ ] **Step 3: Verify all tables exist**

```bash
uv run python -c "
from sqlalchemy import inspect
from cvp.db import engine
tables = sorted(inspect(engine).get_table_names())
print('Tables:', tables)
expected = {'matters', 'rooms', 'categories', 'items', 'evidence_files', 'vision_runs', 'alembic_version'}
assert expected.issubset(set(tables)), f'Missing: {expected - set(tables)}'
print('OK — all 6 domain tables created')
"
```

Expected:
```
Tables: ['alembic_version', 'categories', 'evidence_files', 'items', 'matters', 'rooms', 'vision_runs']
OK — all 6 domain tables created
```

- [ ] **Step 4: Commit**

```bash
git add alembic.ini migrations/ src/cvp/
git commit -m "feat: ORM models, Alembic config, initial migration"
```

---

## Task 7: Seed script

**Files:**
- Create: `src/cvp/seed.py`

- [ ] **Step 1: Create `src/cvp/seed.py`**

```python
"""
Category seed data from docs/depreciation-schedule.md.
Entry point: uv run seed
Idempotent: safe to run multiple times.
"""

from sqlalchemy.orm import Session

from cvp.db import SessionLocal
from cvp.models import Category

CATEGORIES: list[dict] = [
    {"id": 1, "name": "Clothing, everyday", "useful_life_years": 5, "acv_floor_pct": 0.20, "notes": "T-shirts, jeans, socks, underwear, casual wear"},
    {"id": 2, "name": "Clothing, outerwear and formal", "useful_life_years": 8, "acv_floor_pct": 0.20, "notes": "Coats, suits, dresses, formal wear"},
    {"id": 3, "name": "Clothing, children", "useful_life_years": 3, "acv_floor_pct": 0.20, "notes": "Shorter useful life due to outgrowth"},
    {"id": 4, "name": "Footwear", "useful_life_years": 4, "acv_floor_pct": 0.20, "notes": "Shoes, boots, sandals, athletic"},
    {"id": 5, "name": "Accessories (belts, bags, scarves, hats)", "useful_life_years": 6, "acv_floor_pct": 0.20, "notes": "Excludes designer handbags — see category 6"},
    {"id": 6, "name": "Designer handbags and luxury accessories", "useful_life_years": 10, "acv_floor_pct": 0.30, "notes": "Items over $500 at purchase; may need rider"},
    {"id": 7, "name": "Jewelry, non-appraised, within policy sublimit", "useful_life_years": None, "acv_floor_pct": 1.00, "notes": "Presented at RCV; often rider-covered"},
    {"id": 8, "name": "Watches (non-luxury, non-appraised)", "useful_life_years": 10, "acv_floor_pct": 0.25, "notes": "Casual and fashion watches"},
    {"id": 9, "name": "Furniture, upholstered (sofas, chairs)", "useful_life_years": 10, "acv_floor_pct": 0.20, "notes": "Fabric and leather upholstery"},
    {"id": 10, "name": "Furniture, wood case goods", "useful_life_years": 15, "acv_floor_pct": 0.25, "notes": "Tables, dressers, bookcases, desks"},
    {"id": 11, "name": "Furniture, mattresses and box springs", "useful_life_years": 8, "acv_floor_pct": 0.20, "notes": "Includes foundations"},
    {"id": 12, "name": "Bedding, linens, towels", "useful_life_years": 6, "acv_floor_pct": 0.20, "notes": "Sheets, duvets, pillowcases, bath linens"},
    {"id": 13, "name": "Window treatments (curtains, blinds, shades)", "useful_life_years": 10, "acv_floor_pct": 0.20, "notes": "Soft and hard window coverings"},
    {"id": 14, "name": "Rugs, machine-made", "useful_life_years": 10, "acv_floor_pct": 0.25, "notes": "Area rugs, runners, entry rugs"},
    {"id": 15, "name": "Rugs, handmade or antique", "useful_life_years": 25, "acv_floor_pct": 0.50, "notes": "Oriental, tribal, hand-knotted"},
    {"id": 16, "name": "Kitchen appliances, large", "useful_life_years": 12, "acv_floor_pct": 0.20, "notes": "Refrigerator, oven, dishwasher, washer, dryer"},
    {"id": 17, "name": "Kitchen appliances, small", "useful_life_years": 8, "acv_floor_pct": 0.20, "notes": "Toasters, blenders, coffee makers, mixers"},
    {"id": 18, "name": "Cookware, bakeware, utensils", "useful_life_years": 10, "acv_floor_pct": 0.25, "notes": "Pots, pans, knives, kitchen tools"},
    {"id": 19, "name": "Dinnerware, glassware, flatware", "useful_life_years": 15, "acv_floor_pct": 0.25, "notes": "Plates, bowls, glasses, silverware"},
    {"id": 20, "name": "Small kitchen goods (storage, serveware)", "useful_life_years": 8, "acv_floor_pct": 0.20, "notes": "Food containers, serving platters, dish towels"},
    {"id": 21, "name": "Electronics, TVs and displays", "useful_life_years": 7, "acv_floor_pct": 0.20, "notes": "TVs, monitors, projectors"},
    {"id": 22, "name": "Electronics, computers and tablets", "useful_life_years": 4, "acv_floor_pct": 0.20, "notes": "Laptops, desktops, iPads, Chromebooks"},
    {"id": 23, "name": "Electronics, smartphones", "useful_life_years": 3, "acv_floor_pct": 0.20, "notes": "Fastest-depreciating electronics category"},
    {"id": 24, "name": "Electronics, audio and home theater", "useful_life_years": 7, "acv_floor_pct": 0.20, "notes": "Speakers, receivers, soundbars"},
    {"id": 25, "name": "Electronics, cameras and lenses", "useful_life_years": 6, "acv_floor_pct": 0.25, "notes": "DSLRs, mirrorless, lenses, accessories"},
    {"id": 26, "name": "Electronics, gaming consoles and games", "useful_life_years": 5, "acv_floor_pct": 0.20, "notes": "PlayStation, Xbox, Nintendo, handhelds"},
    {"id": 27, "name": "Electronics, small and miscellaneous", "useful_life_years": 5, "acv_floor_pct": 0.20, "notes": "Routers, printers, chargers, cables"},
    {"id": 28, "name": "Books, records, physical media", "useful_life_years": 20, "acv_floor_pct": 0.25, "notes": "Books, vinyl, CDs, DVDs"},
    {"id": 29, "name": "Toys and games", "useful_life_years": 6, "acv_floor_pct": 0.20, "notes": "Children's toys, board games, puzzles"},
    {"id": 30, "name": "Sporting goods and exercise equipment", "useful_life_years": 8, "acv_floor_pct": 0.20, "notes": "Bikes, weights, treadmills, gear"},
    {"id": 31, "name": "Outdoor furniture and grills", "useful_life_years": 8, "acv_floor_pct": 0.20, "notes": "Patio sets, umbrellas, gas/charcoal grills"},
    {"id": 32, "name": "Outdoor equipment (lawn, garden, tools)", "useful_life_years": 10, "acv_floor_pct": 0.20, "notes": "Mowers, trimmers, hand tools, hoses"},
    {"id": 33, "name": "Power tools and workshop", "useful_life_years": 12, "acv_floor_pct": 0.25, "notes": "Drills, saws, compressors, workbenches"},
    {"id": 34, "name": "Hand tools and hardware", "useful_life_years": 15, "acv_floor_pct": 0.25, "notes": "Hammers, wrenches, screwdrivers, hardware"},
    {"id": 35, "name": "Musical instruments (non-appraised)", "useful_life_years": 20, "acv_floor_pct": 0.30, "notes": "Guitars, keyboards, drums, wind instruments"},
    {"id": 36, "name": "Artwork, non-appraised", "useful_life_years": None, "acv_floor_pct": 1.00, "notes": "Presented at RCV; often rider-covered"},
    {"id": 37, "name": "Collectibles and memorabilia", "useful_life_years": None, "acv_floor_pct": 1.00, "notes": "Presented at RCV; often rider-covered"},
    {"id": 38, "name": "Precious metals and coins", "useful_life_years": None, "acv_floor_pct": 1.00, "notes": "Presented at RCV; often rider-covered"},
    {"id": 39, "name": "Food, pantry, household consumables", "useful_life_years": 1, "acv_floor_pct": 0.20, "notes": "Non-perishables; perishables excluded from report"},
    {"id": 40, "name": "Personal care and cosmetics", "useful_life_years": 2, "acv_floor_pct": 0.20, "notes": "Toiletries, makeup, skincare"},
    {"id": 41, "name": "Office supplies and stationery", "useful_life_years": 5, "acv_floor_pct": 0.20, "notes": "Paper, pens, binders, small office equipment"},
    {"id": 42, "name": "Miscellaneous household goods", "useful_life_years": 8, "acv_floor_pct": 0.20, "notes": "Catch-all for items not fitting categories 1-41"},
]


def seed_categories(db: Session) -> int:
    """Insert all 42 categories; skip any that already exist. Returns count inserted."""
    inserted = 0
    for row in CATEGORIES:
        if db.get(Category, row["id"]) is None:
            db.add(Category(**row))
            inserted += 1
    db.commit()
    return inserted


def main() -> None:
    db = SessionLocal()
    try:
        count = seed_categories(db)
        print(f"Seed complete — {count} categories inserted (skipped existing).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the seed against the real DB**

```bash
uv run seed
```

Expected: `Seed complete — 42 categories inserted (skipped existing).`

- [ ] **Step 3: Verify idempotency**

```bash
uv run seed
```

Expected: `Seed complete — 0 categories inserted (skipped existing).`

- [ ] **Step 4: Commit**

```bash
git add src/cvp/seed.py
git commit -m "feat: add category seed script with 42 rows"
```

---

## Task 8: FastAPI skeleton and dashboard route

**Files:**
- Create: `src/cvp/routers/__init__.py`
- Create: `src/cvp/main.py`

- [ ] **Step 1: Create `src/cvp/routers/__init__.py`**

Empty file.

- [ ] **Step 2: Create `src/cvp/main.py`**

```python
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from cvp.db import SessionLocal
from cvp.models import Matter

BASE_DIR = Path(__file__).parent

app = FastAPI(title="Contents Valuation Prototype")

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    db = SessionLocal()
    try:
        matters = (
            db.query(Matter)
            .order_by(Matter.status, Matter.target_delivery_date)
            .all()
        )
    finally:
        db.close()
    return templates.TemplateResponse(
        "dashboard.html", {"request": request, "matters": matters}
    )


def run_dev() -> None:
    import uvicorn

    uvicorn.run("cvp.main:app", host="127.0.0.1", port=8000, reload=True)
```

---

## Task 9: Templates and static file

**Files:**
- Create: `src/cvp/static/app.js`
- Create: `src/cvp/templates/base.html`
- Create: `src/cvp/templates/dashboard.html`

- [ ] **Step 1: Create `src/cvp/static/app.js`**

```javascript
// Phase 1 placeholder — HTMX handles most interactivity.
```

- [ ] **Step 2: Create `src/cvp/templates/base.html`**

```html
<!doctype html>
<html lang="en" class="h-full bg-gray-50">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{% block title %}CVP{% endblock %} — Contents Valuation Prototype</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://unpkg.com/htmx.org@1.9.12"></script>
  <script src="/static/app.js" defer></script>
</head>
<body class="h-full">
  <nav class="bg-white border-b border-gray-200">
    <div class="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
      <div class="flex h-14 items-center justify-between">
        <a href="/" class="text-base font-semibold text-gray-900">Contents Valuation Prototype</a>
        <a href="/matters/new"
           class="rounded-md bg-indigo-600 px-3 py-1.5 text-sm font-semibold text-white shadow-sm hover:bg-indigo-500">
          New matter
        </a>
      </div>
    </div>
  </nav>
  <main class="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-8">
    {% block content %}{% endblock %}
  </main>
</body>
</html>
```

- [ ] **Step 3: Create `src/cvp/templates/dashboard.html`**

```html
{% extends "base.html" %}

{% block title %}Dashboard{% endblock %}

{% block content %}
<div class="sm:flex sm:items-center mb-6">
  <div class="sm:flex-auto">
    <h1 class="text-2xl font-semibold text-gray-900">Matters</h1>
    <p class="mt-1 text-sm text-gray-500">All active insurance matters tracked in this instance.</p>
  </div>
</div>

{% if matters %}
<div class="overflow-hidden shadow ring-1 ring-black ring-opacity-5 rounded-lg">
  <table class="min-w-full divide-y divide-gray-300">
    <thead class="bg-gray-50">
      <tr>
        <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Firm / Policyholder</th>
        <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Loss event</th>
        <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Status</th>
        <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Items</th>
        <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Target delivery</th>
      </tr>
    </thead>
    <tbody class="divide-y divide-gray-200 bg-white">
      {% for matter in matters %}
      <tr class="hover:bg-gray-50">
        <td class="px-4 py-3">
          <a href="/matters/{{ matter.id }}" class="font-medium text-indigo-600 hover:text-indigo-900">
            {{ matter.policyholder_name or "(unnamed)" }}
          </a>
          <p class="text-xs text-gray-500">{{ matter.firm_name }}</p>
        </td>
        <td class="px-4 py-3 text-sm text-gray-700">{{ matter.loss_event }}</td>
        <td class="px-4 py-3">
          <span class="inline-flex rounded-full px-2 py-0.5 text-xs font-medium
            {% if matter.status == 'draft' %}bg-gray-100 text-gray-700
            {% elif matter.status == 'in_review' %}bg-yellow-100 text-yellow-800
            {% elif matter.status == 'delivered' %}bg-green-100 text-green-800
            {% else %}bg-gray-100 text-gray-500{% endif %}">
            {{ matter.status | replace('_', ' ') | title }}
          </span>
        </td>
        <td class="px-4 py-3 text-sm text-gray-700">{{ matter.items | length }}</td>
        <td class="px-4 py-3 text-sm text-gray-700">{{ matter.target_delivery_date or "—" }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</div>
{% else %}
<div class="text-center py-20 text-gray-400">
  <p class="text-lg font-medium">No matters yet.</p>
  <p class="text-sm mt-1">
    Click <span class="font-semibold text-gray-600">New matter</span> in the header to get started.
  </p>
</div>
{% endif %}
{% endblock %}
```

- [ ] **Step 4: Smoke-test the server starts**

```bash
uv run python -c "
from cvp.main import app
print('App created:', app.title)
print('Routes:', [r.path for r in app.routes])
"
```

Expected:
```
App created: Contents Valuation Prototype
Routes: ['/static', '/', '/openapi.json', '/docs', '/docs/oauth2-redirect', '/redoc']
```

- [ ] **Step 5: Commit**

```bash
git add src/cvp/
git commit -m "feat: FastAPI skeleton, dashboard route, and Jinja2 templates"
```

---

## Task 10: Seed tests

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/test_seed.py`

- [ ] **Step 1: Create `tests/__init__.py`**

Empty file.

- [ ] **Step 2: Write the tests**

Create `tests/test_seed.py`:

```python
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from cvp.models import Base, Category
from cvp.seed import CATEGORIES, seed_categories


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_seed_creates_42_categories(db: Session) -> None:
    inserted = seed_categories(db)
    assert inserted == 42
    assert db.query(Category).count() == 42


def test_seed_is_idempotent(db: Session) -> None:
    seed_categories(db)
    second_run = seed_categories(db)
    assert second_run == 0  # nothing new inserted
    assert db.query(Category).count() == 42


def test_all_category_ids_present(db: Session) -> None:
    seed_categories(db)
    ids = {c.id for c in db.query(Category).all()}
    assert ids == set(range(1, 43))


def test_non_depreciable_categories_have_null_useful_life(db: Session) -> None:
    seed_categories(db)
    # IDs 7, 36, 37, 38 are non-depreciable per the depreciation schedule
    for cat_id in [7, 36, 37, 38]:
        cat = db.get(Category, cat_id)
        assert cat is not None
        assert cat.useful_life_years is None, f"Category {cat_id} should have null useful_life_years"
        assert cat.acv_floor_pct == 1.00, f"Category {cat_id} should have acv_floor_pct=1.0"
```

- [ ] **Step 3: Run the tests**

```bash
uv run pytest tests/test_seed.py -v
```

Expected:
```
tests/test_seed.py::test_seed_creates_42_categories PASSED
tests/test_seed.py::test_seed_is_idempotent PASSED
tests/test_seed.py::test_all_category_ids_present PASSED
tests/test_seed.py::test_non_depreciable_categories_have_null_useful_life PASSED

4 passed in 0.XXs
```

- [ ] **Step 4: Run full suite**

```bash
uv run pytest -v
```

Expected: Same 4 tests, all PASSED.

- [ ] **Step 5: Commit**

```bash
git add tests/
git commit -m "test: add seed confirmation tests for all 42 categories"
```

---

## Task 11: Acceptance criteria verification

- [ ] **Step 1: Run ruff**

```bash
uv run ruff check .
```

Expected: No output (no errors). If there are errors, fix them before proceeding.

- [ ] **Step 2: Run full test suite one final time**

```bash
uv run pytest -v
```

Expected: 4 tests, all PASSED.

- [ ] **Step 3: Start the development server**

```bash
uv run dev
```

Expected: Terminal shows `Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)`

- [ ] **Step 4: Open the dashboard**

Open a browser to `http://127.0.0.1:8000`.

Expected:
- Page title: "Dashboard — Contents Valuation Prototype"
- Nav bar with "Contents Valuation Prototype" text and "New matter" button
- Body shows the "No matters yet." empty state

- [ ] **Step 5: Confirm acceptance criteria checklist**

| Criterion (PRD §15 Phase 1) | Status |
|---|---|
| FastAPI app boots on localhost:8000 | ✓ |
| Dashboard shows "No matters yet" | ✓ |
| SQLite DB with migrations for all 6 tables | ✓ |
| Seed script populates 42 categories | ✓ |
| `uv run pytest` passes (seed test) | ✓ |

Stop here and report to the user for Phase 2 review.

---

## Self-review

**Spec coverage (PRD §15 Phase 1):**
- FastAPI boot → Tasks 8, 9, 11
- "No matters yet" dashboard → Task 9 (dashboard.html empty state)
- All 6 tables from §7 → Task 3 (models.py covers matters, rooms, categories, items, evidence_files, vision_runs)
- Seed 42 categories from depreciation-schedule.md → Task 7
- `uv run pytest` with seed test → Task 10

**Placeholder scan:** No TBD, TODO, or vague steps found.

**Type consistency:**
- `seed_categories(db: Session) -> int` defined in Task 7, called in Task 10 tests with matching signature
- `Category` model: `id: int`, `useful_life_years: int | None`, `acv_floor_pct: float` — used consistently in seed data and test assertions
- `_new_uuid() -> str` used as `default=` in all UUID-pk models
