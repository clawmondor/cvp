---
version: alpha
name: ClaimOS
description: >-
  As-built design system for the ClaimOS internal ops tool. Descriptive, not
  prescriptive: these tokens codify the Tailwind-via-CDN language already in the
  templates so new UI stays consistent. A visual rebrand is a separate, later,
  mockup-driven slice (see CLAUDE.md) — do not introduce new colors, fonts, or
  radii here without that effort.
colors:
  # Interaction / brand (Tailwind indigo) — names match theme.css `@theme`
  primary: "#4f46e5"          # indigo-600 — primary buttons, active states, links
  primary-light: "#6366f1"    # indigo-500 — hover, focus rings, active borders
  primary-strong: "#4338ca"   # indigo-700 — pressed
  primary-subtle: "#eef2ff"   # indigo-50  — tinted backgrounds
  on-primary: "#ffffff"
  # primary tints
  primary-tint: "#e0e7ff"        # indigo-100
  primary-tint-strong: "#c7d2fe" # indigo-200
  # Surfaces & neutral ramp (Tailwind gray)
  surface: "#ffffff"          # cards, nav, panels
  neutral-50: "#f9fafb"       # gray-50  — page background
  neutral-100: "#f3f4f6"      # gray-100 — inset / hover fills
  neutral-200: "#e5e7eb"      # gray-200 — default hairlines, dividers
  neutral-300: "#d1d5db"      # gray-300 — input borders
  neutral-400: "#9ca3af"      # gray-400 — placeholders, disabled
  neutral-500: "#6b7280"      # gray-500 — metadata, captions (most common)
  neutral-600: "#4b5563"      # gray-600 — secondary text
  neutral-700: "#374151"      # gray-700 — secondary heading / dense body text
  neutral-900: "#111827"      # gray-900 — headings, primary text
  # Semantic (Tailwind green / red / amber)
  success: "#15803d"          # green-700
  success-surface: "#f0fdf4"  # green-50
  error: "#dc2626"            # red-600
  error-surface: "#fef2f2"    # red-50
  warning: "#b45309"          # amber-700
  # success ramp
  success-surface-strong: "#dcfce7" # green-100
  success-border: "#bbf7d0"         # green-200
  success-emphasis: "#16a34a"       # green-600 (success icons / hover)
  success-strong: "#166534"         # green-800
  # error ramp
  error-surface-strong: "#fee2e2"   # red-100
  error-border: "#fecaca"           # red-200
  error-strong: "#b91c1c"           # red-700
  error-strongest: "#991b1b"        # red-800
  # warning ramp (amber; yellow is folded in)
  warning-surface: "#fffbeb"        # amber-50  (replaces prior yellow-100 value)
  warning-surface-strong: "#fef3c7" # amber-100
  warning-border: "#fde68a"         # amber-200
  warning-emphasis: "#d97706"       # amber-600
  warning-strong: "#92400e"         # amber-800
  # Admin chrome (dark surface — Tailwind slate)
  admin-800: "#1e293b"        # slate-800 — admin sidebar background
  admin-700: "#334155"        # slate-700 — nav item hover
  admin-300: "#cbd5e1"        # slate-300 — nav item text
  on-admin-surface-strong: "#ffffff"
  # admin chrome extra steps
  admin-400: "#94a3b8"        # slate-400
  admin-600: "#475569"        # slate-600
