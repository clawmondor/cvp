# Product Requirements Document — Contents Valuation Prototype (v0)

**Status:** Draft for Claude Code implementation
**Owner:** Founding team
**Target environment:** Local machine (macOS), single user, no deployment

---

## 1. Purpose

Build a local-first web application that the founding team uses to produce **Contents Inventory and Valuation Reports** for first-party property insurance claims. The prototype is the internal tool that powers the done-for-you service sold to Los Angeles first-party property attorneys representing Palisades and Eaton fire victims.

The prototype is **not a customer-facing SaaS**. Customers (attorneys) never log into it. The founders use it to produce reports faster, more consistently, and with a defensible audit trail, then deliver the final PDF and CSV to the attorney via email.

Think "internal ops tool," not "product."

## 2. Problem

Producing a line-itemized Contents Inventory today is a 40–60 hour manual process in Google Sheets. For every item a specialist must: identify the item from photos/video/client recall, categorize it, find current retail pricing, screenshot and cite the source, compute depreciation, and format it into a carrier-ready report. The process is error-prone, non-reproducible, and impossible to audit after the fact.

## 3. Goals and non-goals

### Goals (v0 prototype)

1. Reduce average time to produce a total-loss report from 40–60 hours to **under 20 hours** of specialist time.
2. Produce reports with a **complete, reproducible audit trail** — every price traces to a retailer URL, a capture date, and a stored screenshot.
3. Enforce a **single depreciation methodology** across every report (no specialist-to-specialist variance).
4. Export in two formats: a polished **PDF** matching the report template, and a **Xactimate-compatible CSV**.
5. Run **entirely on a local machine** with zero cloud dependencies except the Anthropic API.
6. Be buildable by a solo engineer with a DevOps/cloud background in **3–4 focused weeks**.

### Non-goals (explicitly out of scope for v0)

- Multi-user authentication, role-based access, or team collaboration features.
- Cloud deployment (AWS, Fly, Vercel, etc.). Prototype runs on `localhost`.
- Customer-facing UI for attorneys or policyholders.
- Live retailer scraping beyond a thin manual-assist wrapper. (v1 may add this.)
- Training custom ML models. All AI usage is via the Anthropic API.
- Billing, invoicing, or subscription management.
- Mobile app or mobile-optimized UI (desktop-only for v0).
- Direct carrier submission, API integrations with Xactimate/Symbility, or e-signature.
- Automated price updates after the initial capture.
- USPAP-compliant appraisal features.

## 4. Users and usage context

One user: the founder acting as "claim specialist." Sits at a desk with a laptop, a second monitor, and a cup of coffee. Has just received a folder of photos, a video walkthrough, and a partial inventory spreadsheet from an attorney via Google Drive. Has 10–14 days to produce a finished report.

Expected weekly usage in the first 6 months: 5–15 reports in progress, 1–3 specialists over time.

## 5. User flow (the happy path)

1. **Create matter.** Specialist creates a new "matter" (one claim = one matter) and enters basic metadata: firm name, attorney, policyholder, loss location, loss date, loss type, carrier, policy number, claim number, Coverage C limit, target delivery date.
2. **Upload evidence.** Specialist drags photos, videos, PDFs, and spreadsheets into the matter's intake area. Files are stored locally and listed in the matter view.
3. **Scan evidence with AI.** Specialist clicks "Scan photos with Vision" on an uploaded image batch. The app sends each image to Claude Vision via the Anthropic API and receives structured item suggestions back (item name, category guess, quantity, condition, room). Suggestions appear as unconfirmed draft line items.
4. **Review and confirm line items.** Specialist walks through the draft line items in a table view, correcting descriptions, assigning rooms, adjusting quantities, entering ages, and confirming or rejecting each item. Confirmed items become part of the inventory.
5. **Price each item.** For each confirmed item, the specialist looks up current retail pricing manually (a helper panel opens search links to the top retailers) and enters: unit RCV, retailer, source URL, match type (exact/comparable/category avg), and date of capture. The app auto-captures a screenshot of the URL via a headless browser if possible, otherwise the specialist pastes in a screenshot file.
6. **Depreciation auto-computes.** Once an item has an RCV and an age, ACV computes automatically using the item's category useful-life table and condition multiplier. The specialist can override the computed ACV with a reason note.
7. **Review report preview.** Specialist opens the "Report preview" view, which renders the full Contents Inventory and Valuation Report using the v0 template. The specialist reviews room summaries, the executive summary, and spot-checks the itemized section.
8. **Export.** Specialist clicks "Export PDF" and "Export Xactimate CSV." Both files are generated to `./data/exports/<matter>/` and the paths are shown.
9. **Archive.** After the report is delivered to the attorney, the specialist marks the matter "Delivered" and adds internal notes on turnaround time and invoiced amount for later analytics.

