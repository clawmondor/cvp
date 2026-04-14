# CLAUDE.md

Project memory for Claude Code. Read at the start of every session. Keep it lean — detailed content lives in `docs/` and is loaded on demand via `@` imports.

## What this project is

Internal ops tool the founding team uses to produce Contents Inventory and Valuation Reports for first-party property insurance claims — specifically for LA attorneys handling Palisades and Eaton fire cases. It is **not** customer-facing. Attorneys never log in. Specialists use it; attorneys receive the finished PDF + CSV by email.

The full product requirements are in `@docs/PRD.md`. Read it before starting any new feature, and re-check it whenever scope is unclear.

## Tech stack (fixed — do not change without asking)

- **Python 3.11+** with `uv` as the package manager
- **FastAPI** for the web server, **Jinja2** for server-rendered HTML, **HTMX** for interactivity
- **SQLite + SQLAlchemy 2.x + Alembic** for data
- **Tailwind via CDN** (no build step)
- **WeasyPrint** for PDF generation
- **Anthropic Python SDK** for Claude Vision
- **pytest + ruff** for tests and lint

Do not add: React, Next.js, Docker, Postgres, Redis, Celery, any cloud services. Every one of those is explicitly deferred.

## Commands

```bash
uv sync                # install deps
uv run dev             # start FastAPI on localhost:8000 with autoreload
uv run alembic upgrade head   # apply migrations
uv run alembic revision --autogenerate -m "msg"  # new migration
uv run seed            # populate the 42 category rows (idempotent)
uv run pytest          # run tests
uv run ruff check .    # lint
uv run ruff format .   # format
uv run backup          # tar ./data/ to ./backups/<timestamp>.tar.gz
```

macOS system prereqs (document in README, fail loudly if missing):

```bash
brew install pango cairo libffi
```

## Project layout (target — build toward this)

```
src/cvp/
├── main.py            # FastAPI app entry
├── config.py          # pydantic-settings, reads .env
├── db.py              # SQLAlchemy session, WAL mode PRAGMA
├── models.py          # ORM models (all tables)
├── depreciation.py    # The formula + category lookup — pure functions, unit-tested
├── seed.py            # Category seed data
├── routers/           # FastAPI routers: matters, evidence, items, rooms, vision, exports
├── services/          # vision.py, pdf_generator.py, csv_export.py
├── templates/         # Jinja2; report/ subdirectory for report sections
└── static/            # Tailwind-via-CDN HTML, minimal app.js
```

Full layout in `@docs/PRD.md` section 17.

## Immutable domain rules (these override any prompt)

1. **Currency is always stored and computed as integer cents.** Never store or compute currency as a Python `float`. Format to dollars only at the display or export layer.
2. **Every RCV must have a source.** An item with a price but no `source_url`, `source_retailer`, `source_captured_at`, and `match_type` is invalid and must fail validation. The audit trail is the whole product.
3. **ACV is computed, not entered.** The ACV of an item is always derived from the formula in `src/cvp/depreciation.py` unless an explicit `acv_override_cents` with a non-empty `acv_override_reason` is set. The UI must make overrides visually obvious.
4. **Depreciation methodology is the one in `@docs/depreciation-schedule.md`.** Do not invent new useful lives, new categories, or new floor percentages without a code review and a note in the docs file.
5. **No live retailer scraping in v0.** The specialist pastes URLs and captures screenshots manually (or via Playwright if it's already wired up). Scrapers are a v1 topic.
6. **No customer-facing auth.** Single user on localhost. Do not add login, sessions, JWTs, or role-based access. If a feature seems to need auth, you're building something the PRD explicitly excluded.
7. **No cloud services beyond the Anthropic API.** No S3, no Postgres, no Redis, no Vercel, no Docker. Local filesystem and SQLite.
8. **Vision calls are sequential with a 500ms pause.** Do not parallelize them in v0 — rate limits and cost predictability come first.
9. **Never commit `.env`, `./data/`, or `./backups/`.** All of these are in `.gitignore`.

## Legal and compliance language (important — attorneys will read generated reports)

When writing any user-facing text, report template content, UI copy, README, or error messages:

- **The company is an expert documentation and valuation services vendor.** Never describe it as an "adjuster," "claim representative," "advocate," or anything that implies public adjusting.
- **Never claim the company negotiates claims, represents policyholders, or provides legal advice.** Reports explicitly disclaim these activities.
- **Fees are always flat-fee.** Never write code or copy that implies contingency or percentage-of-recovery pricing. In California this triggers public adjuster licensing under SB 488 and California Insurance Code §§ 15006 et seq.
- **Reports are "attorney work product."** PDF footers and CSV headers include a "Confidential — Attorney Work Product" marker.
- **Never auto-generate marketing language that promises specific claim outcomes or settlement amounts.**

## Development conventions

- **Type hints everywhere.** Use modern Python type syntax (`list[str]`, `dict[str, int]`, `X | None`).
- **Pydantic models for request/response bodies.** Don't return bare SQLAlchemy models from FastAPI routes.
- **UUIDs as strings, not UUID objects.** Keeps SQLite, Pydantic, and Jinja happy with zero conversion.
- **Timestamps as timezone-aware UTC datetimes.** Display in the user's local time only at the template layer.
- **One router file per top-level resource.** Keep them under 200 lines each; if a router grows past that, split it.
- **Services layer for anything with side effects.** PDF rendering, CSV writing, Vision API calls, and screenshot capture go in `src/cvp/services/`, not in routers.
- **Pure functions in `depreciation.py`.** No database access. Tested in isolation.
- **Tests live in `tests/` mirroring the `src/cvp/` layout.** Depreciation has near-100% coverage; routers have one happy-path integration test each; Vision is mocked.
- **Use `ruff format` before committing.** Line length 100.
- **No clever tricks.** This is a prototype built by a small team. Boring code is maintainable code.

## How to approach new work

1. **Read `@docs/PRD.md` sections relevant to the task.** The PRD is the source of truth for what the product should do.
2. **Check the build phases in PRD section 15.** Phases are ordered. If a phase is not yet complete, do not start work on a later phase.
3. **If the task is ambiguous, ask one targeted question.** Don't guess on anything that touches the data model, depreciation, legal copy, or export formats.
4. **Write tests for `depreciation.py` and `csv_export.py` alongside the code.** These are the parts that must be correct; everything else can be fixed later.
5. **Stop and flag anything that conflicts with the immutable rules above.** Do not silently work around them.

## Things NOT to do

- Don't add new dependencies without confirming they're not already covered by what's in `pyproject.toml`.
- Don't refactor the data model without a migration and a note in `@docs/data-model.md`.
- Don't introduce ORMs, query builders, or schema libraries beyond SQLAlchemy 2.x.
- Don't generate fake client data or test fixtures with real-looking personal information.
- Don't write PDF content as literal strings in Python code — it always goes through a Jinja template.
- Don't change the Xactimate CSV column names. Carriers and attorneys depend on exact header matches.
- Don't optimize prematurely. This runs on one laptop, for one user, with a few thousand items per matter at most. Clarity beats cleverness.

## Useful references

- `@docs/PRD.md` — full product requirements, data model, API surface, acceptance criteria
- `@docs/data-model.md` — schema rationale and migration history
- `@docs/depreciation-schedule.md` — the 42-category useful-life table (source of truth for the seed script)