typography:
  # System sans stack (Tailwind default — no web font is loaded)
  display:
    fontFamily: ui-sans-serif, system-ui, sans-serif
    fontSize: 36px            # text-4xl — hero / marquee numbers
    fontWeight: 700
    lineHeight: 1.05
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: ui-sans-serif, system-ui, sans-serif
    fontSize: 30px            # text-3xl — splash / marquee headings
    fontWeight: 700
    lineHeight: 1.1
    letterSpacing: -0.02em
  headline-md:
    fontFamily: ui-sans-serif, system-ui, sans-serif
    fontSize: 24px            # text-2xl — page headings
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: -0.01em
  title-lg:
    fontFamily: ui-sans-serif, system-ui, sans-serif
    fontSize: 20px            # text-xl — prominent section titles
    fontWeight: 600
    lineHeight: 1.3
  title:
    fontFamily: ui-sans-serif, system-ui, sans-serif
    fontSize: 18px            # text-lg — section / card titles
    fontWeight: 600
    lineHeight: 1.3
  body-md:
    fontFamily: ui-sans-serif, system-ui, sans-serif
    fontSize: 16px            # text-base
    fontWeight: 400
    lineHeight: 1.5
  body-sm:
    fontFamily: ui-sans-serif, system-ui, sans-serif
    fontSize: 14px            # text-sm — the workhorse body/control size
    fontWeight: 400
    lineHeight: 1.5
  label-sm:
    fontFamily: ui-sans-serif, system-ui, sans-serif
    fontSize: 12px            # text-xs — labels, badges, metadata
    fontWeight: 500
    lineHeight: 1
  # Print report only (WeasyPrint PDF) — see Overview "Print report" context
  report-body:
    fontFamily: Arial, Liberation Sans, Helvetica, sans-serif
    fontSize: 11pt
    fontWeight: 400
    lineHeight: 1.4
  report-figure:
    fontFamily: '"Courier New", monospace'
    fontSize: 16pt            # monetary figures are always monospace
    fontWeight: 700
    lineHeight: 1.2
spacing:
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 32px
  container: 80rem            # max-w-7xl — main content column
rounded:
  sm: 4px                     # rounded    — default control radius
  md: 6px                     # rounded-md — buttons, inputs
  lg: 8px                     # rounded-lg — cards, panels
  full: 9999px               # pills, avatars
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    typography: "{typography.body-sm}"
    rounded: "{rounded.md}"
    padding: 6px 12px
  button-primary-hover:
    backgroundColor: "{colors.primary-light}"
  button-secondary:
    # Ghost / text button — secondary actions are text links, not filled
    backgroundColor: transparent
    textColor: "{colors.neutral-500}"
    typography: "{typography.body-sm}"
    padding: 6px 12px
  button-secondary-hover:
    textColor: "{colors.neutral-900}"
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.neutral-900}"
    borderColor: "{colors.neutral-300}"
    rounded: "{rounded.md}"
    padding: 8px 12px
  input-focus:
    borderColor: "{colors.primary-light}"
  card:
    backgroundColor: "{colors.surface}"
    borderColor: "{colors.neutral-200}"
    rounded: "{rounded.lg}"
    padding: 16px
  badge-success:
    backgroundColor: "{colors.success-surface}"
    textColor: "{colors.success}"
    typography: "{typography.label-sm}"
    rounded: "{rounded.full}"
    padding: 2px 8px
  badge-error:
    backgroundColor: "{colors.error-surface}"
    textColor: "{colors.error}"
    typography: "{typography.label-sm}"
    rounded: "{rounded.full}"
    padding: 2px 8px
  badge-warning:
    backgroundColor: "{colors.warning-surface}"
    textColor: "{colors.warning}"
    typography: "{typography.label-sm}"
    rounded: "{rounded.full}"
    padding: 2px 8px
  nav:
    backgroundColor: "{colors.surface}"
    borderColor: "{colors.neutral-200}"
    textColor: "{colors.neutral-900}"
    height: 56px
  admin-sidebar:
    backgroundColor: "{colors.admin-800}"
    textColor: "{colors.admin-300}"
    width: 224px
  admin-sidebar-item-hover:
    backgroundColor: "{colors.admin-700}"
    textColor: "{colors.on-admin-surface-strong}"
---

# ClaimOS Design System

## Overview

ClaimOS is an **internal ops tool**, not a customer-facing product. The people
using it are specialists producing Contents Inventory and Valuation Reports;
attorneys never log in. The interface should feel **calm, dense, and
utilitarian** — a workbench for careful documentation work, not a marketing
surface. Clarity and legibility of data (line items, prices, sources, ACV/RCV
figures) outrank visual flourish.

The system is built with **Tailwind via CDN, no build step, and no custom web
font**. Type therefore uses the platform system-sans stack. All values below are
descriptive of what already ships. A visual rebrand — new theme, layout, brand
chrome — is intentionally deferred to a separate, mockup-driven slice; do not
treat this document as license to invent new colors, fonts, or radii.

There are **three surfaces**, and they are deliberately different:

- **App UI (light)** — the primary surface. Indigo accent on a warm-neutral gray
  ground. This is what the `colors`/`typography`/`components` primary tokens
  describe.
