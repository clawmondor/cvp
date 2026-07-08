# ClaimOS Rename & Rebrand Foundation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the `cvp` package → `claimos` and the `matter` domain → `claim` across code, schema, routes, templates, and tests; collapse Alembic to a clean ClaimOS baseline; add a one-shot CVP→ClaimOS data-migration script; update product-name/docs — leaving CVP production untouched and deployable from a frozen `cvp-legacy` branch.

**Architecture:** One repo, renamed in place. `main` becomes the ClaimOS mainline; `cvp-legacy` (cut before merge) keeps the live internal CVP deployable. ClaimOS runs on a brand-new Postgres created from a squashed baseline migration; a `migrate-db` script copies all data from the legacy CVP DB into it at cutover. The visual rebrand is a **separate follow-on slice** — this plan does the structural/vocabulary rename only.

**Tech Stack:** Python 3.11+, uv, FastAPI, Jinja2, HTMX, SQLAlchemy 2.x, Alembic, Postgres (prod) / SQLite (local/tests), pytest, ruff.

## Global Constraints

_Every task's requirements implicitly include this section._

- **This is a naming change, not a semantics change.** No behavior, workflow, or UI-layout changes. Depreciation logic, the 42 seed categories, and ACV/RCV/cents rules are untouched.
- **Currency stays integer cents.** Never introduce float currency.
- **Do NOT change Xactimate CSV column headers.** Carriers/attorneys match exact headers. Verify export headers are byte-identical before/after.
- **Do NOT change PDF report content** except the product name where it literally appears. Keep the "Confidential — Attorney Work Product" marker.
- **Do NOT rewrite legal/compliance copy substance** (flat-fee, not-a-public-adjuster, no-legal-advice, attorney-work-product). Leave `company_name` ("Contents Valuation LLC" — the legal vendor entity) unchanged; it is not the product name.
- **No visual rebrand here** — no theme, layout, or brand-chrome changes. Deferred to the mockup-driven styling slice.
- **No new dependencies.** No stack additions.
- **CSP rules hold:** never introduce inline JS or inline event handlers (`onclick=` etc.); interactivity stays `data-*` + delegated listeners in `app.js`.
- **Formatting gate (CI-enforced, has failed before):** every commit must pass `uv run ruff check .` and show zero files from `uv run ruff format --check .`. Run `uv run ruff format .` before staging.
- **The live CVP production DB is never renamed or migrated in place.** `keep the legacy DB read-only` from the migration script.
- Tests build schema via `Base.metadata.create_all()` in `tests/conftest.py` (not Alembic), so the suite is the regression net for the renames.

---

## File-structure map

- `src/cvp/` → `src/claimos/` (whole package moves; internal file layout unchanged).
- `src/claimos/models*.py` — `Matter`→`Claim`, `matter_id`→`claim_id`, `matters`→`claims`, `matter_access`→`claim_access`.
- `src/claimos/routers/matters.py` → `routers/claims.py`; URL prefix `/matters`→`/claims`.
- `src/claimos/templates/*matter*.html` (7 files) → `*claim*.html`; all refs updated.
- `src/claimos/static/app.js` — `matter` selectors/URLs → `claim`.
- `migrations/versions/*` — collapsed to one ClaimOS baseline; `migrations/env.py` imports `claimos.*`.
- `src/claimos/migrate_db.py` (new) — one-shot CVP→ClaimOS data copy; script `migrate-db`.
- `pyproject.toml`, `alembic.ini`, `railway.toml`, `.env.example`, `Dockerfile`, `README.md`, `CLAUDE.md`, `docs/*` — naming/path/product-name updates.

---

## Task 1: Package rename `cvp` → `claimos`

Atomic: the app will not import until the whole rename is done, so the green checkpoint is at the end (full suite passes with only the package moved — no domain rename yet).

