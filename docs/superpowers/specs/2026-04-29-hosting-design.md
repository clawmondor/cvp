# Hosting & Deployment Design Spec

**Date:** 2026-04-29
**Status:** Draft
**Scope:** Choose a hosting provider and design the deployment topology for the CVP application, including database, container runtime, DNS/SSL, secrets, CI/CD, and disaster recovery posture. Optimize for cost over performance.

---

## 1. Overview

The CVP application is moving off the founder's laptop and onto a hosted production environment. The recent addition of authentication, MFA, and RBAC (commits `5c5a48f` through `2d42548`) makes a multi-user deployment necessary. This spec selects a provider stack, defines the production topology, and lists every code/config change required to get there safely.

Target: ~$10–25/mo, managed PaaS (git-push-to-deploy), supports WeasyPrint native dependencies, US-region, encryption at rest, no formal compliance regime, daily backups + provider-native point-in-time recovery.

### 1.1 Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Hosting provider (web) | Render Web Service (Starter tier) | Git-push deploy, Dockerfile support for native libs, low ops |
| Hosting provider (DB) | Render Postgres Standard | Bundled PITR; one-vendor billing simplicity beats $12/mo savings of Neon |
| Database engine (prod) | Postgres | Required by managed-PaaS shape; SQLite stays for local dev |
| DNS / registrar | Cloudflare (already in use) | User familiarity; existing infra |
| CDN/edge mode | Cloudflare proxied (orange cloud) | User familiarity; sensitive data benefits from WAF/DDoS perimeter |
| SSL mode | Full (strict) | CF validates Render's Let's Encrypt cert at origin |
| Container | Dockerfile, `python:3.11-slim` base | Required for WeasyPrint's pango/cairo libs |
| Web tier sizing | Starter (512 MB), upgrade-when-it-bites | Cheapest starting point; alert-driven upgrade |
| Evidence images | Render persistent disk (10 GB) | Keep v0 simple; R2 backlogged |
| Offsite backups | Backlogged | Provider PITR is sufficient for v0 |
| Admin bootstrap | Env-var-driven, idempotent, removed after first use | Fits automated deploy; trade-off acceptable for 4–10-user team |
| CI | GitHub Actions (lint, test, secrets-scan) | Repo-native, free for public repos |
| Schema rollback policy | Forward-only, additive migrations | Avoids code-vs-schema lock-step rollback complexity |
| Staging environment | None in v0 | $26/mo cost not justified at current team size |

### 1.2 Out of Scope

- Offsite backups (backlogged with explicit DR risk note)
- Cloudflare R2 for evidence images (backlogged with cost/egress upside note)
- Render PR Preview Environments
- Staging environment
- Authenticated Origin Pulls (Cloudflare → Render mTLS)
- Browser-based end-to-end tests
- Multi-region deployment
- Background worker / queue infrastructure

---

## 2. Topology

```
                    User browser
                         │
                         ▼
              Cloudflare DNS / Registrar
              cvp.<your-domain> (proxied, orange)
                         │
                         ▼
              Render Web Service
              (Oregon or Virginia, single region)
                  │           │
                  ▼           ▼
        Render Postgres   Anthropic API
        (private network,
        Standard tier with PITR)

              Render Persistent Disk
              (10 GB, mounted at /app/data)
              attached to Web Service
```

Single web service, single Postgres, no background workers. Evidence images live on the persistent disk, mounted to preserve the existing `./data/` filesystem convention so application code doesn't change.

---

## 3. Container & Runtime

### 3.1 Dockerfile (lives at repo root)

```dockerfile
FROM python:3.11-slim AS base

# WeasyPrint native deps + libpq for psycopg
RUN apt-get update && apt-get install -y --no-install-recommends \
      libpango-1.0-0 libpangoft2-1.0-0 libcairo2 libffi8 \
      libpq5 fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

CMD ["uv", "run", "uvicorn", "cvp.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
```