- **Admin chrome (dark)** — the admin area uses a dark `slate` sidebar
  (`admin-*` tokens) with light text. It is a distinct navigational shell,
  not a theme variant of the app UI.
- **Print report (PDF)** — the WeasyPrint-rendered report is its own typographic
  world: **Arial/Helvetica** body and **Courier New** for every monetary figure,
  with print-specific grays. It does not share the web palette or font by design,
  because it is delivered as attorney work product outside the app.

## Colors

The app palette is a single **indigo** interaction color over a **warm-neutral
gray** foundation, plus three semantic accents.

`src/claimos/styles/theme.css` `@theme` is the **structural source of
truth** for these color tokens — it defines the closed token set that Tailwind
compiles into `app.css`. This document mirrors those same tokens (names and
hex values) for humans; if the two ever disagree, `theme.css` wins and this
file should be updated to match.

- **Primary (`#4f46e5`, indigo-600):** the one interaction color — primary
  buttons, links, active states. Hover lifts to `primary-light` (indigo-500),
  pressed drops to `primary-strong` (indigo-700), `primary-subtle` (indigo-50)
  tints selected backgrounds, and `primary-tint`/`primary-tint-strong`
  (indigo-100/200) round out the tint ramp for larger tinted fills and
  borders.
- **Neutrals (gray):** `surface` white for cards and nav; a nine-step
  `neutral-50`…`neutral-900` ramp (gray-50 through gray-900) covers
  backgrounds, hairlines, and text. `neutral-50`/`neutral-100` are page ground
  and inset/hover fills; `neutral-200`/`neutral-300` are default hairlines and
  input borders; `neutral-900` down to `neutral-400` form the text ramp
  (headings to placeholders/disabled), with `neutral-700` for secondary
  headings and dense body text and `neutral-500` — the single most common
  color in the app — for metadata and secondary copy.
- **Semantics:** `success` green, `error` red, `warning` amber, each with a
  full ramp — a tinted `-surface`, a stronger `-surface-strong`, a `-border`
  step, and a darker `-strong` (error also has `-strongest`, success and
  warning also have `-emphasis`) — for badges, banners, and borders at
  different emphasis levels. Warning consolidates onto amber; there is no
  separate yellow token. There is no emerald, violet, or blue accent in the
  palette — those fold into primary (indigo) or the green/red/amber semantics
  above.
- **Admin surface (slate):** the dark sidebar — `admin-800` (slate-800)
  ground, `admin-700` (slate-700) hover, `admin-300` (slate-300) text going to
  white when active, plus two extra chrome steps for secondary use: `admin-400`
  (slate-400) for de-emphasized text and `admin-600` (slate-600) for lighter
  chrome fills.

### Modes (light / dark)

The app supports **light and dark mode** with no template changes: every
mode-varying color token in `theme.css` is a CSS `light-dark(<light>, <dark>)`
value, and `color-scheme` (`:root` = follow OS; `:root.light`/`:root.dark` =
forced) selects which. Because both a component's surface and text tokens flip
together, `.card`/`.input`/`.btn-*`/`.badge-*` adapt automatically. `white`,
`black`, and the `admin-*` chrome ramp are mode-independent single values.

Selection is server-side (no theme flash, CSP-safe): a `theme` cookie
(`dark`/`light`/absent) maps to a `dark`/`light`/`""` class on `<html>` via the
`theme_class` Jinja global; a **System / Light / Dark** control in the nav sets
the cookie and flips the class live. The **report/PDF is always light** (report
preview forces `class="light"`; the PDF is separate). A rebrand supplies both
the light and dark value per token in this one file.

> **Rebranding:** to produce a re-skinned version of the app, edit the token
> values (and optionally the `@layer components` recipes) in
> `src/claimos/styles/theme.css`. Step-by-step instructions are in
> `docs/REBRANDING.md`.

## Typography

System-sans throughout the app; there is no loaded web font. Roughly nine
levels, with **`body-sm` (14px)** as the workhorse for both body copy and
controls, and **`label-sm` (12px)** for metadata and badges. At the top,
**`display` (36px)** is reserved for hero / marquee numbers — the largest
figure on a page — above `headline-lg`/`headline-md`. Headings use tight
tracking at 700 weight (`display`/`headline-lg`/`headline-md`); section and
card titles use `title` (18px) at 600, with **`title-lg` (20px)** available for
more prominent section titles that need to outrank `title` without reaching
headline weight. Only three weights appear in practice: 400, 500 (medium),
600–700 (semibold/bold).

