# Design System Build Foundation — Design Spec

**Status:** Approved (brainstorm) — 2026-07-09
**Branch:** `feat/tailwind-build-foundation`
**Supersedes stack rule:** CLAUDE.md "Tailwind via CDN (no build step)" → Tailwind v4 standalone-CLI build (this spec is the approval + record of that change).

## Problem

The UI is styled with Tailwind loaded via the **Play CDN** (`cdn.tailwindcss.com`), a runtime JIT engine Tailwind labels dev-only. Design "tokens" exist solely as repeated utility strings (`bg-indigo-600` across ~40 templates) — enforced by convention, not structure. This is exactly what caused the color drift addressed in PR #35: the DESIGN.md token layer is documentation, not a control point.

We want a real design **system**: a single source of truth for tokens and component styling, so a rebrand becomes a one-file change and multiple rebrands can be compared side-by-side on branches. This must be built **before** any rebrand, at **strict visual parity** (no UI change today).

## Goals

- Replace the runtime CDN with a proper build producing a static, minified, self-hosted `app.css`.
- No Node/npm: use the Tailwind **v4 standalone CLI binary**.
- Concentrate the entire rebrandable surface into **one theme file** (`theme.css`): `@theme` tokens + `@layer components` classes.
- Migrate templates to reference **semantic tokens** (`bg-primary`) and **component classes** (`.btn-primary`) for the design-system surface (colors/type/radii/shadow + recurring atoms); leave one-off **layout** utilities inline.
- Every step renders **identically** to the current CDN output (visual parity), verifiable.
- Make a rebrand = editing `theme.css` on a branch; `rebrand-a` vs `rebrand-b` = a one-file diff.

## Non-Goals

- **The rebrand itself** (changing token values) — stays deferred. This builds the machinery, does not use it.
- Migrating one-off layout utilities (flex/grid/page-specific padding) to component classes — that is the `@apply`-everything anti-pattern.
- Adding npm, PostCSS, Node, or any second language ecosystem.
- Touching the WeasyPrint print report (`report/pdf.html`) — it uses its own inline CSS and is out of scope.
- A runtime multi-theme selector (build-time `app.<theme>.css` + env selection) — possible future; branches are the chosen mechanism for now.

## Architecture (end state)

```
src/claimos/styles/theme.css     # THE rebrandable surface: @theme tokens + @layer components
src/claimos/static/app.css       # generated, gitignored, served at /static/app.css
bin/tailwindcss                  # pinned standalone binary (gitignored; fetched by script/Docker)
scripts/fetch-tailwind.sh        # fetch+pin the standalone binary locally
scripts/build-css.sh             # wrapper: bin/tailwindcss -i styles/theme.css -o static/app.css
```

- **Build:** Tailwind v4 standalone binary (pinned version). Input `theme.css`, output `app.css`. Content-scans `src/claimos/templates/**/*.html` so only used classes ship.
- **Single source of truth:** `theme.css` holds all tokens (colors, type scale, radii, shadow, spacing) via v4 `@theme`, plus component classes (`.btn-primary`, `.btn-secondary`, `.input`, `.card`, `.badge-success|error|warning`, `.nav`, `.admin-sidebar`, `.tab-*`) via `@layer components`. A rebrand edits only this file.
- **Templates:** semantic tokens + component classes for the design-system surface; layout utilities stay inline.
- **Serving:** `<link rel="stylesheet" href="/static/app.css">` replaces the CDN `<script>` in every shell template (`base.html`, `admin/base.html`, `splash.html`, `login.html`, `login_mfa.html`, `register.html`, `report/preview.html`).

## Slice decomposition

This spec defines the whole architecture; it is implemented as **three independently-mergeable, parity-verified slices**. Each renders identically to the prior state. **The first implementation plan covers Slice 1 only.**

### Slice 1 — Pipeline + parity (first plan)
Stand up the build; achieve identical rendering with **no restyle**. Templates are
touched only by a **pixel-identical, scripted utility rename** (the official Tailwind
v3→v4 renames) — no visual/design change.

- Add `theme.css` importing Tailwind v4 (`@import "tailwindcss";` + `@source` for the
  template globs) and a minimal base compat rule restoring v3's default un-colored
  border color (`gray-200`, since v4 defaults bare `border` to `currentColor`).