**Files:**
- Move: `src/cvp/` → `src/claimos/`
- Modify: `pyproject.toml`, `alembic.ini`, `migrations/env.py`, every `.py` under `src/` and `tests/` that imports `cvp`
- Test: existing suite (`tests/`) is the regression net

**Interfaces:**
- Consumes: nothing (first task).
- Produces: the `claimos` package. All later tasks import from `claimos.*` (e.g. `from claimos.models import Base`, `from claimos.db import SessionLocal, engine`).

- [ ] **Step 1: Move the package with git so history is preserved**

```bash
git mv src/cvp src/claimos
```

- [ ] **Step 2: Rewrite every Python import of `cvp`**

Find them first:

```bash
rg -l --glob '*.py' '\bcvp\b' src tests
```

Replace `cvp` → `claimos` in Python import contexts across `src/` and `tests/`. The occurrences are `import cvp...`, `from cvp...`, `from cvp.<mod> import ...`, and string module paths. Do it with a scoped replace, then review the diff:

```bash
rg -l --glob '*.py' '\bcvp\b' src tests | xargs sed -i '' -E 's/\bcvp\b/claimos/g'
```

Then manually inspect the diff for any `cvp` that was NOT a package reference (there should be none in `.py` files; `cvp` only appears as the package name and in the sqlite path handled in Step 4):

```bash
git diff --stat && rg --glob '*.py' '\bcvp\b' src tests
```

Expected: the second `rg` prints nothing.

- [ ] **Step 3: Update `pyproject.toml`**

Change: `[project] name = "claimos"`; every `[project.scripts]` target prefix `cvp.` → `claimos.` (`dev = "claimos.main:run_dev"`, `seed = "claimos.seed:main"`, `seed-auth = "claimos.seed_auth:main"`, `bootstrap-admin = "claimos.bootstrap_admin:main"`); `[tool.hatchling.build.targets.wheel] packages = ["src/claimos"]`; and the two `[tool.ruff.lint.per-file-ignores]` paths `src/cvp/services/...` → `src/claimos/services/...`. Update `description` to `"ClaimOS — contents claim valuation platform"`.

- [ ] **Step 4: Update `alembic.ini`, `migrations/env.py`, and the sqlite default path**

- `alembic.ini`: any `cvp` in `script_location`/`prepend_sys_path` → `claimos`.
- `migrations/env.py`: model imports `from cvp...` → `from claimos...` (target_metadata source).
- `src/claimos/config.py`: change the sqlite default `database_url` from `sqlite:///./data/cvp.db` to `sqlite:///./data/claimos.db`.

- [ ] **Step 5: Reinstall the package under its new name**

```bash
uv sync
```

Expected: resolves and installs `claimos` with the renamed scripts, no errors.

- [ ] **Step 6: Run the full suite — verify green**

```bash
uv run pytest -q
```

Expected: same pass count as before the rename (baseline was 401 passing), zero import errors.

- [ ] **Step 7: Lint + format gate**

```bash
uv run ruff check . && uv run ruff format . && uv run ruff format --check .
```