The **print report** deviates on purpose: Arial/Helvetica for prose and
**Courier New (monospace) for all monetary figures**, so dollar amounts align in
columns and read as tabular data.

## Layout

Content sits in a centered column capped at **`max-w-7xl` (80rem)** with
responsive gutters (`px-4 sm:px-6 lg:px-8`) and `py-8` vertical padding. Spacing
follows Tailwind's **4px scale** — `xs`4 / `sm`8 / `md`16 / `lg`24 / `xl`32 —
with 16px (`md`) as the default rhythm between elements. The top nav is a fixed
**56px** bar; the admin sidebar is a **224px** (`w-56`) fixed column.

## Elevation & Depth

The design is **flat**. Depth comes from tonal layering and hairline borders, not
heavy shadows: white cards on a gray-50 ground, `1px` gray-200/300 borders, and
`bg-gray-50`/`bg-gray-100` fills for inset or hover states. The only shadow in
regular use is a subtle `shadow-sm` on primary buttons. Do not reach for larger
drop shadows to establish hierarchy — use surface tone and borders.

## Shapes

A small, consistent radius language: **`md` (6px)** for buttons and inputs,
**`lg` (8px)** for cards and panels, **`sm` (4px)** as the bare default, and
**`full`** for pills, badges, and avatars. Keep radii consistent within a view —
do not mix sharp and heavily-rounded corners.

## Components

> These atoms are now backed by real classes in `src/claimos/styles/theme.css`
> `@layer components` — `.card`, `.input`, `.btn-primary`, `.btn-secondary`, and
> `.badge-success/-error/-warning` — composed via `@apply` from the color tokens.
> Each class carries only the stable core (color/font/radius/shadow/focus); size,
> padding, and layout stay inline (except `.input`, which includes its uniform
> padding). Divergent instances (e.g. buttons with a different hover shade) remain on
> inline utilities by design — the classes are the standardization target for a future
> rebrand, not a forced normalization.

- **Buttons** — Primary is a filled indigo-600 button, white text, `rounded-md`,
  `6px 12px` padding, `shadow-sm`, hover indigo-500. Secondary actions are **ghost
  text links** (gray-500 → gray-900 on hover), not filled buttons. There is no
  outlined-secondary style; don't introduce one.
- **Inputs** — White background, `1px` gray-300 border, `rounded-md`, `8px 12px`
  padding, indigo-500 focus ring.
- **Cards / panels** — White surface, `1px` gray-200 border, `rounded-lg`, `16px`
  padding, no shadow.
- **Badges / status** — Pill-shaped (`rounded-full`), `label-sm` text, on a tinted
  semantic `-surface`: green for success/matched, red for errors/destructive,
  amber for caution/pending.
- **Nav (app)** — White bar, `1px` gray-200 bottom border, 56px tall, semibold
  wordmark left, actions right.
- **Admin sidebar** — Dark slate-800 column, slate-300 links, slate-700 hover
  going to white text.

## Do's and Don'ts

- **Do** use indigo (`primary`) as the single accent — reserve it for the primary
  action and active state. Everything else is neutral gray.
- **Don't** add a second brand/accent hue or introduce new colors, fonts, or radii
  outside the deferred rebrand slice.
- **Do** treat warning as amber (never yellow) and success as green (never
  emerald) — there is no separate info/blue or violet accent; those fold into
  primary.
- **Do** default to `body-sm` (14px) for controls and copy; use `neutral-500`
  (gray-500) for secondary text.
- **Don't** use drop shadows to build hierarchy — layer surfaces and borders
  instead (flat design).
- **Do** keep the print report's Arial + Courier typography — monetary figures are
  always monospace, and the report footer always carries the
  "Confidential — Attorney Work Product" marker.
- **Don't** wire interactivity with inline JS event handlers (`onclick=` etc.).
  The CSP `script-src` has no `unsafe-inline`; use `data-*` attributes with
  delegated listeners in `static/app.js`.
- **Do** format currency to dollars only at the display/export layer — values are
  stored and computed as integer cents.
- **Don't** describe ClaimOS or its output as adjusting, negotiating, representing
  policyholders, or contingency-priced. Copy stays within the flat-fee,
  expert-documentation-vendor framing.
