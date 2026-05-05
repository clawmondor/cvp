# Backlog

Deferred work that has been considered, designed, or scoped but is not yet scheduled. Items here are not committed plans — they're the explicit "we know about this; it is not v0" list. New entries belong here rather than in code comments or scattered TODO markers.

Each item: short title, why it matters, rough cost/effort, and a pointer to the spec or discussion that produced it.

Source for all items: `docs/superpowers/specs/2026-04-29-hosting-design.md` §12.

---

## Hosting & Infrastructure

### Offsite database backups (nightly pg_dump to B2) — ELEVATED PRIORITY

**Why:** Railway Postgres provides daily snapshots only — there is no point-in-time recovery (PITR). RPO is up to 24 hours. A nightly `pg_dump` shipped to Backblaze B2 compresses that window and adds belt-and-suspenders against provider-side failure or accidental project deletion.
**Cost / effort:** ~$1/mo B2 storage + free GitHub Actions minutes. Low effort: one workflow file, one B2 bucket, one rotation policy.
**Trigger to revisit:** immediately after first successful production deploy.
**Source:** spec §1.3.

### Cloudflare R2 for evidence images

**Why:** Evidence images currently live on a Railway persistent volume attached to the web service. This is a disaster-recovery single point of failure — volume loss or accidental deletion is unrecoverable. R2 also offers free egress and lower per-GB cost ($0.015/GB/mo).
**Cost / effort:** ~$0.20/mo for 10 GB storage. Implementation is medium effort: introduce an `EvidenceStorage` service abstraction, swap reads/writes from filesystem to S3-compatible API, migrate existing images, update tests.
**Trigger to revisit:** before the first paying-client engagement, OR when evidence library exceeds 5 GB.

### Staging environment

**Why:** Today, `main` deploys straight to production. A staging service tied to a `staging` branch would let us validate migrations and runtime changes against a Postgres instance before hitting production data.
**Cost / effort:** Low effort to provision on Railway; ongoing effort to keep in sync.

### Railway PR Preview Environments

**Why:** Per-PR ephemeral environment makes review and demo trivial.
**Cost / effort:** Low effort to enable via Railway's preview environments feature.

### Authenticated Origin Pulls (Cloudflare → Railway mTLS)

**Why:** Hardens the Railway origin so only Cloudflare can reach it; defense in depth on top of the proxied DNS setup.
**Cost / effort:** Free on Cloudflare side. Low-moderate effort: client cert provisioning and rotation.

### Browser-based end-to-end tests

**Why:** Current pytest covers unit + light integration. Real-browser coverage via Playwright would catch regressions in HTMX flows that unit tests miss.
**Cost / effort:** Moderate. Adds CI time and maintenance burden.

### PDF rendering memory cap

**Why:** WeasyPrint can spike memory on large matters and cause OOM kills.
**Cost / effort:** Either paginate PDF rendering at ~100 items per pass, or add a resource cap in the Railway service settings. Trigger on memory alert.