## 6. Tech stack

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.11+ | Best ecosystem for data, PDFs, AI API clients |
| Web framework | FastAPI | Minimal boilerplate, typed, async, easy to learn from DevOps background |
| Template engine | Jinja2 | Server-rendered HTML; no React build step |
| Frontend interactivity | HTMX + vanilla JS | Keeps the stack lean; no SPA, no build pipeline |
| CSS | Tailwind via CDN (not a build step) | Fast styling without a toolchain |
| Database | SQLite via SQLAlchemy 2.x | Zero-config, file-based, sufficient for single-user prototype |
| Migrations | Alembic | Future-proof schema changes |
| File storage | Local filesystem under `./data/uploads/<matter_id>/` | No S3 |
| AI API | Anthropic Python SDK (`anthropic>=0.40`) | Claude Vision for photo → item extraction |
| PDF rendering | WeasyPrint | Renders HTML/CSS to PDF; uses the same Jinja templates as the preview |
| CSV export | Python csv module + pandas | Xactimate ESX format is CSV-compatible |
| Headless browser (optional) | Playwright | For auto-screenshot of source URLs; skip if it adds too much setup friction |
| Dev tooling | uv (package manager), ruff (lint), pytest | Modern Python tooling |
| Config | pydantic-settings + `.env` file | API keys, paths, toggles |

**Do not add** React, Next.js, Docker, Redis, Celery, Postgres, or any cloud services in v0. Every one of those is deferred to a later phase.

## 7. Data model

SQLite schema. Represent with SQLAlchemy 2.x declarative models. All tables include `id` (UUID string), `created_at`, and `updated_at`.

### `matters`

| Column | Type | Notes |
|---|---|---|
| id | str (UUID) | Primary key |
| firm_name | str | |
| attorney_name | str | |
| attorney_email | str | |
| policyholder_name | str | |
| loss_location | str | Full street address |
| loss_type | enum | `total_loss` / `partial_loss` / `smoke` / `water` / `theft` / `other` |
| loss_event | str | "Palisades Fire", "Eaton Fire", or custom |
| loss_date | date | |
| carrier | str | |
| policy_number | str | |
| claim_number | str | |
| coverage_c_limit | int (cents) | Store currency as integer cents throughout |
| firm_file_number | str | |
| status | enum | `draft` / `in_review` / `delivered` / `archived` |
| target_delivery_date | date | |
| delivered_date | date, nullable | |
| invoice_amount_cents | int, nullable | |
| internal_notes | text | |

### `rooms`

| Column | Type | Notes |
|---|---|---|
| id | str (UUID) | |
| matter_id | FK → matters.id | |
| name | str | "Primary bedroom", "Kitchen", etc. |
| sort_order | int | |

### `items`

| Column | Type | Notes |
|---|---|---|
| id | str (UUID) | |
| matter_id | FK → matters.id | |
| room_id | FK → rooms.id, nullable | |
| line_number | int | Per-matter sequential |
| description | str | Human-readable |
| brand | str, nullable | |
| model | str, nullable | |
| category_id | FK → categories.id | Drives depreciation |
| quantity | int | |
| age_years | float | |
| condition | enum | `excellent` / `above_average` / `average` / `below_average` |
| rcv_unit_cents | int | Replacement cost per unit |
| rcv_total_cents | int | computed: quantity × rcv_unit_cents |
| acv_total_cents | int | computed via depreciation formula |
| acv_override_cents | int, nullable | Manual override |
| acv_override_reason | str, nullable | |
| match_type | enum | `exact` / `nearest_comparable` / `category_average` |
| source_retailer | str | |
| source_url | str | |
| source_captured_at | datetime | |
| source_screenshot_path | str, nullable | Relative path under `./data/uploads/` |
| confirmed | bool | false = draft from Vision, true = specialist-confirmed |
| excluded | bool | Items the specialist chose not to include in the final report |
| notes | text | |