### 3.2 Runtime notes

- **`--proxy-headers --forwarded-allow-ips=*`**: required behind Cloudflare + Render's load balancer. Both layers are trusted because the container is unreachable any other way.
- **`uv` toolchain inside container**: matches local development, eliminates resolver drift.
- **`uv sync --frozen --no-dev`**: production install, dev deps stripped.
- **Fonts**: `fonts-liberation` provides Helvetica / Times / Courier substitutes for WeasyPrint. Add others if a PDF template requires them.
- **Image size target**: ~250–300 MB.
- **Healthcheck endpoint**: `GET /healthz` — returns 200 only when the DB connection is healthy. Render polls this during deploys and runtime.
- **Persistent disk mount**: `/app/data` (matches existing `./data/` convention).

### 3.3 Tier sizing

Start on Render Web Starter (512 MB RAM, $7/mo). WeasyPrint can spike memory while rendering large PDFs, so:

- Configure a Render alert at memory > 80% sustained.
- If the alert fires repeatedly, upgrade to Standard ($25/mo, 2 GB RAM) — dropdown change, no code work.
- Alternative mitigation: cap PDF generation at ~100 items per render and paginate larger matters. Defer this until the alert fires; YAGNI.

---

## 4. Database & SQLite → Postgres Migration

### 4.1 Tier choice

**Render Postgres Standard** — ~$19/mo, 1 GB RAM, ~10 GB storage, daily snapshots **plus continuous WAL archival (PITR)** allowing recovery to any second within the last 7 days. Without offsite backups, PITR is the only reasonable recovery path for accidental data loss; the $12/mo premium over Basic is the right place to spend.

### 4.2 Code changes required

1. Add `psycopg[binary]>=3.2` to `pyproject.toml`.
2. `config.py`: read `DATABASE_URL` from env. Local default = `sqlite:///./data/cvp.db`. Render injects the production Postgres URL.
3. `db.py`: WAL PRAGMA fires only when the URL starts with `sqlite://`. Connection pool size 5–10 for Postgres.
4. Audit models for type-strictness issues:
   - **Booleans** — `Boolean` type works on both. ✓
   - **JSON columns** — use `sqlalchemy.JSON` (auto-picks JSONB on Postgres, TEXT on SQLite). Verify no raw SQL assumes one dialect.
   - **Datetime** — already TZ-aware UTC. ✓
   - **Money** — already integer cents. ✓
5. Scan `migrations/versions/` for SQLite-specific raw SQL or constructs (e.g., `INTEGER PRIMARY KEY AUTOINCREMENT`). Fix any with per-dialect branches or pure SQLAlchemy Core. **This is the most likely source of first-deploy surprises.**

### 4.3 Data migration

**No data migration.** On first production deploy, the Postgres DB is empty and the pre-deploy command runs:

```
uv run alembic upgrade head && uv run seed && uv run bootstrap-admin
```

`alembic upgrade head` creates the schema, `uv run seed` populates the 42 category rows (must remain idempotent — already true per CLAUDE.md), and `bootstrap-admin` creates the initial admin user from env vars. Local SQLite databases are not migrated; they remain a dev-only artifact.

Implementation must verify that `uv run seed` is genuinely idempotent against Postgres (existing rows untouched, new rows added). If the existing implementation uses an INSERT pattern that fails on duplicate keys, switch to UPSERT (`ON CONFLICT DO NOTHING`) before this command goes into the pre-deploy hook.

### 4.4 Tests

Tests continue to run on SQLite for speed. A small `tests/integration/test_postgres_smoke.py` runs against a local Postgres if available, gated behind `pytest -m postgres` so the default `uv run pytest` stays fast.

### 4.5 Risk note

SQLite was permissive with implicit type coercion; Postgres is strict. The first production deploy may surface 1–3 latent type bugs (`str` passed where `Integer` expected, etc.). Budget half a day after first deploy to chase these.

---