Expected: clean; `--check` reports zero files to reformat.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor: rename package cvp -> claimos"
```

---

## Task 2: Domain rename `matter` → `claim` (full sweep)

Atomic for the same reason: models, routers, templates, JS, and tests must all flip together for the suite to be green. ~1,198 `matter` occurrences across `src` + `tests`.

**Files:**
- Modify: `src/claimos/models.py`, `models_access.py`, and any other `models_*.py` with `matter_id`
- Rename: `src/claimos/routers/matters.py` → `routers/claims.py`; the 7 `*matter*.html` templates → `*claim*.html`
- Modify: `src/claimos/main.py` (router registration), all routers/services/templates/`static/app.js` referencing matter
- Modify: every test referencing `Matter`/`matter_id`/`/matters`

**Interfaces:**
- Consumes: the `claimos` package (Task 1).
- Produces: ORM class `Claim` (table `claims`); FK column `claim_id` on all child tables; model `ClaimAccess` (table `claim_access`); URL prefix `/claims/{id}`. Task 3 (baseline migration) and Task 4 (`migrate-db`) rely on these exact names: table `claims`, table `claim_access`, and `claim_id` as the child FK column.

- [ ] **Step 1: Inventory the rename surface (record the pre-rename FK-bearing tables)**

```bash
rg -i '\bmatter' src/claimos --glob '*.py' -l
rg 'matter_id' src/claimos --glob '*.py'
```

Note which child tables carry `matter_id` (rooms, item_groups, items, evidence_files, vision_jobs, vision_runs, matter_access, etc.). Task 4 will need this list; capture it in the commit message or a scratch note.

- [ ] **Step 2: Rename the model files' identifiers**

In `src/claimos/models.py` and every `models_*.py`:
- ORM class `Matter` → `Claim` (keep the docstring accurate).
- `__tablename__ = "matters"` → `"claims"`; `matter_access` → `claim_access`.
- Every `matter_id: Mapped[str] = mapped_column(... ForeignKey("matters.id") ...)` → `claim_id ... ForeignKey("claims.id")`.
- Relationship attrs/backrefs: `matter` → `claim`, `matters` → `claims`, `back_populates="matter"` → `back_populates="claim"`.
- Index names: `ix_item_groups_matter_id` → `ix_item_groups_claim_id`; `ix_vision_jobs_matter_created` → `ix_vision_jobs_claim_created`; `uq_item_groups_matter_name_normalized` → `uq_item_groups_claim_name_normalized`; and the columns listed inside those `Index(...)` calls.
- **Leave `claim_number` (the carrier's claim number field) exactly as-is** — it is a distinct concept and already correctly named.

- [ ] **Step 3: Rename the router file, URL prefix, and registration**

```bash
git mv src/claimos/routers/matters.py src/claimos/routers/claims.py
```

In `claims.py`: change the router prefix `/matters` → `/claims`, path params/vars `matter_id` → `claim_id`, ORM refs `Matter` → `Claim`, and any route function names (e.g. `matter_detail` → `claim_detail`). In `src/claimos/main.py`: update the import and `include_router` for the renamed module.

- [ ] **Step 4: Rename templates and update all references**

```bash
git mv src/claimos/templates/matter_detail.html src/claimos/templates/claim_detail.html
git mv src/claimos/templates/matter_new.html src/claimos/templates/claim_new.html
git mv src/claimos/templates/admin/org/matters.html src/claimos/templates/admin/org/claims.html
git mv src/claimos/templates/admin/org/matter_access.html src/claimos/templates/admin/org/claim_access.html
git mv src/claimos/templates/admin/internal/matters.html src/claimos/templates/admin/internal/claims.html
git mv src/claimos/templates/admin/internal/matter_access.html src/claimos/templates/admin/internal/claim_access.html
git mv src/claimos/templates/admin/system/matters.html src/claimos/templates/admin/system/claims.html
```

Update every `{% include %}`/`{% extends %}`/`url_for(...)`/`hx-get`/`hx-post`/`href` reference to those filenames and to the `/matters` routes, and change user-facing "Matter" copy → "Claim" in all templates.

- [ ] **Step 5: Sweep remaining `matter` references in Python, JS, and tests**

```bash
rg -l -i '\bmatter' src/claimos tests --glob '*.py' --glob '*.js' --glob '*.html'
```

Rename `matter`/`Matter`/`matter_id`/`matters` → `claim`/`Claim`/`claim_id`/`claims` in routers, services (`access_cache` comments, sharing), `static/app.js` (selectors, `data-*`, URL strings), and all test fixtures/assertions. Keep `claim_number` untouched.

- [ ] **Step 6: Completeness check — no domain `matter` left**

```bash
rg -i '\bmatter' src/claimos tests
```

Expected: zero hits (or only clearly-unrelated English prose in a comment, which you then reword). If anything domain-related remains, fix it before continuing.

- [ ] **Step 7: Run the full suite — verify green**

```bash
uv run pytest -q
```

Expected: same pass count as after Task 1 (schema rebuilt from renamed models via `create_all`; all `claims`/`claim_id` tables present).

- [ ] **Step 8: Guard the invariants — CSV headers unchanged**

Run the CSV-export test(s) and confirm headers are identical to pre-rename:

```bash
uv run pytest -q -k "csv or export"
```

Expected: PASS with no header diffs. (If any export test hard-codes `/matters` URLs, that's a rename it needed — but Xactimate column names must be byte-identical.)

- [ ] **Step 9: Lint + format gate**

```bash
uv run ruff check . && uv run ruff format . && uv run ruff format --check .
```

Expected: clean.

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "refactor: rename domain matter -> claim across schema, routes, templates, tests"
```