### `categories` (seed data, not user-editable in v0)

42 rows matching the depreciation schedule in `docs/depreciation-schedule.md`. Each row has:

| Column | Type |
|---|---|
| id | int (1-42) |
| name | str |
| useful_life_years | int, nullable |
| acv_floor_pct | float (0.20 = 20%) |
| notes | str |

`useful_life_years = NULL` means the category is not depreciated (artwork, jewelry). These items are presented at RCV only.

### `evidence_files`

| Column | Type | Notes |
|---|---|---|
| id | str (UUID) | |
| matter_id | FK → matters.id | |
| filename | str | Original |
| stored_path | str | Relative to `./data/uploads/` |
| mime_type | str | |
| size_bytes | int | |
| kind | enum | `photo` / `video` / `receipt` / `statement` / `policy_doc` / `other` |
| scanned | bool | Whether Vision has processed this file |

### `vision_runs`

| Column | Type | Notes |
|---|---|---|
| id | str (UUID) | |
| matter_id | FK | |
| evidence_file_id | FK → evidence_files.id | |
| model | str | e.g., `claude-opus-4-6` |
| prompt_version | str | For tracking prompt iterations |
| raw_response | text | Full JSON response for debugging |
| items_created | int | Count of draft items generated |
| ran_at | datetime | |

## 8. Depreciation formula

For an item in a depreciable category:

```
straight_line_dep_rate = 1 / useful_life_years
accumulated_dep = min(straight_line_dep_rate * age_years * condition_multiplier, 1 - acv_floor_pct)
acv_unit_cents = round(rcv_unit_cents * (1 - accumulated_dep))
acv_total_cents = acv_unit_cents * quantity
```

**Condition multipliers:**

| Condition | Multiplier |
|---|---|
| Excellent | 0.75 |
| Above average | 0.90 |
| Average | 1.00 |
| Below average | 1.15 |

**Floor:** `acv_total_cents` is never less than `rcv_total_cents * acv_floor_pct` for the item's category. For items with `useful_life_years IS NULL`, `acv_total_cents = rcv_total_cents` (no depreciation).

**Override:** if `acv_override_cents` is set, it takes precedence over the computed value. The UI must display a visible indicator when an override is in effect, and `acv_override_reason` must be non-empty.

## 9. API surface

All routes are prefixed with `/api` except HTML page routes. JSON request and response bodies use `snake_case`.

### Matter management

- `GET /` — Dashboard HTML (list of matters)
- `GET /matters/new` — New matter form
- `POST /matters` — Create matter
- `GET /matters/{matter_id}` — Matter detail page
- `PATCH /api/matters/{matter_id}` — Update matter fields
- `POST /api/matters/{matter_id}/status` — Update status

### Evidence files

- `POST /api/matters/{matter_id}/evidence` — Multipart upload, supports multiple files at once
- `GET /api/matters/{matter_id}/evidence` — List evidence files
- `DELETE /api/evidence/{file_id}` — Delete a file (and its record)
- `GET /files/{stored_path:path}` — Serve a stored file (photo preview, etc.)

### Vision scan

- `POST /api/matters/{matter_id}/vision-scan` — Body: `{ "evidence_file_ids": [...] }`. Runs Claude Vision on each listed image, creates draft items, returns a summary

### Items

- `GET /api/matters/{matter_id}/items` — List items for a matter, optionally filtered by room, confirmed, excluded
- `POST /api/matters/{matter_id}/items` — Create item (manual, not from Vision)
- `PATCH /api/items/{item_id}` — Update item fields (including confirm/exclude/override)
- `DELETE /api/items/{item_id}` — Hard delete
- `POST /api/items/{item_id}/recompute-acv` — Force ACV recomputation