## 5. Secrets, Environment, and Admin Bootstrap

### 5.1 Environment variables

**Render-injected (do not set manually):**

| Var | Source |
|---|---|
| `DATABASE_URL` | Render Postgres link |
| `PORT` | Render web service |

**Operator-set (Render dashboard, Secret type):**

| Var | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Vision API |
| `SECRET_KEY` | Session/CSRF signing — generate fresh, 64 random bytes |
| `INITIAL_ADMIN_EMAIL` | Bootstrap admin (used once, then removed) |
| `INITIAL_ADMIN_PASSWORD` | Bootstrap admin (used once, then removed) |
| `APP_BASE_URL` | e.g. `https://cvp.<your-domain>` — used for email links and MFA QR issuer |
| `ENVIRONMENT` | `production` |

### 5.2 Public-repo safety checklist

The repo will eventually be on public GitHub. Before going public:

1. Confirm `.env`, `./data/`, `./backups/` are in `.gitignore`. (Already true per CLAUDE.md.)
2. Add `.env.example` with all keys, empty values, and inline comments.
3. Run `gitleaks detect --source . --redact` over full history. If any matches, scrub with `git filter-repo` before publishing.
4. Enable GitHub secret scanning + push protection on the public repo.
5. Confirm no hardcoded credentials in any seed script.
6. README explicitly warns: never commit `.env`, `./data/`, `./backups/`.

### 5.3 Admin bootstrap

**`bootstrap-admin` script** (extend existing `seed-auth` or add new entry point):

- Reads `INITIAL_ADMIN_EMAIL` and `INITIAL_ADMIN_PASSWORD` from env.
- **If any admin user already exists, logs "bootstrap admin: skipped" and exits 0.** Idempotent.
- Otherwise creates an admin user with the provided credentials, role = admin, MFA disabled (forced enroll on first login).
- Wired into Render's pre-deploy command.

**First-deploy runbook (added to README):**

1. Set `INITIAL_ADMIN_EMAIL` and `INITIAL_ADMIN_PASSWORD` in Render dashboard.
2. Deploy. Pre-deploy runs migrations and bootstraps the admin.
3. Log in, complete MFA enrollment via the existing user-profile flow.
4. Create real admin accounts for any other founders.
5. **Remove `INITIAL_ADMIN_PASSWORD` from Render env vars.** Optionally remove `INITIAL_ADMIN_EMAIL` too.
6. Subsequent deploys see existing admins and skip bootstrap.

**Alternative path documented in README:** for security-conscious deployers, `uv run bootstrap-admin --email x --prompt-password` can be run from the Render Shell tab instead, keeping the password out of env vars entirely. Slightly safer; easier to forget on first deploy.

---

## 6. CI/CD

### 6.1 Branch & deploy flow

```
local feature branch
        │ push
        ▼
GitHub PR
        │
   GitHub Actions:
   - lint   (ruff check + ruff format --check)
   - test   (pytest, SQLite)
   - secrets (gitleaks)
        │ all green + reviewed
        ▼
   merge to main
        │ webhook
        ▼
Render auto-deploy:
   1. docker build
   2. pre-deploy: alembic upgrade head && bootstrap-admin
   3. healthcheck on /healthz
   4. swap traffic
```

### 6.2 GitHub Actions workflow (`.github/workflows/ci.yml`)

Three jobs, run on PRs and pushes to main:

- **`lint`** — `uv sync --frozen --no-dev`, then `uv run ruff check .` and `uv run ruff format --check .`
- **`test`** — same install, then `uv run pytest`. SQLite only.
- **`secrets`** — `gitleaks/gitleaks-action@v2`. Fails on any match.

Add `concurrency: { group: ci-${{ github.ref }}, cancel-in-progress: true }`.

### 6.3 Render configuration

