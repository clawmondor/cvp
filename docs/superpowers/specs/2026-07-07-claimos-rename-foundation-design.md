# ClaimOS Rename & Rebrand — Foundation Design Spec

**Status:** Approved for planning · **Branch:** `feat/claimos-rename` (off `main`) · **Date:** 2026-07-07

This is the **foundation** effort of the CVP → ClaimOS pivot. It does the deep
rename (`cvp` package → `claimos`, `matter` domain → `claim`), rebrands the
product to **ClaimOS**, and stands up a **separate, isolated ClaimOS runtime
environment** alongside the existing internal CVP production instance.

It is deliberately **not** the SaaS build. Self-service onboarding, billing, and
tenant-isolation hardening are tracked as a **follow-on effort** (see §11) and are
out of scope here.

---

## 1. Context & the decision that shaped this

The current internal CVP is **live with real client data** (LA-attorney Palisades
/ Eaton fire claims). The pivot goal is a rename + rebrand to ClaimOS as the first
step toward an external SaaS. Key constraints established during brainstorming:

- **Live data must be protected** — no destructive migration on the running CVP DB.
- **Coexist temporarily, then converge** — the internal CVP keeps running during a
  transition; existing clients migrate onto ClaimOS over time; then CVP is retired.
  We end at **one product, one repo**.
- **Legacy CVP is frozen** during the transition — critical/security fixes only; all
  new work goes into ClaimOS.
- The prior `v2` branch and `feat/claimos-shell-ia` "slice" program are **abandoned**
  and are not a foundation for this work.

The question "new repo + prod env, or evolve in place?" resolves across three
independent axes:

| Axis | Decision | Why |
| --- | --- | --- |
| **Runtime / environment** | Separate, isolated ClaimOS environment (new Railway env + new Postgres + new subdomain). | CVP prod has live data and must keep running during coexistence. |
| **Repo / codebase** | **One repo, rename in place.** `main` becomes the ClaimOS mainline; `cvp-legacy` branch serves frozen legacy. | Legacy is frozen and we converge to one product — a fork is permanent duplicate overhead for something we retire. |
| **DB rename mechanics** | **Fresh `claims` schema on a new Postgres + per-client ETL.** The live CVP DB is never renamed. | Eliminates any destructive in-place migration on live client data. |

The existing schema already has a tenant boundary — `Group` is *"an organization —
one internal, many external,"* users belong to a group, and `Matter.owner_group_id`
scopes each matter to an owning org — so the eventual SaaS is **additive**, not a
rewrite. This spec does not build on that; it just preserves it through the rename.

---

## 2. Goal

Land a single "this is ClaimOS now" moment: the repo, package, domain vocabulary,
and branding all flip together, `main` deploys to a fresh isolated ClaimOS
environment, and the frozen internal CVP keeps serving existing clients unchanged —
with a repeatable path to migrate each client's data from CVP into ClaimOS.

## 3. Scope

**In scope:**

- GitHub repo rename `clawmondor/cvp` → `clawmondor/claimos` (stays under `clawmondor`).
- Branch model: `main` = ClaimOS mainline; long-lived frozen `cvp-legacy` branch.
- Python package rename `src/cvp/` → `src/claimos/` and every import/entry-point.
- Domain rename `matter` → `claim` across ORM, DB schema, routes, templates, JS, tests.
- Clean squashed **baseline** Alembic migration for the ClaimOS `claims` schema.
- New ClaimOS Railway environment: fresh Postgres, subdomain, distinct secrets.
- Per-client **ETL script** to migrate one client's data CVP-DB → ClaimOS-DB.
- Rebrand to **ClaimOS** (name only) across UI chrome, README, docs.
- Docs updates (`CLAUDE.md`, `README.md`, affected `docs/`).

**Out of scope (follow-on — see §11):**

- Self-service registration / onboarding, billing, subscription/plan model.
- Tenant-isolation hardening beyond what exists today (row-level enforcement audits,
  per-tenant rate limits, etc.).
- Rewriting the "internal ops tool" posture and immutable rule #6 (no public
  registration) — revisited when SaaS lands.
- Any new domain features, workflow, or UI beyond the rename/rebrand.

## 4. Non-goals / invariants preserved

- **No semantic change** — this is a naming change. Depreciation logic, the 42
  categories, ACV/RCV/cents rules, and the audit-trail requirement are untouched.
- **Xactimate CSV column headers are unchanged.** Carriers/attorneys match exact
  headers. The rename must not touch export column names.
- **PDF report content is unchanged** except the product name where it appears; the
  "Confidential — Attorney Work Product" marker stays.
- **Legal/compliance copy substance is unchanged** — flat-fee, not a public adjuster,
  does not provide legal advice, attorney work product. Only the product *name*
  changes in this effort (see §9).
- **No new dependencies**, no stack changes. CSP unchanged; no inline JS/event
  handlers introduced.
- The live CVP production database is **never** renamed or migrated in place.