### Rooms

- `GET /api/matters/{matter_id}/rooms` — List rooms
- `POST /api/matters/{matter_id}/rooms` — Create room
- `PATCH /api/rooms/{room_id}` — Rename or reorder
- `DELETE /api/rooms/{room_id}` — Delete (items in the room become unassigned)

### Reports and export

- `GET /matters/{matter_id}/preview` — HTML preview of the full report (rendered with Jinja using the same template WeasyPrint consumes)
- `POST /api/matters/{matter_id}/exports/pdf` — Generate PDF to `./data/exports/<matter_id>/report.pdf`, return the path
- `POST /api/matters/{matter_id}/exports/csv` — Generate Xactimate-compatible CSV to same folder, return the path

### Categories

- `GET /api/categories` — List all 42 categories (read-only in v0)

## 10. UI pages

The UI is minimal, functional, and keyboard-friendly. No custom design system; Tailwind utility classes and sensible defaults.

### Dashboard (`/`)

- Table of all matters sorted by status then target delivery date
- Columns: firm, policyholder, loss event, status, items count, target delivery date, days remaining
- "New matter" button in the header
- Color-coded status chips

### New matter form (`/matters/new`)

- Single-column form with all the fields from the `matters` table
- Defaults: loss event dropdown pre-populated with "Palisades Fire", "Eaton Fire", and "Other"
- On submit, redirects to the matter detail page

### Matter detail (`/matters/{matter_id}`)

Tabbed interface with these tabs, navigable via the URL hash (`#evidence`, `#items`, etc.):

1. **Overview** — matter metadata, editable in place. Key metrics: total items, total RCV, total ACV, blended depreciation, count of unconfirmed drafts, count of items missing pricing.
2. **Evidence** — drag-and-drop upload zone, grid of uploaded files with thumbnails for images, "Scan selected with Vision" action button
3. **Items** — the main working view. A large table of all items for the matter with inline editing. Filters: room, category, confirmed/unconfirmed, has price/missing price, excluded. Bulk actions: assign room, assign category, confirm, exclude. Keyboard shortcuts for fast data entry.
4. **Rooms** — room list with add/rename/reorder
5. **Preview** — button that opens `/matters/{matter_id}/preview` in a new tab
6. **Export** — two buttons (PDF, CSV) that trigger exports and show the resulting file paths, plus a "reveal in Finder" link

### Report preview (`/matters/{matter_id}/preview`)

Renders a full-fidelity HTML version of the Contents Inventory and Valuation Report matching the structure of `04_Report_Template_v0.docx`:

1. Cover page
2. Table of contents
3. Executive summary (with computed headline figures)
4. Scope of engagement
5. Methodology
6. Data sources and inputs
7. Depreciation methodology (table of categories used in this matter)
8. Summary of findings (by room)
9. Itemized inventory (every confirmed, non-excluded item)
10. Pricing audit trail (every row with its source)
11. Certifications and limitations
12. Preparer's signature

## 11. AI vision integration

- **Endpoint:** Anthropic Messages API, `POST /v1/messages`
- **Model:** `claude-opus-4-6` for quality, `claude-sonnet-4-6` for cost-sensitive iteration. Configurable via `.env`.
- **Input:** each image is base64-encoded and sent as an `image` content block alongside a text prompt
- **Prompt:** stored in `src/cvp/services/vision_prompts.py` as versioned string constants. The prompt instructs Claude to return a JSON array of items, each with: `description`, `category_hint`, `quantity`, `brand` (if visible), `model` (if visible), `condition` (if inferable), `room_hint` (if inferable), `confidence` (low/medium/high). The prompt must explicitly say "return ONLY a JSON array, no preamble, no markdown fences."
- **Parsing:** extract the JSON array from the response, tolerant of accidental markdown fences. Log and skip malformed entries without failing the whole run.
- **Draft item creation:** each returned item becomes a row in `items` with `confirmed=false` and enough metadata to be reviewed. The raw response is stored in `vision_runs.raw_response` for debugging.
- **Rate limits:** sequential calls with a 500ms pause between images. Do not parallelize in v0.
- **Cost control:** surface a running token/cost estimate on the Evidence tab so the specialist knows what they're spending.

