# Contents Valuation Prototype

Internal ops tool for producing **Contents Inventory and Valuation Reports** for first-party property insurance claims. Built for Los Angeles attorneys handling Palisades and Eaton fire cases.

This is **not a customer-facing application.** Attorneys never log in. Specialists use it to build reports; attorneys receive the finished PDF and CSV by email.

---

## What it does

A specialist receives a folder of photos, video walkthroughs, and a partial inventory spreadsheet from an attorney. The tool helps them:

1. Create a **matter** (one claim = one matter) with all policy and policyholder metadata
2. **Upload evidence** — photos, receipts, policy documents — stored locally
3. **Scan photos with Claude Vision** to generate draft line items from images
4. **Review and confirm items** — correct descriptions, assign rooms, enter ages and quantities
5. **Price each item** — paste a retailer URL, capture the price, record match type and source
6. **Compute ACV automatically** using a straight-line depreciation schedule with condition multipliers and category floors
7. **Preview the report** as a full HTML render before export
8. **Export** a polished PDF and a Xactimate-compatible CSV

---

## System requirements

- **macOS** (tested on macOS 14+)
- **Python 3.11+**
- **[uv](https://docs.astral.sh/uv/)** — Python package and environment manager
- **Homebrew** packages for PDF rendering:

```bash
brew install pango cairo libffi
```

> WeasyPrint (the PDF engine) requires Pango and Cairo system libraries. The app will fail loudly at PDF export time if these are missing.

---

## Local development setup

### 1. Clone the repository

```bash
git clone <repo-url>
cd tor
```

### 2. Install Python dependencies

```bash
uv sync
```

This creates a `.venv/` in the project root and installs all runtime and dev dependencies.

### 3. Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and fill in your values. At minimum you need:

```
ANTHROPIC_API_KEY=sk-ant-...    # Required for Vision scans
```

The other variables have sensible defaults and can be left as-is for local development.

### 4. Apply database migrations

```bash
uv run alembic upgrade head
```

This creates `./data/cvp.db` (SQLite) and applies all schema migrations. The `./data/uploads/` and `./data/exports/` directories are created automatically on first run.

### 5. Seed the category table

```bash
uv run seed
```

Populates the 42 depreciation categories from `docs/depreciation-schedule.md`. This command is idempotent — safe to run multiple times.

### 6. Start the development server

```bash
uv run dev
```

Opens the app at **http://127.0.0.1:8000** with auto-reload enabled.

---

## Project layout

```
src/cvp/
├── main.py            # FastAPI app entry point, dashboard route
├── config.py          # pydantic-settings — reads from .env
├── db.py              # SQLAlchemy engine, WAL mode, session factory
├── models.py          # ORM models: matters, rooms, items, categories, evidence_files, vision_runs
├── seed.py            # 42-category seed data (idempotent)
├── depreciation.py    # Depreciation formula — pure functions, unit-tested  [Phase 4]
├── routers/           # FastAPI routers: matters, evidence, items, rooms, vision, exports
├── services/          # vision.py, pdf_generator.py, csv_export.py
├── templates/         # Jinja2 templates
│   ├── base.html
│   ├── dashboard.html
│   └── report/        # Report section templates for preview and PDF
└── static/
    └── app.js

migrations/            # Alembic migration files
tests/                 # pytest test suite
docs/
├── PRD.md                      # Full product requirements
├── data-model.md               # Schema rationale and migration history
└── depreciation-schedule.md    # The 42-category useful-life table (source of truth)
data/                  # gitignored — created at runtime
├── cvp.db             # SQLite database
├── uploads/           # Evidence files (photos, PDFs, etc.)
└── exports/           # Generated PDFs and CSVs
```

---

## Available commands

| Command | Description |
|---|---|
| `uv sync` | Install / update all dependencies |
| `uv run dev` | Start the dev server at localhost:8000 with auto-reload |
| `uv run alembic upgrade head` | Apply all pending migrations |
| `uv run alembic revision --autogenerate -m "description"` | Generate a new migration from model changes |
| `uv run seed` | Populate the 42 depreciation categories (idempotent) |
| `uv run pytest` | Run the full test suite |
| `uv run ruff check .` | Lint |
| `uv run ruff format .` | Format |
| `uv run backup` | Archive `./data/` to `./backups/<timestamp>.tar.gz` |

---

## Running tests

```bash
uv run pytest
```

To run with verbose output:

```bash
uv run pytest -v
```

To run a specific test file:

```bash
uv run pytest tests/test_seed.py -v
```

### Test coverage by module

| Module | Coverage target | What's tested |
|---|---|---|
| `depreciation.py` | Near 100% | Normal case, zero age, age > useful life, floor enforcement, condition multipliers, override, null useful life, fractional age, quantity scaling, edge RCV values |
| `csv_export.py` | High | Exact Xactimate column headers, currency formatting, row count vs confirmed non-excluded items |
| `seed.py` | Full | 42 categories inserted, idempotency, all IDs present, non-depreciable flags |
| Routers | Happy path | One integration test per route |
| Vision service | Mocked | API response parsing, draft item creation |

> Tests use an in-memory SQLite database. They never touch `./data/cvp.db`.

---

## Data model overview

Six tables:

- **matters** — one row per insurance claim; holds all policy metadata, status, and delivery tracking
- **rooms** — named spaces within the insured property (bedroom, kitchen, etc.), linked to a matter
- **items** — the core inventory: one row per line item with RCV, ACV, source citation, and confirmation state
- **categories** — 42 rows from `docs/depreciation-schedule.md`; drives the depreciation formula; read-only in v0
- **evidence_files** — uploaded photos, PDFs, and other files; tracks scan status
- **vision_runs** — one row per Claude Vision API call; stores the raw response for auditing

All currency is stored as **integer cents**. Conversion to dollars happens only at the display and export layer.

Full schema rationale in `docs/data-model.md`.

---

## Depreciation formula

```
straight_line_dep_rate  = 1 / useful_life_years
accumulated_dep         = min(straight_line_dep_rate × age_years × condition_multiplier,
                              1 − acv_floor_pct)
acv_unit_cents          = round(rcv_unit_cents × (1 − accumulated_dep))
acv_total_cents         = acv_unit_cents × quantity
```

**Condition multipliers:**

| Condition | Multiplier |
|---|---|
| Excellent | 0.75 |
| Above average | 0.90 |
| Average | 1.00 |
| Below average | 1.15 |

Items in non-depreciable categories (artwork, jewelry, collectibles, precious metals) are presented at RCV with no depreciation applied. Full methodology in `docs/depreciation-schedule.md`.

---

## Configuration reference

All settings are read from `.env` at startup via pydantic-settings. Every variable has a default so the app works for development without a complete `.env` file (except Vision scans, which require `ANTHROPIC_API_KEY`).

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | `""` | Required for Claude Vision photo scanning |
| `VISION_MODEL` | `claude-opus-4-6` | Model used for Vision scans |
| `VISION_MODEL_FALLBACK` | `claude-sonnet-4-6` | Fallback model |
| `DATABASE_URL` | `sqlite:///./data/cvp.db` | SQLite database path |
| `UPLOAD_DIR` | `./data/uploads` | Where evidence files are stored |
| `EXPORT_DIR` | `./data/exports` | Where PDFs and CSVs are written |
| `COMPANY_NAME` | `Contents Valuation LLC` | Appears in report headers and footers |
| `COMPANY_ADDRESS` | `""` | Appears in report cover page |
| `COMPANY_EMAIL` | `""` | Appears in report cover page |
| `COMPANY_PHONE` | `""` | Appears in report cover page |

---

## Important constraints

- **No cloud services** beyond the Anthropic API. Everything runs on localhost.
- **No authentication.** Single-user tool. Do not add login, sessions, or roles.
- **Currency is always integer cents.** Never use Python `float` for currency math.
- **Vision scans are sequential** with a 500ms pause between images. Do not parallelize.
- **Do not commit** `.env`, `./data/`, or `./backups/` — all are gitignored.
- Reports are **attorney work product** and include a "Confidential — Attorney Work Product" marker.

---

## Tech stack

| Layer | Choice |
|---|---|
| Language | Python 3.11+ |
| Web framework | FastAPI |
| Templates | Jinja2 (server-rendered) |
| Frontend | HTMX + Tailwind CSS via CDN (no build step) |
| Database | SQLite via SQLAlchemy 2.x |
| Migrations | Alembic |
| PDF rendering | WeasyPrint |
| AI | Anthropic Python SDK (Claude Vision) |
| Package manager | uv |
| Lint / format | ruff |
| Tests | pytest |
