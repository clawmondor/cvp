# Backlog

Deferred work that has been considered, designed, or scoped but is not yet scheduled. Items here are not committed plans — they're the explicit "we know about this; it is not v0" list. New entries belong here rather than in code comments or scattered TODO markers.

Each item: short title, why it matters, rough cost/effort, and a pointer to the spec or discussion that produced it.

---

## Hosting & Infrastructure

### Move evidence images to Cloudflare R2

**Why:** Evidence images currently live on a single Render persistent disk attached to the web service. This is a disaster-recovery single point of failure — disk loss or accidental deletion is unrecoverable. R2 also offers free egress and lower per-GB cost ($0.015/GB/mo vs $0.25/GB/mo).
**Cost / effort:** ~$0.20/mo for 10 GB storage. Implementation is medium effort: introduce an `EvidenceStorage` service abstraction, swap reads/writes from filesystem to S3-compatible API, migrate existing images, update tests.
**Source:** `docs/superpowers/specs/2026-04-29-hosting-design.md` §1.2, §8.3.
**Trigger to revisit:** before the first paying-client engagement, OR when evidence library exceeds 5 GB.

### Offsite database backups

**Why:** Provider PITR (Render Postgres Standard, 7-day window) is the only recovery path today. A nightly `pg_dump` shipped to Backblaze B2 adds belt-and-suspenders against provider-side failure, account compromise, or accidental project deletion.
**Cost / effort:** ~$1/mo B2 storage + free GitHub Actions minutes. Low effort: one workflow file, one B2 bucket, one rotation policy.
**Source:** `docs/superpowers/specs/2026-04-29-hosting-design.md` §1.2, §8.

### Staging environment

**Why:** Today, `main` deploys straight to production. A staging service tied to a `staging` branch would let us validate migrations and runtime changes against a Postgres instance before hitting production data.
**Cost / effort:** ~$26/mo (web + Postgres mirrors). Low effort to provision; ongoing effort to keep in sync.
**Source:** `docs/superpowers/specs/2026-04-29-hosting-design.md` §6.5.

### Render PR Preview Environments

**Why:** Per-PR ephemeral environment makes review and demo trivial.
**Cost / effort:** ~$7/mo per active PR. Trivial to enable in Render.
**Source:** `docs/superpowers/specs/2026-04-29-hosting-design.md` §1.2.

### Authenticated Origin Pulls (Cloudflare → Render mTLS)

**Why:** Hardens the Render origin so only Cloudflare can reach it; defense in depth on top of the proxied DNS setup.
**Cost / effort:** Free on Cloudflare side. Low-moderate effort: client cert provisioning and rotation.
**Source:** `docs/superpowers/specs/2026-04-29-hosting-design.md` §1.2.

### PDF rendering memory cap

**Why:** WeasyPrint can spike memory on large matters. The Starter web tier (512 MB) may OOM on matters with hundreds of items.
**Cost / effort:** Either upgrade to Standard ($25/mo, +$18) or paginate PDF rendering at ~100 items per pass. Trigger on Render memory alert (>80% sustained).
**Source:** `docs/superpowers/specs/2026-04-29-hosting-design.md` §3.3.

### Browser-based end-to-end tests

**Why:** Current pytest covers unit + light integration. Real-browser coverage via Playwright would catch regressions in HTMX flows that unit tests miss.
**Cost / effort:** Moderate. Adds CI time and maintenance burden.
**Source:** `docs/superpowers/specs/2026-04-29-hosting-design.md` §1.2.
