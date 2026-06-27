# CLAIMOS Refactor — Roadmap & Tracker

**Status:** Active · **Branch:** `v2` · **Started:** 2026-06-26

A living tracker for the CLAIMOS-inspired refactor of the Contents Valuation
Platform (CVP). We are **mining the CLAIMOS pitch deck for concepts**, not
building it literally. Each slice below gets its own brainstorm → spec → plan →
build cycle. Check items off as we go; edit freely.

---

## 1. Goal & framing

Pull the genuinely useful concepts out of the CLAIMOS mockups into the real
internal ops tool, without breaking the immutable product rules in
`CLAUDE.md` (internal-only; attorneys/claimants never log in; flat-fee;
attorney work product).

**Explicitly mined-in (the six concepts we endorsed):**

1. Item status & exception workflow (from CLAIMOS *Valuation*)
2. Claim readiness / next-step landing (from *Intake*)
3. AI findings + confidence cards (from *AI Analysis*)
4. Modular report builder (from *Reporting*)
5. Claim activity feed + pending/SLA rollup (from *Audit Trail*)
6. Visual layer: dark "operations console" theme + 7-step sidebar nav +
   persistent claim header + shared status-badge system (cross-cutting)

**Explicitly set aside (do NOT build literally):**

- CLAIMOS *Communication* CRM / Division-of-Labor board with Claimant /
  Attorney / Adjuster as logged-in participants — collides with the
  internal-only rule. Its useful kernel (pending tasks, exceptions, ownership)
  is absorbed by slices for concepts 1 and 5.
- Per-user "hours logged" time-tracking — low ROI for a 1–3 person team and a
  net-new data/maintenance burden.

---

## 2. Branch & deploy model (parallel v2 environment)

Goal: develop the refactor on `v2` with its **own** Railway environment while
`main` stays independently deployable.

Today's deploy model (from `docs/superpowers/specs/2026-04-29-hosting-design.md`):
Railway auto-deploys from `main`; feature branches do not deploy.

### One-time setup checklist

- [x] Create long-lived `v2` branch off `main`
- [ ] Push `v2` to `origin` so Railway can target it
- [ ] **Railway dashboard:** create a new **Environment** (e.g. `v2` / `staging`)
- [ ] In that environment's service settings, set **auto-deploy branch = `v2`**
- [ ] Provision a **separate Postgres** for the v2 environment (do not share the
      production DB — migrations on v2 must not touch prod data)
- [ ] Copy required env vars/secrets into the v2 environment
      (`ANTHROPIC_API_KEY`, auth secrets, admin bootstrap vars, etc. — see
      hosting spec §5.1). Use **distinct** secrets where it matters.
- [ ] Give the v2 environment its own subdomain (e.g. `v2.<domain>` via
      Cloudflare) so it's reachable without touching prod DNS
- [ ] Confirm `preDeployCommand` (alembic upgrade / seed / bootstrap-admin)
      runs cleanly against the v2 Postgres on first deploy
- [ ] Smoke-test: `/healthz` green on the v2 environment

### Working rules for `v2`

- `v2` is a **long-lived integration branch**, not a squash-per-feature branch.
- Each slice is developed on a short feature branch cut **from `v2`**, PR'd, and
  merged **into `v2`** (not `main`).
- Keep migrations **forward-only / additive** (hosting spec §6.5) so `v2` and
  `main` schemas can diverge without destructive renames.
- When the refactor is ready, integrate `v2` → `main` as its own planned event
  (separate decision; not covered by this roadmap yet).

---

## 3. Cross-cutting design decisions (resolve in Slice 0)

These are decided once and reused by every later slice:

- [ ] **Status taxonomy + color system** — the shared vocabulary
      (e.g. New / Needs-doc / Review / Ready / Exception / Blocked) and its
      colors, used by items, evidence, and activity. Single source of truth.
- [ ] **Theme tokens** — dark palette, surfaces, accent colors, typography
      scale. Tailwind-via-CDN config (no build step) — decide how we express
      tokens without a Tailwind build.
- [ ] **Navigation architecture** — does the 7-step sidebar become real routed
      pages, or stay client-side panels like today's `matter_detail.html`?
- [ ] **Where do Rooms & Groups live?** — CLAIMOS has no Rooms nav item; the
      current app does. Decide its home in the new IA.
