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

**Why:** WeasyPrint can spike memory on large claims and cause OOM kills.
**Cost / effort:** Either paginate PDF rendering at ~100 items per pass, or add a resource cap in the Railway service settings. Trigger on memory alert.

---

## User Feedback

### Feedback attachments

**Why:** v0 of the user feedback feature is text-only. Real reports often need a screenshot to be actionable.
**Cost / effort:** Medium. Reuse the existing evidence-file upload pattern (filesystem under `./data/`, MIME validation, size cap). Allow multiple optional screenshots on the initial feedback submission AND on each thread comment.
**Source:** `docs/superpowers/specs/2026-06-03-user-feedback-design.md`, deferred from v0.

### Apply `assert_plain_text()` to other free-form text inputs

**Why:** The feedback feature ships a reusable plain-text validator in `src/claimos/text_validation.py`. The rest of the app's free-form text inputs do not yet use it. Adopting it project-wide closes a class of stored-XSS issues at the input layer (defense in depth alongside Jinja autoescape and the CSP `script-src` policy).
**Cost / effort:** Low per field, but requires a small per-field audit. Candidate fields: claim name + description, item name + description, room name, profile display name, item comments (`models_comments.Comment.body`), vision model display name, any other free-form `Text`/`String` columns receiving user input. Roll out per-field so each adoption can be reviewed against the field's existing data (e.g., a claim description that already contains `<` would 400 on next edit).
**Source:** `docs/superpowers/specs/2026-06-03-user-feedback-design.md`.

---

## RBAC

### Firm-facing Users page

**Why:** RBAC v2 (`docs/superpowers/specs/2026-07-15-rbac-v2-granular-permissions-design.md`) added the granular grant model (`role_grants` / `role_grant_claims` / `role_grant_overrides`) but deliberately shipped only minimal plumbing bolted onto the existing `/admin/org` panel — enough to assign a User Role, pick a scope, add overrides, and list/edit/revoke a member's grants, with no new visual design work. Lawyers and Paralegals managing their own firm's users deserve a dedicated, polished screen instead of the reused internal-admin-style org panel: user CRUD, role assignment, a scope picker (group-wide vs. specific claims), and — importantly — a proper **per-object override editor UI** (the override mechanism exists in the model and is enforced by the resolver, but this slice has no purpose-built UI for it beyond whatever minimal form the org panel plumbing exposes).
**Cost / effort:** Medium-high. Needs its own spec, its own plan, and a `@DESIGN.md` pass (new screen, not a reskin) before implementation. Replaces the `/admin/org` grant screens for external_admin users only; internal admin panels are unaffected.
**Trigger to revisit:** before onboarding a firm large enough that Lawyers/Paralegals are managing grants for more than a handful of users through the current bolted-on panel.
**Source:** `docs/superpowers/specs/2026-07-15-rbac-v2-granular-permissions-design.md` §8, §12.

### Fold internal users into RBAC v2

**Why:** RBAC v2 is external-users-only by design; internal users (`system_admin`, `internal_admin`, `internal_user`, `specialist`) still resolve claim access through the legacy single-role `claim_access` table, so ClaimOS currently runs two parallel claim-access models. Unifying onto one model removes that duplication, and would let internal roles get the same object-level granularity externals have (e.g. a specialist who should upload evidence but not confirm items).
**Cost / effort:** Medium-high. Requires defining an internal User Role registry (or extending the existing one) and a data migration from internal `claim_access` rows onto `role_grants`, analogous to the external migration in alembic revision `c9851834200b` — plus updating every route's `require_claim_role` internal-path assumptions and the admin panels that write `claim_access` today.
**Trigger to revisit:** after the firm-facing Users page ships, or sooner if internal role needs diverge enough that the coarse single-role model becomes a real limitation.
**Source:** `docs/superpowers/specs/2026-07-15-rbac-v2-granular-permissions-design.md` §12.
