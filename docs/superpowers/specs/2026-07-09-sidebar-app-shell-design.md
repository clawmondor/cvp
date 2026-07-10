# Sidebar app shell — layout redesign

**Date:** 2026-07-09
**Branch:** `rebrand-teal` (continues the theme rebrand work)
**Status:** approved design, ready for implementation plan

## Goal

Replace the current top-nav-only application chrome with a persistent **left
sidebar + top bar** layout, inspired by the ClaimOS dashboard mockups. This is a
**layout-only change**: every page keeps its existing content. No feature logic,
data model, exports, depreciation, or legal copy changes.

Non-goals: no new search/notifications features, no collapsible/responsive
sidebar behavior, no changes to the admin shell, no changes to auth pages
(login/register/splash) beyond the `/` routing change described below.

## Requested navigation

The sidebar left navigation has these items and destinations:

| Nav item        | Destination                     |
|-----------------|---------------------------------|
| Dashboard       | `/` (new empty page)            |
| Claims          | `/dashboard` (existing list)    |
| Claim Detail    | `/claims/{claim_id}`            |
| Rooms & Groups  | `/claims/{claim_id}#rooms`      |
| Evidence        | `/claims/{claim_id}#evidence`   |
| Items           | `/claims/{claim_id}#items`      |
| Preview         | `/claims/{claim_id}#preview`    |
| Export          | `/claims/{claim_id}#export`     |

## Approach (chosen)

Promote the existing `admin/base.html` sidebar pattern (top bar → `aside w-56` →
`main`) into the shared app shell `base.html`. This reuses a proven in-repo
layout. All four pages that `extends "base.html"` (dashboard, claim_detail,
claim_new, profile) inherit the new chrome with **no changes to their content
blocks**.

Rejected alternatives:
- **Separate `app_shell.html`, migrate pages one at a time** — leaves two shells
  to maintain; the user wants one consistent layout now.
- **JS-injected sidebar** — violates the no-inline-JS / minimal-JS conventions;
  hacky. Rejected.

## Current-state facts (verified)

- `base.html` is a top-nav-only shell extended by `dashboard.html`,
  `claim_detail.html`, `claim_new.html`, `profile.html`.
- Auth pages (`splash.html`, `login.html`, `register.html`, `login_mfa.html`) do
  **not** extend `base.html`. Admin uses its own `admin/base.html` (already a
  sidebar layout). Neither is touched by this change.
- `claim_detail.html` renders an in-page tab bar using `data-tab` links
  (`href="#overview|#rooms|#evidence|#items|#preview|#export"`) and `data-panel`
  divs. `app.js` `initTabs()` reads `window.location.hash` on load and on
  `hashchange` to show the matching panel. So a link to `/claims/{id}#items`
  opens the Items tab with no new JS.
- `claim_detail` already passes `claim` into its template context; the shell can
  detect an active claim via `{% if claim %}` — no router changes needed for the
  claim-scoped nav group.
- Routes pass `user` explicitly into template context; `base.html` uses `user`.
- `optional_user` dependency exists at `src/claimos/dependencies.py:144`
  (`CurrentUser | None`).
- The `/` route is currently `splash()` in `routers/auth.py`; in dev with
  `auto_login_user_id` it redirects to `/dashboard`.

## Design

### 1. Shell restructure — `base.html`

Restructure the `<body>` into: top bar, then a flex row of `aside` (sidebar) +
`main`, mirroring `admin/base.html`. Content block (`{% block content %}`) stays
in `main` unchanged.

The sidebar uses **semantic, theme-aware tokens** (not the fixed-navy `admin-*`
tokens):

- Sidebar background: `bg-neutral-100` with `border-r border-neutral-200`
  (light gray `#f1f5f9` in light mode; a slightly-lifted `#12161f` in dark mode,
  distinct from both the page background and the white card surface).
- Section label ("INTELLIGENCE"-style): `text-neutral-400` uppercase caption.
- Nav item (idle): `text-neutral-600 hover:text-neutral-900 hover:bg-neutral-100`.
- Nav item (active): `bg-primary-subtle text-primary`.

Because these tokens are `light-dark()`, the sidebar renders **light in light
mode and dark in dark mode automatically**, matching both reference mockups.

Sidebar is a fixed `w-56`, not collapsible (matches admin; laptop-only internal
tool).

### 2. Sidebar partial — `templates/_app_sidebar.html`

A shared partial included by `base.html`. Two groups:

- **Global group (always visible):**
  - Dashboard → `/`
  - Claims → `/dashboard`
- **Claim-scoped group (rendered only when `claim` is in context):** preceded by
  a section label. Items:
  - Claim Detail → `/claims/{{ claim.id }}`
  - Rooms & Groups → `/claims/{{ claim.id }}#rooms`
  - Evidence → `/claims/{{ claim.id }}#evidence`
  - Items → `/claims/{{ claim.id }}#items`
  - Preview → `/claims/{{ claim.id }}#preview`
  - Export → `/claims/{{ claim.id }}#export`

