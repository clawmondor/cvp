# Production Runbook

Operational runbook for the production deployment on Railway. Linked from `docs/superpowers/specs/2026-04-29-hosting-design.md`.

> **Important context (read once):** Railway Postgres provides daily snapshots only — there is no point-in-time recovery. RPO is up to 24 hours. The offsite-`pg_dump` backlog item is the recommended next step after first deploy to compress that window. See spec §1.3 for the full tradeoff rationale.

---

## First-time deployment

1. **Create the Railway project**
   - Railway dashboard → New Project → Deploy from GitHub repo.
   - Pick this repo and the `main` branch.
   - Railway will auto-detect the Dockerfile because `railway.toml` pins `builder = "DOCKERFILE"`. If Railway suggests Nixpacks, something is wrong — check that `railway.toml` is committed and on `main`.

2. **Add Railway Postgres**
   - Inside the project → New → Database → Add Postgres.
   - Once created, Railway exposes a `DATABASE_URL` reference variable on the Postgres service.
   - Go to the web service → Variables → Add Variable Reference → select Postgres' `DATABASE_URL`. This injects the private-network URL at runtime; no manual copy.

3. **Add a persistent volume**
   - Web service → Settings → Volumes → New Volume.
   - Size: 10 GB. Mount path: `/app/data`.
   - Restart the service if Railway doesn't do it automatically.

4. **Set environment variables (web service → Variables)**
   - `ANTHROPIC_API_KEY`
   - `SECRET_KEY` (generate fresh: `python -c "import secrets; print(secrets.token_hex(64))"`)
   - `INITIAL_ADMIN_EMAIL`
   - `INITIAL_ADMIN_PASSWORD`
   - `APP_BASE_URL` (e.g. `https://cvp.your-domain.tld`)
   - `ENVIRONMENT` = `production`
   - (Do NOT manually set `DATABASE_URL` or `PORT` — Railway provides both.)

5. **Confirm service settings**
   - Settings → Deploy → confirm Auto Deploy is enabled and the watched branch is `main`.
   - Settings → Networking → Generate Domain (creates `<service>.up.railway.app`). You'll point Cloudflare at this.
   - Healthcheck path is configured by `railway.toml` (`/healthz`); verify it shows in the UI.
   - Pre-deploy command is configured by `railway.toml`; verify it shows in the UI.

6. **Set a usage alert**
   - Project Settings → Usage → set a monthly cap or alert (e.g. $40/mo). This is the mitigation for the usage-based billing tradeoff documented in spec §1.3.

7. **Configure Cloudflare DNS**
   - Cloudflare dashboard → DNS for your-domain.tld:
     - Add CNAME `cvp` → `<service>.up.railway.app`, **proxied (orange cloud)**.
   - SSL/TLS → Overview → encryption mode: **Full (strict)**.
   - Page Rules / Cache Rules → "Bypass cache" for `cvp.your-domain.tld/*`.
   - In Railway: Settings → Networking → Custom Domain → add `cvp.your-domain.tld`. Railway will issue a cert.
   - If cert issuance stalls (Railway shows "Pending" for >5 min), gray-cloud the CNAME briefly until Railway issues, then re-orange.

8. **First login**
   - Visit `https://cvp.your-domain.tld`.
   - Sign in with the bootstrap admin credentials.
   - Complete MFA setup via the user-profile flow.
   - Create real admin accounts for any other founders.
   - **Remove `INITIAL_ADMIN_PASSWORD` from Railway Variables.**

9. **Set up offsite Postgres backups (recommended, not strictly required for v0)**
   - Tracked in `docs/BACKLOG.md`. Until done, RPO is up to 24 hours.

---

## Disaster recovery

### Scenario 1: Bad deploy went live

1. Railway dashboard → service → Deployments tab.
2. Find the previous successful deployment → ⋯ menu → "Redeploy".
3. ~30 seconds to swap. Healthcheck verifies before traffic moves.

### Scenario 2: Wrong matter deleted (data loss)

**Destructive — Railway snapshots are daily, so up to 24 hours of writes since the snapshot will be lost. Coordinate with the team before clicking. If an offsite `pg_dump` ran more recently than the latest Railway snapshot, prefer the offsite copy.**

1. Railway dashboard → Postgres plugin → Backups tab.
2. Pick the most recent backup before the deletion.
3. Railway's restore flow replaces the database in place. Confirm the project name twice before clicking.
4. After restore: redeploy the web service so connections reset, then verify data integrity.

If the deletion happened very recently (within the same day, before the next snapshot), Railway snapshots will not help. Recovery options in that case:
- Restore from the offsite `pg_dump` if one exists for that day.
- If no offsite copy: data is unrecoverable. Document the loss; this is the gap the offsite-backup backlog item closes.

### Scenario 3: Railway is down (extended)

For outages over a few hours:
1. Pull the most recent offsite `pg_dump` (if backups are wired in).
2. Spin up Postgres on another provider (or local Docker for emergency).
3. Restore the dump and redeploy the container against the temporary database.

Don't pre-build automation for this — it's vanishingly rare. Re-evaluate if it ever happens once.

---

## Routine operations

### Running ad-hoc commands against production

Two paths:
- **Railway CLI:** `railway run --service <web-service-name> <command>` from the operator's terminal (requires `railway login` and project link).
- **Railway Shell** (web): service → ⋯ menu → "Open Shell". Useful when you don't have CLI set up.

### Updating the bootstrap admin password (forgot the password before MFA was set)

1. Set `INITIAL_ADMIN_PASSWORD` to a new value in the web service Variables tab.
2. Run `railway run uv run bootstrap-admin`. **It will skip** because the admin already exists.
3. Better path: use the admin password-reset flow added in commit `001b760` from another admin account.
4. If no other admin exists and the password is lost: open the Railway Postgres plugin → Connect → copy the public connection string, then update the `password_hash` for the user with a SQL client. This is a last-resort manual operation.

### Manually re-running the seed

Pre-deploy already runs it on every deploy; manual re-runs are rarely needed. If required:

```
railway run uv run seed
```

Idempotent; safe to run anytime.
