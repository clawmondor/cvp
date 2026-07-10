# Slice 3 — Component Classes — Design Spec

**Status:** Approved (brainstorm) — 2026-07-09
**Branch:** `feat/design-components-slice3`
**Parent effort:** `docs/superpowers/specs/2026-07-09-design-system-build-foundation.md` (Slice 3 of 3, final). Slice 2 merged in PR #37.

## Problem / Goal

After Slice 2 the color/type/radius system is fully tokenized. The recurring UI atoms (cards, inputs, buttons, badges) still repeat their whole class bundles inline across templates, so a rebrand that changes *how a component looks* (e.g. button elevation, card radius) means editing many files. Slice 3 extracts the **stable core** of these atoms into `@layer components` classes in `theme.css` (the single rebrand file), composed via `@apply` from Slice-2 tokens, and migrates the template instances that match. Strict visual parity — no normalization.

## Approved principles

- **Core-only:** each component class encodes only the stable core (color / font / radius / shadow / focus). **Size, padding, width, margin, and layout stay inline** — with one documented exception: `.input` includes its padding (`px-3 py-2`), because the dominant input style has uniform padding and is a single coherent atom. Buttons/cards keep padding inline.
- **Exact-core-match migration, never normalize.** An instance is migrated *only* if its class list contains the component's exact core set; that core is replaced by the class and the instance's other utilities stay inline. Instances whose core diverges (e.g. a button using `hover:bg-primary-strong` instead of `-light`) are **left fully inline** — normalizing them would be a visual change, which belongs to the deferred rebrand.
- **Partial coverage is acceptable.** `.card`/`.input`/`.btn-secondary` cover cleanly; `.btn-primary`/badges are fragmented and will cover partially. That is correct and honest.

## Component set (in `theme.css` `@layer components`)

```css
@layer components {
  .card {
    @apply bg-surface shadow-sm rounded-lg;
  }
  .input {
    @apply block rounded-md border border-neutral-300 px-3 py-2 text-sm shadow-xs
           focus:border-primary-light focus:outline-hidden focus:ring-1 focus:ring-primary-light;
  }
  .btn-primary {
    @apply bg-primary text-white font-semibold shadow-sm hover:bg-primary-light;
  }
  .btn-secondary {
    @apply text-neutral-500 hover:text-neutral-700;
  }
  .badge-success {
    @apply inline-flex items-center rounded-full bg-success-surface-strong px-2 py-0.5 text-xs font-medium text-success;
  }
  .badge-error {
    @apply inline-flex items-center rounded-full bg-error-surface-strong px-2 py-0.5 text-xs font-medium text-error;
  }
  .badge-warning {
    @apply inline-flex items-center rounded-full bg-warning-surface-strong px-2 py-0.5 text-xs font-medium text-warning;
  }
}
```

### Per-component core sets (the exact tokens an instance must contain to be migrated)

- **`.card`** — `bg-surface`, `shadow-sm`, `rounded-lg`. (Instances using `sm:rounded-lg` do NOT match — responsive radius differs — leave inline.)
- **`.input`** — `block`, `rounded-md`, `border`, `border-neutral-300`, `px-3`, `py-2`, `text-sm`, `shadow-xs`, `focus:border-primary-light`, `focus:outline-hidden`, `focus:ring-1`, `focus:ring-primary-light`. (The `px-2 py-1`/`rounded-sm`/no-ring input variants do NOT match — leave inline.)
- **`.btn-primary`** — `bg-primary`, `text-white`, `font-semibold`, `shadow-sm`, `hover:bg-primary-light`. (Buttons with `hover:bg-primary-strong`, missing `font-semibold`, or missing `shadow-sm` do NOT match — leave inline.)
- **`.btn-secondary`** — `text-neutral-500`, `hover:text-neutral-700`. Replace just those two color tokens; keep `text-sm` etc. inline. (Skip instances where these appear on a non-interactive element only if it would change meaning — otherwise a ghost-link/button match is fine.)
- **`.badge-{success,error,warning}`** — `inline-flex`, `items-center`, `rounded-full`, `bg-{success/error/warning}-surface-strong`, `px-2`, `py-0.5`, `text-xs`, `font-medium`, `text-{success/error/warning}`. (Count-dot badges like `rounded-full bg-error h-2.5 w-2.5` are a DIFFERENT component — do NOT migrate.)

## Migration mechanics

For each template class attribute: if the class set ⊇ a component's core set (order-independent), remove the core tokens and prepend the component class, preserving all other classes and their order otherwise. Because a match requires ALL core tokens present, divergent instances are automatically skipped. This is **not** a blind find-replace — it is a set-membership match per instance, applied by a script and then reviewed.

Migration covers templates only. `app.js`/`crop-editor.js` inject utility bundles too, but component-class extraction there is out of scope for this slice (the JS bundles are few and dynamic; revisit only if valuable) — the raw-family guard already keeps them token-clean.

## Parity

`@apply` compiles the component class to exactly the utilities it lists, in the `components` layer. An exact-core-match swap therefore produces identical computed styles (utilities layer still wins for the inline size/layout classes, which don't overlap the component core). Verification:
- A build test asserts each component class emits (e.g. `.card`, `.btn-primary` present in `app.css`) and that its declarations include the expected token-derived properties.
- The full pytest suite passes (templates render).
- Manual/scripted spot-check that migrated elements' final class sets are equivalent to pre-migration.

## Guard / tests

- The Slice-2 raw-family guard (`scripts/audit_design_tokens.py`) is unchanged and still passes (component classes use tokens internally; templates still contain only tokens + component classes + layout utilities).
- New: a small test that greps `app.css` for the emitted component selectors.

## Non-goals

- Normalizing fragmented buttons/badges into a single look (rebrand territory).
- Size variants (`.btn-primary-sm/-lg`) — not pursued; size stays inline.
- Extracting nav/admin-sidebar/tabs/modals (single-instance or structural — no repetition payoff).
- JS component-class extraction.
- Any change to token values or the palette (Slice 2 is done).

## Risks

- **Over-extraction / low coverage:** mitigated by the exact-match rule (skip divergent) and the small, high-frequency component set.
- **Specificity/order:** component classes live in the `components` layer (lower precedence than utilities), so inline size/layout utilities still win — safe because component cores and kept-inline classes don't overlap.
- **`@apply` with variant utilities** (`hover:`/`focus:`): supported in v4; the build test confirms emission.