When no claim is in context, the claim-scoped group is omitted entirely.

**Active-state highlighting (server-side):** compute from `request.url.path`.
- `/` → Dashboard active
- `/dashboard` → Claims active
- `/claims/{id}` (any) → Claim Detail active (the group's parent)

The specific active *tab* (Rooms vs Evidence vs …) continues to be indicated by
the **in-page tab bar**, which is retained. The URL hash is not available
server-side, so the sidebar sub-items are plain links and are not individually
highlighted — no app.js change is made.

### 3. Top bar

In `base.html`, above the sidebar+main row:

- **Left:** breadcrumb `CLAIMOS / <page title>`. Page title comes from a
  `{% block topbar_title %}` (default `"ClaimOS"`), which pages may override; the
  claim detail page sets it to the policyholder/claim label.
- **Right (existing real affordances only):** theme toggle (`_theme_toggle.html`),
  **New claim** button (`/claims/new`), profile/avatar link (`/profile`), Admin
  link (role-gated, same logic as today), Sign out form.
- **Omitted** (not backed by real features): search box, notifications bell,
  "CLAIMANT" badge.

The feedback widget include and `crop-editor-modal-root` div at the bottom of
`base.html` are preserved as-is.

### 4. New Dashboard page

- **New template `templates/home.html`** — extends `base.html`; a genuinely empty
  placeholder: an `<h1>Dashboard</h1>` heading and a short muted note (e.g.
  "Your dashboard is coming soon."). No data.
- **Make `optional_user` dev-auto-login-aware.** `optional_user`
  (`dependencies.py:144`) currently only checks the JWT token, so in dev with
  `AUTO_LOGIN_USER_ID` set it returns `None` — which would make `/` show splash
  instead of the Dashboard. `get_current_user` already handles dev auto-login
  (lines 89–106). Extract that block into a small helper
  `_dev_auto_login_user() -> CurrentUser | None` and call it at the top of **both**
  `get_current_user` and `optional_user`. This is dev-only behavior; it correctly
  makes optional endpoints see the auto-login user in dev, and keeps production
  behavior identical (helper returns `None` when not dev / not configured).
- **`/` route change** (`routers/auth.py` `splash`): depend on `optional_user`.
  If a user is returned → render `home.html` with `{"user": user}`. If `None` →
  render `splash.html`. Remove the old explicit `auto_login` redirect to
  `/dashboard`; dev auto-login now flows through `optional_user` and lands on the
  Dashboard. Rename the handler `splash` → `root` for clarity (route stays `/`).
- `/dashboard` (Claims list) is unchanged.

## Files touched

- `src/claimos/templates/base.html` — restructure to topbar + sidebar + main.
- `src/claimos/templates/_app_sidebar.html` — **new** shared sidebar partial.
- `src/claimos/templates/home.html` — **new** empty Dashboard page.
- `src/claimos/dependencies.py` — extract `_dev_auto_login_user()` helper; call
  it from `get_current_user` and `optional_user`.
- `src/claimos/routers/auth.py` — `/` route (`root`) renders `home.html` for
  authed users (via `optional_user`), splash otherwise.
- `tests/` — new integration test: `/` returns the dashboard for an authed user
  and the splash for an anonymous user.

Not touched: `dashboard.html`, `claim_detail.html`, `claim_new.html`,
`profile.html` content blocks; `app.js`; `theme.css`; admin templates; export /
depreciation / model code.

## Testing & verification

- **New test:** authenticated `GET /` renders the Dashboard placeholder;
  anonymous `GET /` renders splash.
- **Existing tests:** router happy-path tests assert on page content, not chrome,
  so they should keep passing. Any test asserting on removed top-nav markup (e.g.
  the old `<a href="/dashboard">ClaimOS</a>` wordmark) will be updated to the new
  chrome.
- **Design-system guards:** `python scripts/audit_design_tokens.py` must stay
  clean (sidebar uses semantic tokens, no raw Tailwind color families);
  `uv run css` must build cleanly.
- **Manual:** `uv run dev`, toggle System/Light/Dark — confirm the sidebar is
  light in light mode and dark in dark mode; confirm claim-scoped group appears
  only on `/claims/{id}`; confirm sidebar hash links switch tabs; confirm `/`
  shows the Dashboard when logged in.
- `uv run ruff format --check .` + `uv run ruff check .` clean.

## Immutable-rules check

No conflicts. No currency/ACV/source/depreciation/legal/registration/vision/cloud
rules are touched. All UI uses existing design-system tokens (DESIGN.md);
no new colors, fonts, or radii are introduced. No inline JS handlers are added.
