# Slice 2 — Semantic Color Tokens — Design Spec

**Status:** Approved (brainstorm) — 2026-07-09
**Branch:** `feat/design-tokens-slice2`
**Parent effort:** `docs/superpowers/specs/2026-07-09-design-system-build-foundation.md` (Slice 2 of 3). Slice 1 merged in PR #36.

## Problem / Goal

After Slice 1 the app self-builds Tailwind v4, but templates + JS still reference **raw Tailwind shades** (`bg-indigo-600`, `text-gray-500`). Tokens live only in `DESIGN.md` prose. Slice 2 introduces a **semantic color-token layer** in `theme.css` `@theme` and migrates all color utilities onto it, so the color system has a single structural control point (a rebrand edits `theme.css`, not 60 files). Strict visual parity, except one intended change (see §JS fold).

## Naming scheme (approved: hybrid)

Semantic names for accent + status colors; a value **ramp** for neutrals and admin (grays are used across many roles, so a role name like "border-text" would be wrong). Every token's value equals the current Tailwind hex → parity.

### Token set (defined in `@theme`; default Tailwind palette cleared with `--color-*: initial`)

| Token | Hex | (was) |
|---|---|---|
| `primary-subtle` | #eef2ff | indigo-50 |
| `primary-tint` | #e0e7ff | indigo-100 |
| `primary-tint-strong` | #c7d2fe | indigo-200 |
| `primary-light` | #6366f1 | indigo-500 |
| `primary` | #4f46e5 | indigo-600 |
| `primary-strong` | #4338ca | indigo-700 |
| `neutral-50` | #f9fafb | gray-50 |
| `neutral-100` | #f3f4f6 | gray-100 |
| `neutral-200` | #e5e7eb | gray-200 |
| `neutral-300` | #d1d5db | gray-300 |
| `neutral-400` | #9ca3af | gray-400 |
| `neutral-500` | #6b7280 | gray-500 |
| `neutral-600` | #4b5563 | gray-600 |
| `neutral-700` | #374151 | gray-700 |
| `neutral-900` | #111827 | gray-900 |
| `success-surface` | #f0fdf4 | green-50 |
| `success-surface-strong` | #dcfce7 | green-100 |
| `success-border` | #bbf7d0 | green-200 |
| `success-emphasis` | #16a34a | green-600 |
| `success` | #15803d | green-700 |
| `success-strong` | #166534 | green-800 |
| `error-surface` | #fef2f2 | red-50 |
| `error-surface-strong` | #fee2e2 | red-100 |
| `error-border` | #fecaca | red-200 |
| `error` | #dc2626 | red-600 |
| `error-strong` | #b91c1c | red-700 |
| `error-strongest` | #991b1b | red-800 |
| `warning-surface` | #fffbeb | amber-50 |
| `warning-surface-strong` | #fef3c7 | amber-100 |
| `warning-border` | #fde68a | amber-200 |
| `warning-emphasis` | #d97706 | amber-600 |
| `warning` | #b45309 | amber-700 |
| `warning-strong` | #92400e | amber-800 |
| `admin-300` | #cbd5e1 | slate-300 |
| `admin-400` | #94a3b8 | slate-400 |
| `admin-600` | #475569 | slate-600 |
| `admin-700` | #334155 | slate-700 |
| `admin-800` | #1e293b | slate-800 |
| `surface` | #ffffff | white (bg role) |
| `white` | #ffffff | (kept literal for `text-white`/`ring-white`) |
| `black` | #000000 | (kept) |

Keywords `transparent`, `currentColor`, `inherit` remain available.

## Migration map (whole-token, property-preserving)

Applied across **templates AND `src/claimos/static/*.js`** by a scripted substitution (same technique as Slice 1). Format: `<prop>-<shade>` → `<prop>-<token>`, for every property (`bg`/`text`/`border`/`ring`/`divide`/`from`/`to`/`via`/`outline`/`placeholder`).

