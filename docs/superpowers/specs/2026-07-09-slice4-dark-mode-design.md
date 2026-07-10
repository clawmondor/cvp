# Slice 4 — Dark / Light Mode — Design Spec

**Status:** Approved (brainstorm) — 2026-07-09
**Branch:** `feat/dark-mode-slice4`
**Parent effort:** `docs/superpowers/specs/2026-07-09-design-system-build-foundation.md`. Slices 1–3 merged (PRs #36/#37/#38). This adds dark mode as a **foundational token-layer capability so every future rebrand inherits light+dark**, before any rebrand happens.

## Goal

Add a dark mode alongside the current (light) UI, driven entirely from the token layer so a rebrand supplies *light and dark* values per token in one file. Users follow their OS by default and can override. **Light mode stays pixel-identical to today** (the regression bar); dark mode is net-new.

## Approved decisions

- **Token strategy:** redefine token *values* per mode; **no template migration** (neutrals are already used role-by-position: low=surface, high=text).
- **Mechanism:** follow OS by default, with a manual override persisted in a cookie and applied **server-side** (no inline script — CSP has no `unsafe-inline` for scripts; no theme flash).
- **CSS:** use the `light-dark()` function so each token is defined once with both values, driven by `color-scheme`. (Fallback if Tailwind `@theme` won't emit it: duplicate the dark block in `.dark` + `@media (prefers-color-scheme: dark) :root:not(.light)`. Prototype this in Task 1 before committing to it.)
- **3-state control:** System / Light / Dark.
- **Report preview forced light** to match the always-light PDF.

## Architecture

### A. Token layer (`theme.css`)

Each mode-varying color token becomes `light-dark(<light>, <dark>)`; light values are exactly today's (parity). Drive it with `color-scheme`:

```css
:root  { color-scheme: light dark; }  /* follow OS */
.light { color-scheme: light; }        /* forced light */
.dark  { color-scheme: dark; }         /* forced dark  */

@theme {
  --color-surface: light-dark(#ffffff, #1a1d23);
  --color-neutral-50: light-dark(#f9fafb, #0f1115);
  --color-neutral-900: light-dark(#111827, #f2f4f7);
  --color-primary: light-dark(#4f46e5, #818cf8);
  /* ...every token below... */
}
```

No `dark:` utility variants; no template changes. `color-scheme` also gives dark form controls/scrollbars for free. The existing `@layer base` border-compat rule already uses `var(--color-neutral-200)`, so it adapts automatically.

**Single-value (mode-independent) tokens:** `white` (#ffffff — literal white for `text-white` on colored buttons, stays white both modes), `black`, and the **`admin-*`** slate ramp (the admin sidebar is already dark chrome in both modes) — these stay plain values, NOT `light-dark()`.

### Reference dark palette (light → dark; tunable)

| Token | light | dark |
|---|---|---|
| primary-subtle | #eef2ff | #1e1b4b |
| primary-tint | #e0e7ff | #312e81 |
| primary-tint-strong | #c7d2fe | #3730a3 |
| primary-light | #6366f1 | #a5b4fc |
| primary | #4f46e5 | #818cf8 |
| primary-strong | #4338ca | #6366f1 |
| neutral-50 | #f9fafb | #0f1115 |
| neutral-100 | #f3f4f6 | #17191e |
| neutral-200 | #e5e7eb | #262932 |
| neutral-300 | #d1d5db | #363a44 |
| neutral-400 | #9ca3af | #6b7280 |
| neutral-500 | #6b7280 | #9aa1ac |
| neutral-600 | #4b5563 | #b6bcc6 |
| neutral-700 | #374151 | #d2d7de |
| neutral-900 | #111827 | #f2f4f7 |
| surface | #ffffff | #1a1d23 |
| success-surface | #f0fdf4 | #052e16 |
| success-surface-strong | #dcfce7 | #14532d |
| success-border | #bbf7d0 | #166534 |
| success-emphasis | #16a34a | #22c55e |
| success | #15803d | #4ade80 |
| success-strong | #166534 | #86efac |
| error-surface | #fef2f2 | #450a0a |
| error-surface-strong | #fee2e2 | #7f1d1d |
| error-border | #fecaca | #991b1b |
| error | #dc2626 | #f87171 |
| error-strong | #b91c1c | #fca5a5 |
| error-strongest | #991b1b | #fecaca |
| warning-surface | #fffbeb | #451a03 |
| warning-surface-strong | #fef3c7 | #78350f |
| warning-border | #fde68a | #92400e |
| warning-emphasis | #d97706 | #f59e0b |
| warning | #b45309 | #fbbf24 |
| warning-strong | #92400e | #fcd34d |

Because both the surface AND text tokens of a component flip together, component classes (`.card`, `.badge-*`, `.btn-primary`, `.input`) adapt correctly with no per-component work — e.g. `.badge-warning` becomes a dark amber tint with light amber text.

### B. Mechanism (server-set, no flash)

- **Cookie `theme`:** `dark` | `light` | absent (= system).
- A FastAPI helper/dependency reads `request.cookies["theme"]` and maps it to `theme_class` (`"dark"` / `"light"` / `""`), injected into template context (a Jinja global or shared-context helper). Base shells set `<html class="{{ theme_class }}">`.
  - cookie present → server renders the class → no flash.
  - absent → no class → `:root { color-scheme: light dark }` follows OS at first paint → no flash.
- **Toggle:** a 3-state control (System / Light / Dark) in the app nav (`base.html`) and admin nav (`admin/base.html`), wired via a `data-theme-*` **delegated listener in `app.js`** (no inline handlers). It sets the `theme` cookie (`document.cookie`, `path=/`, `max-age=1y`, `samesite=lax`; non-sensitive UI pref) and updates `document.documentElement`'s class live (no reload).

### C. Scope

- **Report preview (`report/preview.html`)** is forced **light** (its shell gets `class="light"` regardless of cookie) so it matches the always-light PDF (attorney work product). The **PDF (`pdf.html`)** uses WeasyPrint inline CSS — already isolated, untouched.
- **Admin chrome** (`admin-*`) stays dark slate in both modes; the admin content area adapts. `admin/base.html` still receives `theme_class` for its content.
- Auth / splash / all app pages adapt.

### D. Testing / parity

- **Light-mode regression:** the light value of every `light-dark()` token equals its current hex (a test extracting the first arg and comparing to the Slice-2 table) — proves light mode is unchanged.
- **Dark completeness:** every mode-varying token has a two-arg `light-dark()` (no token forgotten); the single-value set (white/black/admin-*) is explicitly exempt.
- **Cookie→class mapping** (server): TestClient with `theme=dark`/`light`/none → `<html>` class is `dark`/`light`/none.
- **Build health:** `uv run css` builds with `light-dark()` tokens; component selectors still emit.
- Toggle live-update + no-flash: manual/integration spot-check.

## Non-goals

- No template migration; no `dark:` utilities.
- No new semantic surface/text token layer (deferred; the ramp-value approach suffices).
- The PDF report stays light — no dark report.
- No per-user server-stored preference (cookie only; users aren't guaranteed accounts for this pref and it's non-sensitive).
- Tuning the dark palette to perfection — the reference values are a solid starting point and remain tunable (and rebrand-overridable).

## Risks

- **`light-dark()` through Tailwind `@theme`:** must confirm the build emits it and utilities resolve. Task 1 prototypes it first; fallback is the `.dark` + media-query duplication (bulletproof, more verbose).
- **Contrast/accessibility in dark:** reference values chosen for WCAG-ish contrast, but a pass with a contrast checker is advisable before it's called done (flag, not a blocker for the mechanism).
- **Third-party embedded colors** (e.g. any hardcoded hex in templates/JS outside tokens): the Slice-2 guard ensures templates/JS use only tokens, so there should be none — the guard remains the safety net.