---

## Task 3: Collapse Alembic to a clean ClaimOS baseline

Tests use `create_all`, so this is verified independently of the suite: the baseline must produce a schema whose autogenerate diff against the ORM is empty, and `seed` must run.

**Files:**
- Delete: `migrations/versions/*.py` (all 18)
- Create: one new baseline revision in `migrations/versions/`
- Verify against a scratch DB

**Interfaces:**
- Consumes: renamed models (`claims` schema) from Task 2; `migrations/env.py` importing `claimos.*` from Task 1.
- Produces: a single head revision that builds the full ClaimOS schema. Task 4 and the operator runbook run `alembic upgrade head` against a fresh Postgres.

- [ ] **Step 1: Remove the old CVP migration history**

```bash
git rm migrations/versions/*.py
```

(The legacy history remains intact on the `cvp-legacy` branch; ClaimOS starts fresh.)

- [ ] **Step 2: Generate the baseline against an empty scratch DB**

```bash
DATABASE_URL="sqlite:////tmp/claimos_baseline.db" uv run alembic revision --autogenerate -m "baseline claimos schema"
```

Expected: one new file in `migrations/versions/` with `down_revision = None` and `create_table("claims")`, `claim_access`, `claim_id` FKs, and the renamed indexes.

- [ ] **Step 3: Apply it and confirm an empty autogenerate diff**

```bash
rm -f /tmp/claimos_verify.db
DATABASE_URL="sqlite:////tmp/claimos_verify.db" uv run alembic upgrade head
DATABASE_URL="sqlite:////tmp/claimos_verify.db" uv run alembic revision --autogenerate -m "should-be-empty" 2>&1 | tee /tmp/diffcheck.txt
```

Open the generated "should-be-empty" file: its `upgrade()`/`downgrade()` must be empty (no ops). If empty, delete it:

```bash
# delete the throwaway empty revision, keeping only the baseline
git status --porcelain migrations/versions/
```

Expected: the second autogenerate produces no schema operations.

- [ ] **Step 4: Confirm seed runs against the migrated DB**

```bash
DATABASE_URL="sqlite:////tmp/claimos_verify.db" uv run seed
```

Expected: 42 category rows inserted; re-running is idempotent (no duplicates, no error).

- [ ] **Step 5: Lint/format + commit**

```bash
uv run ruff check . && uv run ruff format . && uv run ruff format --check .
git add -A
git commit -m "chore: collapse alembic history into clean ClaimOS baseline migration"
```

---

## Task 4: One-shot CVP→ClaimOS data-migration script (`migrate-db`)

Genuinely new code — real TDD. A declarative table plan drives a generic, FK-ordered copier that reads the legacy CVP DB (read-only) and writes the ClaimOS DB, remapping `matters`→`claims`, `matter_access`→`claim_access`, and `matter_id`→`claim_id`.

**Files:**
- Create: `src/claimos/migrate_db.py`
- Create: `tests/test_migrate_db.py`
- Modify: `pyproject.toml` (`[project.scripts]` add `migrate-db = "claimos.migrate_db:main"`)

