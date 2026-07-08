# ClaimOS

Internal ops tool for producing **Contents Inventory and Valuation Reports** for first-party property insurance claims. Built for Los Angeles attorneys handling Palisades and Eaton fire cases.

This is **not a customer-facing application.** Attorneys never log in. Specialists use it to build reports; attorneys receive the finished PDF and CSV by email.

---

## What it does

A specialist receives a folder of photos, video walkthroughs, and a partial inventory spreadsheet from an attorney. The tool helps them:

1. Create a **claim** with all policy and policyholder metadata
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

Open `.env` and fill in the values below. The auth variables are new and required — the app will start without them but login will not work.

**Required for Vision scans:**
```
ANTHROPIC_API_KEY=sk-ant-...
```

**Required for authentication:**
```
# Generate with: python3 -c "import secrets; print(secrets.token_hex(32))"
JWT_SECRET=<64-char hex string>

# Generate with: uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
MFA_ENCRYPTION_KEY=<fernet key>

# Base URL used when generating invite registration links
PUBLIC_BASE_URL=http://localhost:8000
```

**Local development convenience (disables login entirely — never use in production):**
```
ENVIRONMENT=dev
COOKIE_SECURE=false
# AUTO_LOGIN_USER_ID=<system_admin_uuid>   # fill in after step 6 below
```