- **v4 utility rename in templates (scripted, pixel-identical):** apply the official
  v3→v4 renames for utilities the templates actually use, as whole-token substitutions:
  `outline-none`→`outline-hidden` (76), bare `rounded`→`rounded-sm` (250),
  `rounded-b`→`rounded-b-sm` (1), `shadow-sm`→`shadow-xs` (65), bare `shadow`→`shadow-sm`
  (42), bare `ring`→`ring-3` (9). `rounded-md/lg/full`, `ring-1/2`, and explicit colors are
  unaffected. These renames preserve rendering exactly — they realign class names to v4's
  shifted scales, not the values.
- Add `scripts/fetch-tailwind.sh` (pin a specific v4 version) and `scripts/build-css.sh`.
- Generate `app.css`; swap CDN `<script>` → `<link href="/static/app.css">` in all shell templates listed above.
- **Dev workflow:** keep `uv run dev` as the server; add a `uv run css` script (standalone binary `--watch`). Two processes, documented in README. (Chosen over subprocess-juggling in the Python entrypoint for simplicity.)
- **Docker:** add a build stage that fetches the pinned binary and produces `app.css` before/into the runtime image (Docker-in-prod is already approved; Railway builds via Dockerfile so prod serves self-hosted CSS with no runtime CDN dependency).
- **CI:** add a step that runs `scripts/build-css.sh` — a build-health gate (fails if the build breaks). Nothing is committed, so no freshness check needed.
- **CSP:** remove `https://cdn.tailwindcss.com` from `script-src` and `style-src` in `middleware.py`. Keep `style-src 'unsafe-inline'` **only if** templates still rely on dynamic `style=""` (verify during implementation; drop it too if nothing needs it).
- **.gitignore:** add `src/claimos/static/app.css` and `bin/tailwindcss`.
- **CLAUDE.md:** update the fixed-stack line (CDN → standalone-CLI build) and the commands list (`uv run css`, build script).
- **Parity check:** the only template edits are the deterministic renames above, which are pixel-identical by construction; parity is corroborated by the app rendering without error, the built `app.css` containing the renamed utilities, and no CDN references remaining.
- **Acceptance:** app styled identically with the CDN removed; `uv run dev` + `uv run css` work; Docker image builds and serves `app.css`; CI green; audit guard (from #35) still passes unchanged.

### Slice 2 — Semantic tokens (later plan)
- Populate `@theme` with DESIGN.md's named tokens; migrate **color/type/radius** utilities in templates from raw Tailwind shades (`bg-indigo-600`) to semantic names (`bg-primary`), keeping values identical.
- Evolve `scripts/audit_design_tokens.py` to enforce the **semantic token names** (allowed set becomes `primary/surface/success/...`, not reverse-mapped hexes).
- Parity: values unchanged → identical rendering.

### Slice 3 — Component classes (later plan)
- Define `@layer components` classes for the recurring atoms; migrate templates to use `.btn-primary`, `.card`, `.badge-*`, etc., composed from the Slice-2 tokens.
- Guard checks component-class usage where applicable.
- Parity: identical rendering; the rebrandable surface is now fully concentrated in `theme.css`.

## Rebrand workflow (enabled, not exercised here)

Once Slices 1–3 land: a rebrand = edit `theme.css` (token values and/or component definitions) on a branch. `git checkout -b rebrand-a`, change the theme, build, review; repeat for `rebrand-b`. Reviews are one-file diffs. (A build-time `app.<theme>.css` + env selector remains a possible future enhancement for switching themes without branch changes.)

## Constraints carried from CLAUDE.md

- Python via `uv`/venv; no new managed cloud services. Docker (approved) is where the prod CSS build runs.
- No inline JS event handlers (unaffected — CSS-only change).
- Print report is a separate, untouched context.
- Currency/legal/domain immutables unaffected (no server logic changes).

## Risks

- **v4 default drift breaking parity** — mitigated by the explicit compat pass in Slice 1 + empirical page diffing.
- **Binary supply chain** — pin the version and record its checksum in `fetch-tailwind.sh`; fetch from the official Tailwind GitHub release.
- **Dev friction** (must run `uv run css`) — documented; watch mode makes it low-friction; acceptable for a small team.
- **Migration scope creep (Slices 2–3)** — bounded by "design-system surface only, layout stays inline."