**Interfaces:**
- Consumes: `claims`/`claim_access`/`claim_id` names from Task 2; a target DB already at head + seeded (Task 3).
- Produces: `migrate_db.migrate(source_url: str, target_url: str) -> dict[str, int]` returning `{table_name: rows_copied}`; and `main()` reading `LEGACY_DATABASE_URL` (source) and `DATABASE_URL` (target) from the environment.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_migrate_db.py
import sqlalchemy as sa

from claimos.migrate_db import migrate


def _make_legacy_db(url: str) -> None:
    """Minimal CVP-schema (pre-rename) fixture built with raw DDL so it does not
    depend on the removed `matters` ORM classes."""
    eng = sa.create_engine(url)
    with eng.begin() as c:
        c.exec_driver_sql(
            "CREATE TABLE groups (id TEXT PRIMARY KEY, name TEXT, kind TEXT, is_active INTEGER)"
        )
        c.exec_driver_sql(
            "CREATE TABLE matters (id TEXT PRIMARY KEY, policyholder_name TEXT, "
            "owner_group_id TEXT, status TEXT)"
        )
        c.exec_driver_sql(
            "CREATE TABLE rooms (id TEXT PRIMARY KEY, matter_id TEXT, name TEXT, sort_order INTEGER)"
        )
        c.exec_driver_sql("INSERT INTO groups VALUES ('g1', 'Acme Firm', 'external', 1)")
        c.exec_driver_sql(
            "INSERT INTO matters VALUES ('m1', 'Jane Doe', 'g1', 'draft')"
        )
        c.exec_driver_sql("INSERT INTO rooms VALUES ('r1', 'm1', 'Kitchen', 0)")


def _make_claimos_db(url: str) -> None:
    """Target ClaimOS schema (subset matching the plan under test)."""
    eng = sa.create_engine(url)
    with eng.begin() as c:
        c.exec_driver_sql(
            "CREATE TABLE groups (id TEXT PRIMARY KEY, name TEXT, kind TEXT, is_active INTEGER)"
        )
        c.exec_driver_sql(
            "CREATE TABLE claims (id TEXT PRIMARY KEY, policyholder_name TEXT, "
            "owner_group_id TEXT, status TEXT)"
        )
        c.exec_driver_sql(
            "CREATE TABLE rooms (id TEXT PRIMARY KEY, claim_id TEXT, name TEXT, sort_order INTEGER)"
        )


def test_migrate_copies_and_remaps(tmp_path):
    src = f"sqlite:///{tmp_path/'legacy.db'}"
    tgt = f"sqlite:///{tmp_path/'claimos.db'}"
    _make_legacy_db(src)
    _make_claimos_db(tgt)

    counts = migrate(src, tgt, only_tables=["groups", "claims", "rooms"])

    assert counts == {"groups": 1, "claims": 1, "rooms": 1}

    eng = sa.create_engine(tgt)
    with eng.connect() as c:
        claim = c.exec_driver_sql("SELECT id, policyholder_name FROM claims").one()
        room = c.exec_driver_sql("SELECT id, claim_id, name FROM rooms").one()
    assert claim == ("m1", "Jane Doe")
    assert room == ("r1", "m1", "Kitchen")  # matter_id -> claim_id preserved value
```

- [ ] **Step 2: Run it to confirm it fails**

```bash
uv run pytest tests/test_migrate_db.py -q
```

Expected: FAIL — `ModuleNotFoundError: No module named 'claimos.migrate_db'`.

- [ ] **Step 3: Implement `migrate_db.py`**

```python
# src/claimos/migrate_db.py
"""One-shot data migration: legacy CVP database -> new ClaimOS database.

Reads the source (legacy CVP schema, `matters`/`matter_id`) READ-ONLY and writes
the target (ClaimOS schema, `claims`/`claim_id`). Run once at cutover after the
target DB is at `alembic upgrade head` and seeded.
"""