## 12. PDF generation

- Rendered from the same Jinja2 template that produces the HTML preview
- WeasyPrint CSS controls page size (US Letter), margins (1 inch), headers/footers (company name, "Confidential — Attorney Work Product," page numbers)
- Tables in the itemized inventory section must not break individual rows across pages
- Fonts: Arial (or Liberation Sans as a Linux-friendly fallback)
- Output path: `./data/exports/<matter_id>/contents_report_<YYYYMMDD>.pdf`

## 13. Xactimate CSV export

Xactimate imports a CSV where each row is one line item with these columns (exact header names matter for import compatibility):

```
LineItem, Description, Qty, Unit, UnitPrice, Total, Depreciation, ACV, Category, Room, Age, Condition, Notes
```

- `LineItem` = sequential per-matter
- `UnitPrice` = RCV unit in dollars (not cents), 2 decimal places
- `Total` = RCV total in dollars
- `Depreciation` = dollar amount of accumulated depreciation (RCV - ACV)
- `ACV` = ACV total in dollars
- `Category` = name of the category in the local schema, not Xactimate's internal codes (v0 limitation)
- `Room` = room name
- `Age` = integer years, rounded
- `Condition` = enum value from items table
- `Notes` = includes the source retailer + URL + match type concatenated

Output path: `./data/exports/<matter_id>/contents_xactimate_<YYYYMMDD>.csv`

## 14. Configuration

`.env` file at the project root, not committed. `.env.example` is committed. Required variables:

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

## 15. Build phases and acceptance criteria

Build in these phases in strict order. Do not start phase N+1 until phase N passes its acceptance criteria.

### Phase 1 — Skeleton and data model

- FastAPI app boots on `localhost:8000` with a dashboard page showing "No matters yet"
- SQLite database created with migrations for all tables in section 7
- Seed script populates the 42 categories from `docs/depreciation-schedule.md`
- `uv run pytest` passes with a single test that confirms category seed
- **Acceptance:** run `uv run dev` and see the dashboard in a browser

### Phase 2 — Matter CRUD

- Create, view, update a matter through the UI
- Matter detail page shows all metadata and has the 6 tabs (even if most are empty)
- **Acceptance:** manually create a matter, reload the dashboard, see it listed; click through, see every field

### Phase 3 — Evidence upload

- Drag-and-drop upload works on the Evidence tab
- Files are stored on disk and listed with thumbnails for images
- Can delete a file
- **Acceptance:** upload 10 photos to a test matter, see them in the grid, delete one, confirm it's gone from disk and DB

### Phase 4 — Manual items and depreciation

- Can create, edit, and delete items manually from the Items tab
- Can create and assign rooms
- ACV auto-computes from RCV + age + category + condition using the formula in section 8
- Override with reason works
- **Acceptance:** manually create 50 items across 3 rooms, confirm totals match hand-calculated values; run the unit test suite for depreciation edge cases

### Phase 5 — Vision scan

- "Scan with Vision" button on the Evidence tab
- Calls Anthropic API, parses response, creates draft items with `confirmed=false`
- Draft items appear in the Items tab and can be edited and confirmed
- **Acceptance:** upload 5 photos of real household items, run the scan, confirm at least 60% of returned items are recognizable and correct-enough to edit rather than discard

### Phase 6 — Report preview

- `/matters/{id}/preview` renders the full report as HTML
- Every section from the v0 report template is present
- Summary of findings by room has correct totals
- Itemized inventory lists every confirmed non-excluded item
- Audit trail section lists every source
- **Acceptance:** open the preview for a test matter with 200 items and visually confirm every section renders correctly

### Phase 7 — PDF and CSV export

- "Export PDF" button produces a file matching the preview, paginated cleanly
- "Export CSV" button produces a file with the exact Xactimate column headers in section 13
- Files land in `./data/exports/<matter_id>/` and the paths are shown in the UI
- **Acceptance:** export both formats for the 200-item test matter, open the PDF in Preview.app, open the CSV in Excel, confirm both are readable

### Phase 8 — Polish