---

## 5. Repo & branch model

1. **Before** the rename merges, cut a long-lived branch **`cvp-legacy`** from
   today's `main`. This is the frozen legacy line. Repoint the existing CVP Railway
   production environment to auto-deploy from `cvp-legacy`.
2. Do the rename on **`feat/claimos-rename`** (off `main`). Review, then merge to
   `main`. `main` is now the ClaimOS mainline.
3. **Rename the GitHub repo** `clawmondor/cvp` → `clawmondor/claimos` at the same
   time the rename branch lands, so repo name and code name flip together.
   - GitHub preserves redirects (web, fetch, clone, API) from the old name
     indefinitely. **Do not create a new repo named `cvp`** afterward — that is the
     only action that severs the redirect. It is not needed: legacy lives in the same
     repo as the `cvp-legacy` branch.
   - Railway links to the repo by **GitHub repo ID**, not name, so both environments
     stay connected through the rename (confirm labels in the dashboard).
4. **Local cleanup:** `git remote set-url origin https://github.com/clawmondor/claimos.git`
   in working copies; update README/docs links and Railway service display names.
   Renaming the local folder (`~/consulting/tor` → `~/consulting/claimos`) is optional.

## 6. Package rename (`cvp` → `claimos`)

Mechanical, single-purpose change:

- Move `src/cvp/` → `src/claimos/`. Rewrite every `import cvp` / `from cvp.…`
  (~122 Python files reference `cvp`).
- `pyproject.toml`: `[project] name`, `[project.scripts]` targets
  (`dev = claimos.main:run_dev`, `seed`, `seed-auth`, `bootstrap-admin`),
  `[tool.hatchling.build.targets.wheel] packages = ["src/claimos"]`, and the
  `[tool.ruff.lint.per-file-ignores]` paths (`src/claimos/services/…`).
- `alembic.ini` (`script_location`, any `cvp` references) and `migrations/env.py`
  (`from claimos… import Base`, model imports).
- `src/claimos/main.py` app wiring, `config.py` env-var prefix if any, `db.py`.
- Mirror `tests/` imports to `claimos`.
- **Gate:** `uv run pytest` fully green and `uv run ruff format --check .` clean.

## 7. Domain rename (`matter` → `claim`)

~1,198 `matter` occurrences across `src` + `tests`. Rename consistently:

- **ORM (`src/claimos/models*.py`):** class `Matter` → `Claim`; every `matter_id`
  FK column → `claim_id` (Room, Item, ItemGroup, EvidenceFile, VisionRun,
  VisionJob, etc.); `matter_access` model → `claim_access`; relationships/backrefs
  (`matter` → `claim`, `matters` → `claims`); index names
  (`ix_item_groups_matter_id` → `ix_item_groups_claim_id`,
  `ix_vision_jobs_matter_created` → `ix_vision_jobs_claim_created`,
  `uq_item_groups_matter_name_normalized` → `…_claim_name_normalized`).