from __future__ import annotations

import os

import sqlalchemy as sa

# (target_table, source_table, {source_col: target_col})
# Identity rows have source==target and no column renames. Only the claim rename
# differs. Ordered so parents are inserted before children (FK-safe).
TABLE_PLAN: list[tuple[str, str, dict[str, str]]] = [
    ("groups", "groups", {}),
    ("users", "users", {}),
    ("app_setting", "app_setting", {}),
    ("categories", "categories", {}),
    ("vision_models", "vision_models", {}),
    ("claims", "matters", {}),
    ("claim_access", "matter_access", {"matter_id": "claim_id"}),
    ("rooms", "rooms", {"matter_id": "claim_id"}),
    ("item_groups", "item_groups", {"matter_id": "claim_id"}),
    ("items", "items", {"matter_id": "claim_id"}),
    ("item_crops", "item_crops", {}),
    ("evidence_files", "evidence_files", {"matter_id": "claim_id"}),
    ("vision_runs", "vision_runs", {"matter_id": "claim_id"}),
    ("vision_jobs", "vision_jobs", {"matter_id": "claim_id"}),
    ("vision_job_images", "vision_job_images", {}),
    ("serp_searches", "serp_searches", {}),
    ("comments", "comments", {}),
    ("feedback", "feedback", {}),
    ("feedback_comments", "feedback_comments", {}),
    ("audit_logs", "audit_logs", {"matter_id": "claim_id"}),
    ("refresh_tokens", "refresh_tokens", {}),
]


def _copy_table(
    src: sa.engine.Connection,
    tgt: sa.engine.Connection,
    target_table: str,
    source_table: str,
    renames: dict[str, str],
) -> int:
    rows = src.exec_driver_sql(f"SELECT * FROM {source_table}").mappings().all()
    if not rows:
        return 0
    out = []
    for row in rows:
        d = {renames.get(k, k): v for k, v in dict(row).items()}
        out.append(d)
    cols = list(out[0].keys())
    collist = ", ".join(cols)
    params = ", ".join(f":{c}" for c in cols)
    # upsert-by-PK so a failed run is re-runnable
    tgt.execute(
        sa.text(f"INSERT OR REPLACE INTO {target_table} ({collist}) VALUES ({params})")
        if tgt.dialect.name == "sqlite"
        else sa.text(
            f"INSERT INTO {target_table} ({collist}) VALUES ({params}) "
            f"ON CONFLICT (id) DO NOTHING"
        ),
        out,
    )
    return len(out)


def migrate(
    source_url: str, target_url: str, only_tables: list[str] | None = None
) -> dict[str, int]:
    src_eng = sa.create_engine(source_url)
    tgt_eng = sa.create_engine(target_url)
    counts: dict[str, int] = {}
    with src_eng.connect() as src, tgt_eng.begin() as tgt:
        for target_table, source_table, renames in TABLE_PLAN:
            if only_tables is not None and target_table not in only_tables:
                continue
            counts[target_table] = _copy_table(
                src, tgt, target_table, source_table, renames
            )
    return counts


def main() -> None:
    source = os.environ["LEGACY_DATABASE_URL"]
    target = os.environ["DATABASE_URL"]
    counts = migrate(source, target)
    total = sum(counts.values())
    for table, n in counts.items():
        print(f"  {table}: {n}")
    print(f"migrated {total} rows across {len(counts)} tables")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the test — verify it passes**

```bash
uv run pytest tests/test_migrate_db.py -q
```

Expected: PASS.

- [ ] **Step 5: Register the script**

Add to `pyproject.toml` `[project.scripts]`: `migrate-db = "claimos.migrate_db:main"`, then:

```bash
uv sync
```

- [ ] **Step 6: Full suite + lint/format gate**