- **Auto-deploy:** on push to `main` only. Feature branches don't deploy.
- **Pre-deploy command:** `uv run alembic upgrade head && uv run seed && uv run bootstrap-admin`. Non-zero exit fails the deploy and traffic stays on the previous version.
- **Healthcheck path:** `/healthz`.
- **Build cache:** Dockerfile copies `pyproject.toml` + `uv.lock` before app code so dependency installs only re-run when deps change.

### 6.4 Branch protection (configure on GitHub once public)

- Require PR before merging to `main`.
- Require all three CI jobs to pass.
- Require at least one approval (or status-checks-only if solo).
- Block force-pushes to `main`.
- Disable direct pushes to `main`.

### 6.5 Rollback posture

- **Code:** Render dashboard → "Rollback to previous deploy" → ~30 sec swap.
- **Schema:** **forward-only, additive migrations only.** No `DROP COLUMN` or destructive renames in a single migration. Renames span three deploys: add new column + backfill + drop old. Documented in `docs/data-model.md`.
- **DB content:** PITR restore is destructive (replaces the whole DB at a point in time). Treat as last resort.

---

## 7. Domain & SSL

- **Hostname:** `cvp.<your-domain>` (subdomain of an existing domain registered through Cloudflare).
- **DNS:** CNAME `cvp` → `<app-name>.onrender.com`, **proxied (orange cloud)**.
- **Cloudflare SSL mode:** **Full (strict)** — CF validates Render's Let's Encrypt cert at origin.
- **Cert issuance gotcha:** if the first ACME challenge stalls, gray-cloud the record briefly, let Render issue, then flip back to orange. Document in deploy runbook.
- **Cache rule:** "Bypass cache" for the entire `cvp.<your-domain>` hostname. This is a stateful authenticated app; CF caching has no value here.

### 7.1 Client IP handling (code change required)

The rate limiter added in `033ae94` reads `request.client.host`. Behind Cloudflare, that returns a Cloudflare IP, which would let any single attacker bypass rate limiting trivially.

**Fix:** read `CF-Connecting-IP` first, fall back to `request.client.host` for local development. Apply in any other code path that uses client IP (audit logging, login attempt tracking).

---

## 8. Disaster Recovery

### 8.1 Recovery sources

| Asset | Recovery path | RTO/RPO |
|---|---|---|
| Application code | GitHub `main` | RTO: ~5 min (re-deploy) |
| Database | Render Postgres PITR | RTO: 5–15 min, RPO: ~0 (any second within 7 days) |
| Evidence images | **None — single point of failure** | Backlogged with R2 |
| Secrets (env vars) | Render dashboard + sealed copy in operator's password manager | RTO: ~5 min |

### 8.2 Disaster runbook (new file: `docs/RUNBOOK.md`)

Three scenarios:

1. **Bad deploy went live** → Render dashboard → Rollback. ~30 sec.
2. **Specialist deleted the wrong matter** → Render Postgres → PITR restore to a moment before the deletion. **Destructive for newer data — coordinate before clicking.**
3. **Render down for hours** → wait per Render SLA; if extended, restore Postgres backup elsewhere and redeploy. Don't pre-build automation; this is rare.

### 8.3 Explicit risk acceptance

Evidence images on a single Render persistent disk have no offsite copy. Disk failure or accidental deletion is unrecoverable until R2 (or equivalent) is wired in. **This risk is accepted for v0** and tracked in `docs/BACKLOG.md`. Re-evaluate before the first paying-client engagement.

---

## 9. CLAUDE.md Updates Required

This hosting move overrides several "immutable" rules in `CLAUDE.md`. The rules must be updated as part of this work, otherwise future agent sessions will revert decisions.