- indigo: 50→primary-subtle, 100→primary-tint, 200→primary-tint-strong, 500→primary-light, 600→primary, 700→primary-strong
- gray: 50→neutral-50 … 700→neutral-700, 900→neutral-900 (by number)
- green: 50→success-surface, 100→success-surface-strong, 200→success-border, 600→success-emphasis, 700→success, 800→success-strong
- red: 50→error-surface, 100→error-surface-strong, 200→error-border, 600→error, 700→error-strong, 800→error-strongest
- amber: 50→warning-surface, 100→warning-surface-strong, 200→warning-border, 600→warning-emphasis, 700→warning, 800→warning-strong
- slate: 300→admin-300, 400→admin-400, 600→admin-600, 700→admin-700, 800→admin-800
- `bg-white`→`bg-surface`. `text-white`, `ring-white`, `border-white` unchanged.

### JS drift fold (the one intended, already-approved change)

`app.js`/`crop-editor.js` still use pre-#35 drift families (emerald/violet/blue) plus a couple off-ramp shades. Because the default palette is cleared, these must fold onto tokens — applying #35's approved decisions (emerald→success, violet/blue→primary) and snapping off-ramp shades:

- emerald-600 → success-emphasis (emerald→green fold)
- violet-500 → primary-light; violet-600 → primary; violet-700 → primary-strong (violet→primary)
- blue-600 → primary (blue→primary)
- indigo-400 → primary-light (off-ramp snap 400→500)
- red-500 → error (off-ramp snap 500→600)

This is the **only** non-parity change: JS-driven UI (draw-mode toggle, tab indicator, rename input) shifts from purple/emerald/blue to the app's indigo/green — finally matching the templates. It completes the Slice-1 follow-up.

## Type & radius (values tokenized, utilities NOT renamed)

Renaming `text-sm`→a semantic level isn't mechanical (a `text-sm` may be body or label by context). Instead, tokenize the *values* in `@theme` so a rebrand still has one control point:

- `--font-sans`: the current system-sans stack (from DESIGN.md). Templates keep `text-sm`/`font-medium` etc.
- `--radius-sm|md|lg`: current values (0.25rem / 0.375rem / 0.5rem). Templates keep `rounded-sm`/`rounded-md`/`rounded-lg`/`rounded-full`.

No template/JS churn for type or radius in this slice.

## Guard evolution

`scripts/audit_design_tokens.py` is rewritten to an **allowlist** model: it scans `src/claimos/templates/**/*.html` **and** `src/claimos/static/*.js` for color utilities and fails if any utility's color token is not in the allowed set (`primary*`, `neutral-<n>`, `success*`, `error*`, `warning*`, `admin-<n>`, `surface`, `white`, `black`, `transparent`, `current`). Any raw Tailwind family (`gray`/`indigo`/`slate`/`emerald`/`violet`/`blue`/`red`/`green`/`amber`/…) → failure. Cleared palette + guard = drift cannot return, and unknown colors simply don't render (visible in build).

## Parity verification

- A unit test asserts each `@theme` color token's hex equals the Tailwind shade it replaced (the table above).
- Build emits the same rules for renamed utilities; `app.css` contains the token utilities and no raw-family utilities.
- Full pytest suite green; Docker/CI from Slice 1 unchanged. The JS fold is the only visual delta and is expected.

## Non-goals (Slice 3+)

- Component classes (`.btn-primary`, `.card`, `.badge-*`) via `@layer components` — Slice 3.
- Any actual rebrand (changing token *values*) — deferred.
- Semantic *type-level* names (`text-body-sm`) — not pursued (kept on Tailwind's size scale).

## Risks

- **Clearing the default palette** could break a stray raw utility not caught by the map → mitigated by: the migration is exhaustive (guard enforces zero raw families), and the build/render + full suite catch omissions.
- **`neutral` name collision:** Tailwind has a default `neutral` family; we repurpose the name. Because defaults are cleared and we define `--color-neutral-*` ourselves, `neutral-*` unambiguously means our ramp.
- **JS fold visible change:** intended and pre-approved; called out for reviewer awareness so it isn't flagged as a parity regression.