```bash
uv run pytest -q && uv run ruff check . && uv run ruff format . && uv run ruff format --check .
```

Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: add one-shot CVP->ClaimOS migrate-db data migration"
```

---

## Task 5: Product identity + docs (name/vocabulary only)

No visual rebrand. Update the product name where it appears as an identifier and in docs; keep legal copy and layout untouched.

**Files:**
- Modify: `src/claimos/config.py` (`openrouter_app_title`), any `<title>`/brand-string in `templates/base.html`
- Modify: `README.md`, `CLAUDE.md`, affected `docs/*.md`, `.env.example`

**Interfaces:**
- Consumes: renamed package/domain (Tasks 1–2).
- Produces: docs that describe `src/claimos/`, `/claims` routes, the coexistence/legacy model, and the deferred styling/SaaS slices.

- [ ] **Step 1: Product-name identifiers**

In `src/claimos/config.py` change `openrouter_app_title: str = "CVP"` → `"ClaimOS"`. In `templates/base.html` update the `<title>`/brand text "CVP"/"Contents Valuation…" → "ClaimOS" **without** altering layout/classes. Leave `company_name` ("Contents Valuation LLC") unchanged.

- [ ] **Step 2: Update `CLAUDE.md`**

Update the package path references `src/cvp/` → `src/claimos/`, the project-layout block, the command list, and the "What this project is" framing to note: product is now **ClaimOS**; the internal→external SaaS posture and immutable rule #6 (no public registration) are revisited in the SaaS follow-on; the visual rebrand is a separate mockup-driven slice; `cvp-legacy` branch holds the frozen internal deployment.

- [ ] **Step 3: Rewrite `README.md` to reflect ClaimOS**

`README.md` is the primary onboarding doc — update it thoroughly, not just the title:
- Product name/heading and description → **ClaimOS**.
- Package/path references `src/cvp/` → `src/claimos/`; the sqlite path `data/cvp.db` → `data/claimos.db`.
- Command list — confirm every `uv run` command still matches the renamed `[project.scripts]` (`dev`, `seed`, `seed-auth`, `bootstrap-admin`, and the new `migrate-db`); document `migrate-db` and its `LEGACY_DATABASE_URL`/`DATABASE_URL` env vars.
- Any `/matters` URL examples → `/claims`; any "matter" domain wording → "claim".
- Add a short "Legacy CVP / coexistence" note: the frozen `cvp-legacy` branch serves the internal deployment until clients migrate.
- Leave macOS prereqs (`brew install pango cairo libffi`) and stack sections unchanged except naming.

- [ ] **Step 4: Update `docs/*` and `.env.example`**

Sweep `docs/*.md` for `cvp`/`matter` references that are now stale (keep historical spec/plan **filenames** as-is). In `.env.example`, add a commented `LEGACY_DATABASE_URL=` line (source DB for `migrate-db`) and note the ClaimOS `DATABASE_URL` target.

- [ ] **Step 5: Verify no stale product/path references remain in docs chrome**

```bash
rg -n '\bcvp\b|src/cvp|/matters\b|\bmatter\b' README.md CLAUDE.md
```

Expected: no hits except intentional historical references (e.g. the `cvp-legacy` branch name). Review each remaining hit.

- [ ] **Step 6: Lint/format + commit**

```bash
uv run ruff check . && uv run ruff format . && uv run ruff format --check .
git add -A
git commit -m "docs: rebrand product name to ClaimOS; update README, package paths, legacy/coexistence notes"
```

---

## Task 6: Deploy/config for the separate ClaimOS environment

Config-file side only; the actual Railway/GitHub/DNS actions are in the Operator Runbook.

**Files:**
- Modify: `railway.toml`, `Dockerfile`, `.dockerignore`, `.env.example`

**Interfaces:**
- Consumes: renamed scripts (`claimos.*` entry points) and the baseline migration.
- Produces: a deploy config that boots ClaimOS on a fresh Postgres via `preDeployCommand` (`alembic upgrade head` → `seed` → `bootstrap-admin`).

- [ ] **Step 1: Update `Dockerfile` / `.dockerignore`**

Replace any `src/cvp` path or `cvp` package references with `claimos`. Confirm the WeasyPrint native libs and uv install steps are otherwise unchanged.

- [ ] **Step 2: Update `railway.toml`**

Confirm/point `preDeployCommand` at the renamed scripts and the baseline migration (`uv run alembic upgrade head && uv run seed && uv run bootstrap-admin`), healthcheck path `/healthz` unchanged.

- [ ] **Step 3: Build the container locally to catch path breakage**

```bash
docker build -t claimos:plan-check .
```

Expected: image builds; no missing `src/claimos` path errors. (If Docker is unavailable in the execution environment, skip and note it for the operator.)

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore: point deploy config (Dockerfile, railway.toml) at claimos package"
```

---

## Operator Runbook (manual, sequenced — not subagent steps)

Run these around the merge; they touch git remotes, Railway, GitHub, and DNS.

1. **Freeze legacy (before merging the rename):** from today's `main`,
   `git branch cvp-legacy main && git push -u origin cvp-legacy`. In Railway, set the existing **CVP production** service to auto-deploy `cvp-legacy`. Confirm it still deploys and `/healthz` is green. Legacy is now frozen (critical fixes only).
2. **Merge** `feat/claimos-rename` → `main` (squash per repo convention).
3. **Rename the GitHub repo** `clawmondor/cvp` → `clawmondor/claimos` (Settings → rename). Do **not** create a new repo named `cvp`. Update local remotes: `git remote set-url origin https://github.com/clawmondor/claimos.git`.
4. **Provision the ClaimOS environment:** new Railway environment/service, **new empty Postgres**, new subdomain via Cloudflare, distinct secrets (`ANTHROPIC_API_KEY`/`OPENROUTER_API_KEY`, `JWT_SECRET`, `MFA_ENCRYPTION_KEY`, admin bootstrap vars). Set `DATABASE_URL` to the new Postgres. Deploy `main`; `preDeployCommand` runs baseline migration + seed + bootstrap-admin. Confirm `/healthz` green.
5. **Cutover migration:** set `LEGACY_DATABASE_URL` to the CVP prod Postgres (read-only creds if possible) and `DATABASE_URL` to the ClaimOS Postgres; run `uv run migrate-db`. Verify per-table row-count parity and spot-check RCV/ACV totals + evidence-file counts against legacy.
6. **Retire legacy** once cutover is verified and clients are on ClaimOS.

---

## Self-Review

**Spec coverage:**
- §5 repo/branch model → Operator Runbook 1–3.
- §6 package rename → Task 1.
- §7 domain rename → Task 2 (incl. CSV/PDF invariants guarded in Step 8 + Global Constraints).
- §8.1 baseline migration → Task 3.
- §8.2 one-shot full-DB migration → Task 4.
- §9 product identity + legal-copy invariants → Task 5 + Global Constraints.
- §10 environments/deploy → Task 6 + Operator Runbook 4–6.
- §11 follow-on (styling/SaaS) → out of scope, noted in Task 5 Step 2 docs.
- §12 testing/verification → each task's suite + lint/format gate; migration smoke test in Task 4.
- §13 sequencing → task order + Operator Runbook.

**Placeholder scan:** No "TBD"/"handle edge cases"/"write tests for the above" — the one new-code task (Task 4) has full test + implementation code; rename tasks use concrete commands with a completeness `rg` check and the suite as the gate.

**Type consistency:** `migrate(source_url, target_url, only_tables=None) -> dict[str,int]` is defined in Task 4 Step 3 and used identically in the Step 1 test; table/column names (`claims`, `claim_access`, `claim_id`) match Task 2's Produces block and the `TABLE_PLAN`.