| Current rule | Updated rule |
|---|---|
| Tech stack: "SQLite + SQLAlchemy 2.x + Alembic" | "Postgres in production (Render); SQLite supported for local development. SQLAlchemy 2.x + Alembic." |
| "Do not add: ... Postgres ..." | Remove Postgres from the deny list. |
| Rule 7: "No cloud services beyond the Anthropic API. No S3, no Postgres, no Redis, no Vercel, no Docker. Local filesystem and SQLite." | "Approved cloud services: Anthropic API, Render (web + Postgres + persistent disk), Cloudflare (DNS, registrar, proxy). Not approved without re-discussion: S3/R2, Redis, Vercel, Celery, additional managed services. Docker is approved as the production runtime; local dev still runs on host Python." |
| Rule 6: "No customer-facing auth..." | "No public registration. Attorneys do not log in (PDF/CSV email delivery only). Internal specialists and approved external collaborators authenticate via the existing auth/MFA/RBAC system." |
| Commands section | Add `uv run bootstrap-admin`. |
| Project layout | Add `Dockerfile`, `docs/RUNBOOK.md`, `docs/BACKLOG.md`, `.github/workflows/ci.yml`, `.env.example`. |

The implementation plan must include a "Update CLAUDE.md" task as one of the final steps, after all code changes are in place.

---

## 10. Cost Summary

| Item | Cost |
|---|---|
| Render Web Starter (512 MB) | $7 |
| Render Postgres Standard (PITR) | ~$19 |
| Render Persistent Disk (10 GB) | $2.50 |
| Cloudflare (free plan) | $0 |
| Domain (existing) | $0 incremental |
| **Monthly total** | **~$28.50** |

Verify exact Render pricing at deploy; numbers above reflect publicly-listed tiers as of 2026-04-29.

**Re-budget if:** Web Starter proves too small for PDF rendering (Standard $25 → ~$47 total). Add R2 (~$0.20/mo for 10 GB). Add staging env (~$26/mo). Add offsite backups via B2 (~$1/mo + GitHub Actions minutes).

---

## 11. Implementation Acceptance Criteria

The implementation is complete when:

- [ ] `Dockerfile` builds locally and the resulting image starts the app on `localhost:8000`.
- [ ] `psycopg[binary]>=3.2` added; `config.py` and `db.py` honor `DATABASE_URL`; SQLite still works for local dev.
- [ ] All Alembic migrations apply cleanly against a fresh Postgres database.
- [ ] `uv run seed` is verified idempotent against Postgres (re-running leaves data unchanged).
- [ ] `bootstrap-admin` script exists, reads env vars, idempotent.
- [ ] `GET /healthz` route exists and returns 200 only when DB is reachable.
- [ ] Rate limiter and audit logging read `CF-Connecting-IP` correctly behind a proxy.
- [ ] `.env.example` exists with every required key.
- [ ] `.github/workflows/ci.yml` runs lint, test, and gitleaks; all green on the spec branch.
- [ ] `docs/RUNBOOK.md` exists with the three DR scenarios.
- [ ] `docs/BACKLOG.md` exists with R2 migration entry.
- [ ] `CLAUDE.md` updated per Section 9.
- [ ] First deploy to Render succeeds: pre-deploy migrates schema, bootstraps admin, healthcheck passes.
- [ ] Operator can log in to the production site, complete MFA, and create a second admin account.
- [ ] `INITIAL_ADMIN_PASSWORD` removed from Render env vars after first login.

---

## 12. Backlog (deferred work captured in `docs/BACKLOG.md`)

- **Cloudflare R2 for evidence images** — eliminates the disk single-point-of-failure, gives free egress, ~$0.015/GB/mo storage. Highest-priority backlog item.
- **Offsite database backups** — nightly `pg_dump` to Backblaze B2 via GitHub Actions cron. ~$1/mo storage. Adds belt-and-suspenders to provider PITR.
- **Staging environment** — separate Render service tied to a `staging` branch (~$26/mo).
- **Render PR Preview Environments** (~$7/mo per active PR).
- **Authenticated Origin Pulls** (Cloudflare → Render mTLS) for origin hardening.
- **Browser-based end-to-end tests** via Playwright.
- **PDF rendering memory cap** — paginate large matters at ~100 items per render if Starter tier OOMs.