- Dashboard status chips
- Progress indicator during Vision scans
- Error states for API failures
- Simple backup script: `uv run backup` tars `./data/` to `./backups/<timestamp>.tar.gz`
- **Acceptance:** founder uses the tool end-to-end to produce a real test report in under 20 hours

## 16. Testing strategy

- Unit tests for the depreciation formula covering: normal case, zero age, age > useful life, floor enforcement, condition multipliers, override precedence, null useful life
- Unit tests for the CSV exporter: verify headers, currency formatting, row count matches confirmed non-excluded items
- A single end-to-end test that creates a matter, adds 10 items via the API, generates both exports, and asserts the files exist and are non-empty
- **No** tests for: UI rendering, Vision API responses (mock it), PDF pixel fidelity
- Run tests with `uv run pytest`

## 17. Directory layout (target)

```
contents-valuation-prototype/
├── CLAUDE.md
├── README.md
├── pyproject.toml
├── .env.example
├── .gitignore
├── alembic.ini
├── docs/
│   ├── PRD.md
│   ├── data-model.md
│   └── depreciation-schedule.md
├── src/
│   └── cvp/
│       ├── __init__.py
│       ├── main.py
│       ├── config.py
│       ├── db.py
│       ├── models.py
│       ├── depreciation.py
│       ├── seed.py
│       ├── routers/
│       │   ├── __init__.py
│       │   ├── matters.py
│       │   ├── evidence.py
│       │   ├── items.py
│       │   ├── rooms.py
│       │   ├── vision.py
│       │   └── exports.py
│       ├── services/
│       │   ├── __init__.py
│       │   ├── vision.py
│       │   ├── vision_prompts.py
│       │   ├── pdf_generator.py
│       │   └── csv_export.py
│       ├── templates/
│       │   ├── base.html
│       │   ├── dashboard.html
│       │   ├── matter_new.html
│       │   ├── matter_detail.html
│       │   ├── _tab_overview.html
│       │   ├── _tab_evidence.html
│       │   ├── _tab_items.html
│       │   ├── _tab_rooms.html
│       │   ├── _tab_export.html
│       │   └── report/
│       │       ├── preview.html
│       │       ├── cover.html
│       │       ├── executive_summary.html
│       │       ├── methodology.html
│       │       ├── findings_by_room.html
│       │       ├── itemized_inventory.html
│       │       ├── audit_trail.html
│       │       └── certifications.html
│       └── static/
│           ├── app.css
│           └── app.js
├── migrations/
│   └── versions/
├── tests/
│   ├── test_depreciation.py
│   ├── test_csv_export.py
│   └── test_e2e.py
└── data/              # gitignored
    ├── cvp.db
    ├── uploads/
    └── exports/
```

## 18. Risks and mitigations (for Claude Code to be aware of)

1. **WeasyPrint system dependencies.** WeasyPrint needs Pango and Cairo installed via Homebrew on macOS. The README must document `brew install pango cairo` and the installer should fail loudly with a clear error if these are missing.
2. **Vision API cost surprise.** Each photo scan costs real money. The UI must show a running cost estimate before the scan runs and require confirmation for batches over 20 images.
3. **SQLite concurrent writes.** Single-user, so not an immediate issue, but FastAPI's async handlers can race on SQLite. Use WAL mode (`PRAGMA journal_mode=WAL`) and serialize writes through a dependency-injected session.
4. **Long-running Vision scans blocking the server.** Run scans as background tasks (FastAPI `BackgroundTasks`) and poll status from the client. Don't block the request thread.
5. **Currency as float.** Never store or compute currency as Python floats. Integer cents throughout, format to dollars only at the display/export layer.

## 19. What "done" looks like for v0

- Founder can onboard a new wildfire case in under 15 minutes (matter creation + evidence upload)
- Producing a 1,000-item total-loss report takes under 20 hours of specialist time
- Every line item in the PDF traces to a retailer URL and a capture date
- CSV imports cleanly into Xactimate (verified on one real attorney's workflow)
- No cloud services are required beyond the Anthropic API
- `git clone` + `uv sync` + `uv run dev` starts the app on a fresh laptop in under 5 minutes (assuming Homebrew prereqs)