- **Tables/columns:** `matters` → `claims`; all `matter_id` FK columns → `claim_id`.
  - **Keep** the existing `claim_number` field on the claims table as-is — it is a
    distinct concept (the carrier's claim number) and does not collide.
- **Routes:** `routers/matters.py` → `routers/claims.py`; URL prefix
  `/matters/{id}` → `/claims/{id}`; update `main.py` router registration and all
  `url_for`/`hx-get`/`href` references.
- **Templates:** rename the 7 `*matter*` template files
  (`matter_detail.html`, `matter_new.html`, `admin/org/matters.html`,
  `admin/org/matter_access.html`, `admin/internal/matters.html`,
  `admin/internal/matter_access.html`, `admin/system/matters.html`) → `claim*`
  equivalents; update every `include`/`extends`/link/`data-*` reference and all
  human-visible "Matter" copy → "Claim".
- **JS:** `src/claimos/static/app.js` selectors, `data-*` hooks, any `matter`
  strings/URLs → `claim`. No inline handlers (CLAUDE.md rule).
- **Untouched:** Xactimate CSV headers, PDF content, depreciation, seed categories.

## 8. Database strategy

ClaimOS runs on a **brand-new Postgres**; the live CVP DB is never renamed.

### 8.1 Clean baseline migration
Collapse the current 18 CVP migrations into a **single squashed baseline** Alembic
revision that creates the ClaimOS `claims` schema directly (correct table/column
names from the start — no rename migration). The legacy migration history stays
intact and untouched on `cvp-legacy`. The ClaimOS `migrations/versions/` starts
from this one baseline.

- Regenerate the baseline against a scratch DB, verify `alembic upgrade head`
  produces a schema that matches the ORM (autogenerate diff is empty), then
  `uv run seed` populates the 42 categories.

### 8.2 Per-client ETL (CVP → ClaimOS)
A one-time, per-client migration script (`src/claimos/…` or a `scripts/` entry,
exposed as a `[project.scripts]` command, e.g. `migrate-client`):

- Connects to **both** the legacy CVP Postgres (source) and the ClaimOS Postgres
  (target).
- Copies one owning `Group`'s data: its `matters` → `claims`, and all children
  (rooms, item_groups, items, item_crops, evidence_files, vision_*), preserving
  UUID primary keys and foreign-key relationships and remapping `matter_id` →
  `claim_id`.
- Copies associated users/group and `matter_access` → `claim_access` rows as needed
  so the migrated client can log in and see their claims.
- Runs **read-only against the source** (never mutates legacy data).
- Idempotent / re-runnable per client (skip or upsert on existing PK) so a failed
  run can be retried.
- **Verification:** row-count and spot-value diff (RCV/ACV totals per claim,
  evidence-file counts) between source and target after each run.

Run per client at their cutover moment. When the last client is migrated, retire the
legacy environment.

## 9. Rebrand & legal copy (name-only)

- Product name **ClaimOS** in `<title>`, base chrome/brand mark, README, and the
  product name wherever it appears in PDF/CSV markers. The
  "Confidential — Attorney Work Product" marker keeps its meaning under the new name.
- **Do not** rewrite the substance of the legal/compliance copy in this effort. The
  flat-fee / not-a-public-adjuster / no-legal-advice / attorney-work-product
  disclaimers are product-independent and still apply verbatim.
- The internal-only → external-SaaS posture rewrite — including immutable rule #6
  ("no public registration; attorneys do not log in") — is explicitly **deferred to
  the SaaS follow-on**. Until then, the app remains internal-auth only.

## 10. Environments & deploy

- **New ClaimOS Railway environment/service:** fresh Postgres (empty → baseline
  migration + seed + bootstrap-admin via `preDeployCommand`), its own subdomain via
  Cloudflare, and **distinct** secrets (`ANTHROPIC_API_KEY`, JWT/auth secrets, admin
  bootstrap vars). Never share the CVP prod DB.
- **Legacy CVP environment:** repointed to auto-deploy from `cvp-legacy`. Frozen
  except cherry-picked critical fixes.
- `railway.toml` preDeploy chain (`alembic upgrade head` → `seed` →
  `bootstrap-admin`) verified against the fresh ClaimOS Postgres; `/healthz` green.
- `.env.example` updated for ClaimOS naming; the real `.env` is never committed.

## 11. Follow-on: SaaS-ification (tracked, not built here)

A separate brainstorm → spec → plan cycle covers, in roughly this order:
self-service registration & org onboarding; billing/subscription; tenant-isolation
hardening (audit every query for `owner_group` scoping, add row-level guards);
revisiting the legal/compliance posture and immutable rule #6 for external users.
This spec's clean rename is the enabling foundation for that work.

## 12. Testing & verification

- `uv run pytest` fully green after the rename (tests renamed to match).
- `uv run ruff check .` clean; `uv run ruff format --check .` reports zero
  reformatting (CLAUDE.md hard rule — CI has failed on this before).
- App boots locally (`uv run dev`); a smoke click-through of a claim workspace,
  evidence upload, an item with a priced source, PDF preview, and CSV export.
- Alembic: `alembic upgrade head` on an empty DB yields a schema whose autogenerate
  diff against the ORM is empty; `uv run seed` idempotent.
- ETL smoke test: seed a fixture client in a scratch "legacy" DB, run the migration
  into a scratch ClaimOS DB, assert row counts and RCV/ACV totals match.
- `/healthz` green on the new ClaimOS environment after first deploy.

## 13. Sequencing (keep legacy safe throughout)

1. Cut and push `cvp-legacy`; repoint the CVP prod environment to it. Confirm it
   still deploys and serves. *(Legacy is now safe and frozen.)*
2. On `feat/claimos-rename`: package rename (§6) → tests green.
3. Domain rename (§7) → tests green; `ruff format` clean.
4. Squash to baseline migration (§8.1); verify empty autogenerate diff + seed.
5. Rebrand + docs (§9, and `CLAUDE.md`/`README`/`docs/`).
6. Write + test the per-client ETL (§8.2).
7. Review; merge to `main`; rename the GitHub repo (§5.3).
8. Provision the ClaimOS Railway environment (§10); deploy `main`; `/healthz` green.
9. Migrate the first client with the ETL; verify; begin phased client cutovers.

---

## Appendix — scope facts (as of 2026-07-07)

- `cvp` referenced in ~122 `.py`, 4 `.html`, 2 `.js`, 2 config files.
- ~1,198 `matter` occurrences across `src` + `tests`.
- 21 tables; `matters` + all `matter_id` FKs are the rename surface.
- 7 template files with `matter` in the filename.
- 18 existing Alembic migrations → collapse to 1 baseline for ClaimOS.
- Entry-point scripts: `dev`, `seed`, `seed-auth`, `bootstrap-admin`
  (+ new `migrate-client` for the ETL).