- [ ] **Light/dark coexistence** — admin panels and auth pages: reskin too, or
      leave on the current light theme during transition?

---

## 4. CLAIMOS nav ↔ current app mapping

| CLAIMOS sidebar step | Current home | Disposition |
| --- | --- | --- |
| 1. Intake | Overview tab (partial) | Slice 1 — new readiness landing |
| 2. Evidence | Evidence tab | Re-home + reskin (Slice 0) |
| 3. AI Analysis | crop editor + vision | Slice 3 — findings cards |
| 4. Valuation | Items tab | Slice 2 — status & exceptions |
| 5. Communication | — | Deferred (see §1) |
| 6. Reporting | Preview + Export tabs | Slice 4 — modular builder |
| 7. Audit Trail | admin audit log (partial) | Slice 5 — in-context feed |
| (Rooms & Groups) | Rooms tab | TBD home (Slice 0 decision) |

---

## 5. Slices

Each slice lifecycle: `brainstorm → spec (docs/superpowers/specs) →
plan (docs/superpowers/plans) → build → review → merge to v2`.

### Slice 0 — Shell & IA (foundation)  ·  Status: Not started

Dark theme, 7-step left-sidebar nav, persistent claim header, shared status-badge
component. Re-homes existing pages with minimal feature change. Unblocks 1–5.

- [ ] Resolve the §3 cross-cutting decisions
- [ ] Theme tokens + base layout (`base.html`, sidebar, claim header)
- [ ] Shared status-badge partial + color taxonomy
- [ ] Re-home Evidence, AI Analysis, Valuation, Reporting onto sidebar
- [ ] Decide Rooms & Groups placement
- [ ] Spec written & committed
- [ ] Plan written & committed
- [ ] Built, reviewed, merged to `v2`

### Slice 1 — Intake / Readiness landing (concept 2)  ·  Status: NEXT — brainstorming

Claim readiness stepper + checklist + "recommended next step," driven by data we
already compute (unconfirmed drafts, items missing pricing, missing docs).

- [ ] Brainstorm into a full design
- [ ] Define the readiness signals + their data sources
- [ ] Define the "recommended next step" logic
- [ ] Spec written & committed
- [ ] Plan written & committed
- [ ] Built, reviewed, merged to `v2`

### Slice 2 — Valuation: item status & exceptions (concept 1)  ·  Status: Not started

Per-item status column, always-visible metrics band (RCV / ACV / priced X-of-Y /
exceptions), and a decision panel (Approve N, Flag exceptions, Request receipts).

- [ ] Brainstorm into a full design
- [ ] Define item status state machine + transitions
- [ ] Define "exception" semantics + where it surfaces
- [ ] Bulk actions (approve / flag / request)
- [ ] Spec / plan / build / review / merge

### Slice 3 — AI Analysis: findings cards (concept 3)  ·  Status: Not started

Surface vision output as confidence-scored cards (item ID, OCR/model, comparable
found, action needed) in the scan-review studio.

- [ ] Brainstorm into a full design
- [ ] Map existing vision/crop output to the card model
- [ ] Confidence + action-needed surfacing
- [ ] Spec / plan / build / review / merge

### Slice 4 — Reporting: modular builder (concept 4)  ·  Status: Not started

Toggle report sections (Claim Summary, Evidence Appendix, Valuation Schedule,
Exception Memo, Audit Workbook) + output selection, vs. today's fixed preview.

- [ ] Brainstorm into a full design
- [ ] Define selectable section catalog (respect existing PDF/CSV invariants)
- [ ] Live preview + export/share affordances
- [ ] Spec / plan / build / review / merge

### Slice 5 — Audit Trail: activity feed + pending/SLA (concept 5)  ·  Status: Not started

Surface the audit log we already store, in-context per matter, plus a pending-work
/ next-deadline rollup. (No per-user hours tracking.)

- [ ] Brainstorm into a full design
- [ ] Reuse existing audit data; define in-context feed query
- [ ] Pending-work + next-deadline rollup
- [ ] Spec / plan / build / review / merge

---

## 6. Open questions

- [ ] Tailwind-via-CDN can't ship a custom config easily — how do we express dark
      theme tokens without adding a build step? (Slice 0)
- [ ] Do admin/auth pages get reskinned in this program or stay light?
- [ ] Final `v2` → `main` integration strategy (deferred until refactor matures).