See [Configuration reference](#configuration-reference) for all variables.

### 4. Apply database migrations

```bash
uv run alembic upgrade head
```

Creates `./data/claimos.db` and applies all schema migrations. The `./data/uploads/`, `./data/exports/`, and `./data/crops/` directories are created automatically on first run.

### 5. Seed the category table

```bash
uv run seed
```

Populates the 42 depreciation categories from `docs/depreciation-schedule.md`. Idempotent — safe to run multiple times.

### 6. Create the initial System Admin account

There is no default admin account. You must bootstrap one manually on a fresh database. Run this once:

```bash
uv run python - <<'EOF'
from claimos.db import SessionLocal
from claimos.auth import hash_password
from claimos.models_auth import Group, User

EMAIL = "admin@example.com"   # change this
PASSWORD = "replace-me-now"   # change this — min 12 chars

db = SessionLocal()
try:
    # Create the internal group if it doesn't exist
    group = db.query(Group).filter(Group.kind == "internal").first()
    if group is None:
        group = Group(name="Internal", kind="internal")
        db.add(group)
        db.flush()

    if db.query(User).filter(User.email == EMAIL).first():
        print(f"User {EMAIL} already exists — skipping.")
    else:
        user = User(
            email=EMAIL,
            display_name="Admin",
            password_hash=hash_password(PASSWORD),
            system_role="system_admin",
            group_id=group.id,
        )
        db.add(user)
        db.commit()
        print(f"Created system_admin: {user.id}")
        print(f"Add to .env:  AUTO_LOGIN_USER_ID={user.id}")
finally:
    db.close()
EOF
```

Copy the printed UUID into `.env` as `AUTO_LOGIN_USER_ID` to bypass login during local development (the app will load as that user on every request without a login form). Leave the variable unset or empty for production.

> Once logged in as System Admin, all subsequent users are created and invited through the admin panel at `/admin/system/users`. See [docs/RBAC.md](docs/RBAC.md) for the invite flow and role hierarchy.

### 7. Start the development server

```bash
uv run dev
```

Opens the app at **http://127.0.0.1:8000** with auto-reload enabled.

If `AUTO_LOGIN_USER_ID` is set, the app skips login entirely and goes straight to the dashboard. If it is not set, navigate to `/login` and sign in with the credentials you set in step 6.

---

## Production deployment

This app is designed to run on Railway (service + Postgres + volume) behind Cloudflare. See `docs/RUNBOOK.md` for the full first-deploy runbook and `docs/superpowers/specs/2026-04-29-hosting-design.md` for the architecture rationale (including the no-PITR / usage-billing tradeoffs that drove the choice).

Quick summary:

1. Create a Railway project from this repo. `railway.toml` pins the builder to Docker and configures healthcheck + pre-deploy command.
2. Add a Railway Postgres plugin; reference its `DATABASE_URL` from the web service's Variables.
3. Add a 10 GB volume mounted at `/app/data`.
4. Set required env vars (see `.env.example` — `SECRET_KEY`, `ANTHROPIC_API_KEY`, `APP_BASE_URL`, `INITIAL_ADMIN_EMAIL`, `INITIAL_ADMIN_PASSWORD`, `ENVIRONMENT=production`). Do NOT set `DATABASE_URL` or `PORT` — Railway provides them.
5. Configure Cloudflare CNAME (proxied) → `<service>.up.railway.app`, SSL mode Full (strict). Add the custom domain on the Railway side too.
6. Set a Railway usage alert (recommended) to catch unexpected cost changes.
7. Deploy. Log in with bootstrap credentials, complete MFA, **then remove `INITIAL_ADMIN_PASSWORD` from Railway Variables**.

---

## Legacy CVP / coexistence

This codebase was renamed from **CVP** (Contents Valuation Platform) to **ClaimOS**: the Python package moved from `src/cvp/` to `src/claimos/`, and the core domain object was renamed from `matter` to `claim` (table `matters` → `claims`, column `matter_id` → `claim_id`, etc.).

The pre-rename code is preserved on the frozen `cvp-legacy` branch, which continues to serve the existing internal deployment until data is migrated. To cut a legacy deployment over to ClaimOS:

1. Point `LEGACY_DATABASE_URL` at the existing (pre-rename) database and `DATABASE_URL` at the new (empty) ClaimOS database.
2. Create the ClaimOS **schema only** on the target: `uv run alembic upgrade head`. **Do not run `seed` or `bootstrap-admin` yet** — `migrate-db` requires an empty target. It copies `categories` and the `users` table (including admins) from the legacy DB, and it verifies per-table row-count parity; a pre-seeded `categories` table or a pre-bootstrapped admin would either fail that parity check or collide on the unique `users.email`.
3. Run `uv run migrate-db` — a one-shot, read-only-on-the-source copy that maps legacy tables/columns (`matters`/`matter_id`, `matter_access`, etc.) onto the ClaimOS schema (`claims`/`claim_id`, `claim_access`, etc.), FK-safe ordering, with a built-in parity check that fails loudly on mismatch. See `src/claimos/migrate_db.py` for the exact table/column mapping.
4. **After** the copy passes parity, run `uv run seed` (idempotent) and then `uv run bootstrap-admin` (idempotent — it no-ops if a `system_admin` was migrated over, otherwise creates one). Then deploy ClaimOS in place of `cvp-legacy`.

> **Order matters.** `bootstrap-admin`/`seed` run *after* `migrate-db`, never before. This is a one-time legacy-import sequence; a normal greenfield deploy with no legacy data uses the usual `alembic upgrade head` → `seed` → `bootstrap-admin` order.

No new development happens on `cvp-legacy` — it exists only to keep the current deployment running during migration.

---

## Project layout

```
src/claimos/
├── main.py            # FastAPI app entry point, router mounting
├── config.py          # pydantic-settings — reads from .env
├── db.py              # SQLAlchemy engine, WAL mode, session factory
├── auth.py            # Password hashing, JWT creation/validation, invite code helpers
├── dependencies.py    # FastAPI auth dependencies: require_active_user, require_claim_role, etc.
├── models.py          # ORM models: claims, rooms, items, categories, evidence_files, vision_runs
├── models_auth.py     # Auth models: Group, User, RefreshToken
├── models_access.py   # ClaimAccess (per-user, per-claim permission grants)
├── models_comments.py # Comment model (item-level, visibility: internal/shared)
├── models_audit.py    # AuditLog model
├── migrate_db.py      # One-shot legacy-CVP-db -> ClaimOS-db migration (`uv run migrate-db`)
├── seed.py            # 42-category seed data (idempotent)
├── depreciation.py    # Depreciation formula — pure functions, unit-tested
├── routers/
│   ├── auth.py        # Login, logout, register, token refresh, MFA verify
│   ├── profile.py     # Password change, MFA setup/disable
│   ├── sharing.py     # Claim access grant/revoke API
│   ├── comments.py    # Item comment CRUD
│   ├── claims.py      # Claim CRUD
│   ├── evidence.py    # Evidence file upload/delete
│   ├── items.py       # Item CRUD, confirm/exclude toggles
│   ├── rooms.py       # Room CRUD
│   ├── crops.py       # Bounding-box adjustments, recrop
│   ├── vision.py      # Claude Vision scan trigger
│   ├── serp.py        # Google Lens / SERP price lookup
│   ├── exports.py     # PDF and CSV export
│   └── admin/
│       ├── system.py  # System Admin panel (/admin/system/)
│       ├── internal.py # Internal Admin panel (/admin/internal/)
│       └── org.py     # Org Admin panel (/admin/org/)
├── services/          # vision.py, pdf_generator.py, csv_export.py, audit.py, mfa.py
├── templates/         # Jinja2 templates
│   ├── base.html
│   ├── login.html / login_mfa.html / register.html / splash.html
│   ├── profile.html
│   ├── dashboard.html
│   ├── admin/         # Admin panel templates (system/, internal/, org/)
│   └── report/        # Report section templates for preview and PDF
└── static/
    └── app.js

migrations/            # Alembic migration files
tests/                 # pytest test suite
docs/
├── PRD.md                      # Full product requirements
├── data-model.md               # Schema rationale and migration history
├── depreciation-schedule.md    # The 42-category useful-life table (source of truth)
├── AUTH.md                     # Authentication: sessions, MFA, invites, dev bypass
├── RBAC.md                     # Role-based access control: system roles, claim roles, admin panels
└── QA.md                       # Automated QA testing with Playwright
data/                  # gitignored — created at runtime
├── claimos.db         # SQLite database
├── uploads/           # Evidence files (photos, PDFs, etc.)
├── crops/             # Cropped evidence thumbnails
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
| `uv run seed-auth` | Seed initial auth data (groups, roles) |
| `uv run bootstrap-admin` | Idempotent first-deploy System Admin bootstrap (see `docs/RUNBOOK.md`) |
| `uv run migrate-db` | One-shot data copy from a legacy CVP database into the ClaimOS schema (see [Legacy CVP / coexistence](#legacy-cvp--coexistence) below) |
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

> Tests use an in-memory SQLite database. They never touch `./data/claimos.db`.

---

## Data model overview

**Core tables:**

- **claims** — one row per insurance claim; holds all policy metadata, status, and delivery tracking
- **rooms** — named spaces within the insured property (bedroom, kitchen, etc.), linked to a claim
- **items** — the core inventory: one row per line item with RCV, ACV, source citation, and confirmation state
- **categories** — 42 rows from `docs/depreciation-schedule.md`; drives the depreciation formula; read-only in v0
- **evidence_files** — uploaded photos, PDFs, and other files; tracks scan status
- **vision_runs** — one row per Claude Vision API call; stores the raw response for auditing

**Auth and access tables:**

- **groups** — organizations: one `internal` group (the company) plus one `external` group per law firm / client
- **users** — authenticated users with a `system_role`, `group_id`, optional MFA secret, and invite state
- **refresh_tokens** — server-side refresh token records (hashed); supports revocation
- **claim_access** — per-user, per-claim permission grants (`viewer` / `editor` / `contributor` / `manager`)
- **comments** — item-level comments with `visibility` (`internal` or `shared`)
- **audit_logs** — append-only event log for auth and data mutations

All currency is stored as **integer cents**. Conversion to dollars happens only at the display and export layer.

Full schema rationale in `docs/data-model.md`. For access control design see `docs/RBAC.md`.

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

All settings are read from `.env` at startup via pydantic-settings. Every variable has a default so the app starts without a complete `.env`, but authentication will not work until the auth variables are set.

**Application:**

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | `""` | Required for Claude Vision photo scanning |
| `VISION_MODEL` | `claude-opus-4-6` | Model used for Vision scans |
| `VISION_MODEL_FALLBACK` | `claude-sonnet-4-6` | Fallback model |
| `PORT` | `8000` | Port the dev server listens on |
| `DATABASE_URL` | `sqlite:///./data/claimos.db` | ClaimOS database connection string (SQLite locally; Postgres in production) |
| `LEGACY_DATABASE_URL` | *(unset)* | Only used by `uv run migrate-db` — connection string for the source (legacy CVP) database to copy from. See [Legacy CVP / coexistence](#legacy-cvp--coexistence). |
| `UPLOAD_DIR` | `./data/uploads` | Where evidence files are stored |
| `EXPORT_DIR` | `./data/exports` | Where PDFs and CSVs are written |
| `COMPANY_NAME` | `Contents Valuation LLC` | Appears in report headers and footers |
| `COMPANY_ADDRESS` | `""` | Appears in report cover page |
| `COMPANY_EMAIL` | `""` | Appears in report cover page |
| `COMPANY_PHONE` | `""` | Appears in report cover page |
| `PUBLIC_BASE_URL` | `""` | Base URL prepended to invite registration links (e.g., `http://localhost:8000`) |

**Authentication:**

| Variable | Default | Description |
|---|---|---|
| `ENVIRONMENT` | `production` | Set to `dev` to enable dev-mode bypasses |
| `JWT_SECRET` | `""` | Secret key for signing JWTs. Generate with `python3 -c "import secrets; print(secrets.token_hex(32))"`. **Required for login to work.** |
| `JWT_ACCESS_TTL_MINUTES` | `60` | Access token lifetime in minutes |
| `JWT_REFRESH_TTL_DAYS` | `7` | Refresh token lifetime in days |
| `MFA_ENCRYPTION_KEY` | `""` | Fernet key for encrypting TOTP secrets at rest. Required before MFA can be enabled. |
| `COOKIE_SECURE` | `true` | Set to `false` for local HTTP development |
| `AUTO_LOGIN_USER_ID` | `""` | **Dev only.** UUID of a user to load on every request without JWT validation. Only active when `ENVIRONMENT=dev`. |

---

## Local QA testing

Automated browser-based QA tests verify auth, RBAC, evidence uploads, item management, comments, and exports against the running dev server.

See **[docs/QA.md](docs/QA.md)** for full setup and usage.

Quick start:
```bash
# Install browser
uv run playwright install chromium

# Add to .env
# QA_ADMIN_EMAIL=admin@example.com
# QA_ADMIN_PASSWORD=your-admin-password

# Run all suites
uv run python skills/qa/runner.py

# Run a specific suite
uv run python skills/qa/runner.py --suite auth
```

---

## Important constraints

- **No cloud services** beyond the Anthropic API. Everything runs on localhost.
- **Currency is always integer cents.** Never use Python `float` for currency math.
- **Vision scans are sequential** with a 500ms pause between images. Do not parallelize.
- **Do not commit** `.env`, `./data/`, or `./backups/` — all are gitignored.
- Reports are **attorney work product** and include a "Confidential — Attorney Work Product" marker.
- **`AUTO_LOGIN_USER_ID` is for local development only.** It bypasses all authentication. Never set it in production (`ENVIRONMENT=production` will not activate the bypass regardless, but do not set it).
- **`JWT_SECRET` and `MFA_ENCRYPTION_KEY` must be kept secret.** Rotating `JWT_SECRET` invalidates all active sessions. Rotating `MFA_ENCRYPTION_KEY` breaks all stored MFA secrets — users will need MFA reset.
- **No self-registration.** All users are created by an admin via an admin panel and receive an invite link. See [docs/AUTH.md](docs/AUTH.md).

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
