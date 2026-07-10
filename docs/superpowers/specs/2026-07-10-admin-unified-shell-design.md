# Admin unified shell — fold admin pages into the app shell

**Date:** 2026-07-10
**Branch:** `rebrand-teal` (same PR #42 as the rebrand + sidebar shell)
**Status:** approved design, ready for implementation plan

## Goal

Make the admin area look and navigate like the rest of the app: the same
`base.html` shell (top bar + left sidebar + main), the same theme-aware tokens,
and the same navigation. Today admin is a parallel universe on its own
`admin/base.html` with dark-slate chrome and a per-page duplicated sidebar.

This is a layout/chrome change. No admin **content**, route, data-model, export,
depreciation, Vision, or legal-copy behavior changes.

Non-goals: no changes to what admin pages *do*; no new admin features; no
removal of the `admin-*` color tokens (left dead for a later purge); no change
to the auth/RBAC that gates admin routes.

## Decisions (from brainstorming)

- **Full unification.** Retire `admin/base.html`; all 26 admin pages extend the
  shared `base.html`.
- **Global links + Admin group.** The sidebar keeps Dashboard (`/`) and Claims
  (`/dashboard`) at the top everywhere; in the admin area it adds an **Admin**
  contextual group (like the existing claim-scoped group).

## Current-state facts (verified)

- 26 templates `{% extends "admin/base.html" %}`: 11 under `system/`, 7 under
  `internal/`, 7 under `org/`, plus `admin/vision_models.html`.
- Each admin page supplies its own `{% block sidebar %}` duplicating a
  role-specific link set:
  - **system_admin:** Dashboard, Users, Groups, Claims, Feedback (unread badge),
    Audit Log, Vision Models, Runtime Config → `/admin/system/*` and
    `/admin/vision-models`.
  - **internal_admin:** Dashboard, Users, Claims, External Groups →
    `/admin/internal/*`.
  - **external_admin (org):** Dashboard, Users, Claims, Profile →
    `/admin/org/*?group_id={{ group.id }}` (carries the `group_id` query param;
    old active state used green `bg-success`).
- Every admin route builds context through a per-router `_ctx()` helper that
  always injects `user` (and `panel_title`, plus per-page `breadcrumbs`,
  `unread_count`, `group`). So migrated pages already have `user` for the
  topbar. Org routes pass `group=group` on all 8 render calls.
- `base.html` (from the prior slice) is: top bar (`CLAIMOS / <topbar_title>`) +
  `aside` including `_app_sidebar.html` + `main`; includes the feedback widget
  when `{% if user %}`.
- `admin/base.html` currently renders: a dark top nav (`panel_title`, user email,
  sign out), an optional `breadcrumbs` bar, a `w-56` dark sidebar with
  `{% block sidebar %}`, and `main`.

## Design

### 1. Retire `admin/base.html`; migrate 26 pages

- Delete `src/claimos/templates/admin/base.html`.
- In each of the 26 admin page templates: change
  `{% extends "admin/base.html" %}` → `{% extends "base.html" %}` and **remove
  the entire `{% block sidebar %}…{% endblock %}`**. Leave `{% block title %}`
  and `{% block content %}` exactly as they are.
- No router changes: `_ctx()` already provides `user`, `panel_title`,
  `breadcrumbs`, `unread_count`, `group`.

### 2. Shared role-aware Admin nav — `_admin_sidebar.html` (new)

A single partial that renders the section links for the current role, using a
local Jinja macro for the item markup to avoid duplicating the class string
across ~14 links. Active state derives from `request.url.path`; active =
`bg-primary-subtle text-primary`, idle = `text-neutral-600 hover:bg-neutral-200
hover:text-neutral-900` (matching `_app_sidebar.html`).

```jinja
{% macro item(href, label, active, badge=0) %}
<a href="{{ href }}"
   class="flex items-center justify-between gap-3 rounded-md px-3 py-2 font-medium
   {% if active %}bg-primary-subtle text-primary
   {% else %}text-neutral-600 hover:bg-neutral-200 hover:text-neutral-900{% endif %}">
  <span>{{ label }}</span>
  {% if badge %}<span class="inline-flex items-center rounded-full bg-error px-1.5 py-0.5 text-xs text-white">{{ badge }}</span>{% endif %}
</a>
{% endmacro %}

{% set p = request.url.path %}
{% if user and user.system_role == 'system_admin' %}
  {{ item('/admin/system/', 'Overview', p == '/admin/system/') }}
  {{ item('/admin/system/users', 'Users', p == '/admin/system/users') }}
  {{ item('/admin/system/groups', 'Groups', p == '/admin/system/groups') }}
  {{ item('/admin/system/claims', 'Claims', p == '/admin/system/claims') }}
  {{ item('/admin/system/feedback', 'Feedback', p == '/admin/system/feedback', unread_count | default(0)) }}
  {{ item('/admin/system/audit', 'Audit Log', p == '/admin/system/audit') }}
  {{ item('/admin/vision-models', 'Vision Models', p == '/admin/vision-models') }}
  {{ item('/admin/system/runtime-config', 'Runtime Config', p == '/admin/system/runtime-config') }}
{% elif user and user.system_role == 'internal_admin' %}
  {{ item('/admin/internal/', 'Overview', p == '/admin/internal/') }}
  {{ item('/admin/internal/users', 'Users', p == '/admin/internal/users') }}
  {{ item('/admin/internal/claims', 'Claims', p == '/admin/internal/claims') }}
  {{ item('/admin/internal/groups', 'External Groups', p == '/admin/internal/groups') }}
{% elif user and user.system_role == 'external_admin' and group %}
  {% set q = '?group_id=' ~ group.id %}
  {{ item('/admin/org/' ~ q, 'Overview', p == '/admin/org/') }}
  {{ item('/admin/org/users' ~ q, 'Users', p == '/admin/org/users') }}
  {{ item('/admin/org/claims' ~ q, 'Claims', p == '/admin/org/claims') }}
  {{ item('/admin/org/profile' ~ q, 'Profile', p == '/admin/org/profile') }}
{% endif %}
```

Notes:
- The section "Overview" link replaces the old "Dashboard" label to avoid two
  "Dashboard" entries in one sidebar (global Dashboard + admin section root).
- Org links are guarded by `and group`; if `group` is somehow absent the group
  renders empty rather than erroring.
- Active state for org ignores the query string (compares `request.url.path`).

### 3. Integrate the Admin group into `_app_sidebar.html`

After the existing global and claim-scoped groups, add:

```jinja
{% if request.url.path.startswith('/admin/') %}
<p class="px-3 pt-5 pb-1 text-xs font-semibold uppercase tracking-wider text-neutral-400">
  Admin
</p>
{% include "_admin_sidebar.html" %}
{% endif %}
```

The Admin group appears only under `/admin/`. Entry point into admin remains the
existing role-gated **Admin** link in the topbar (unchanged).

### 4. Topbar: title default + breadcrumbs in `base.html`

Update the topbar's left cluster so it renders a `breadcrumbs` trail when
present (preserves admin's multi-level trail), else the title; and make the
title block default to `panel_title`:

```jinja
<div class="flex items-center gap-2 text-sm">
  <a href="/" class="font-semibold text-neutral-900">CLAIMOS</a>
  <span class="text-neutral-300">/</span>
  {% if breadcrumbs %}
    {% for crumb in breadcrumbs %}
      {% if not loop.last %}
      <a href="{{ crumb.url }}" class="text-neutral-500 hover:text-neutral-700">{{ crumb.label }}</a>
      <span class="text-neutral-300">/</span>
      {% else %}
      <span class="font-medium text-neutral-600">{{ crumb.label }}</span>
      {% endif %}
    {% endfor %}
  {% else %}
    <span class="font-medium text-neutral-600">{% block topbar_title %}{{ panel_title | default("ClaimOS") }}{% endblock %}</span>
  {% endif %}
</div>
```

App pages don't pass `breadcrumbs` and keep overriding `topbar_title`, so their
topbar is unchanged. Admin pages get their section title (via `panel_title`) and
detail pages get their breadcrumb trail with no per-page edits.

### 5. Token cleanup + DESIGN.md

- `--color-admin-*` tokens become unused after migration. **Leave them defined**
  in `theme.css` (harmless; Tailwind emits only used utilities). Add a one-line
  comment marking them dead pending a later purge. Do not touch
  `tests/test_theme_tokens.py` / `tests/test_dark_mode_tokens.py`.
- Update `DESIGN.md`: replace the "dark slate admin chrome" description with a
  note that admin uses the unified app shell and a role-aware Admin sidebar
  group.

### 6. Consequence: feedback widget in admin

Because `base.html` includes the feedback widget for any `user`, admin pages now
show it too (they didn't before). This is intentional and consistent; no action.

## Files touched

- Delete: `src/claimos/templates/admin/base.html`
- Create: `src/claimos/templates/_admin_sidebar.html`
- Modify: `src/claimos/templates/_app_sidebar.html` (add Admin group)
- Modify: `src/claimos/templates/base.html` (breadcrumbs + title default)
- Modify: 26 admin page templates (extends `base.html`; drop `sidebar` block):
  - `admin/vision_models.html`
  - `admin/system/*.html` (11): audit, claims, dashboard, feedback,
    feedback_detail, feedback_new, group_detail, groups, runtime_config,
    user_detail, users
  - `admin/internal/*.html` (7): claim_access, claims, dashboard, group_detail,
    groups, user_detail, users
  - `admin/org/*.html` (7): claim_access, claims, dashboard, group_selector,
    profile, user_detail, users
- Modify: `src/claimos/styles/theme.css` (dead-token comment only)
- Modify: `DESIGN.md`
- Tests: new `tests/test_admin_shell.py`; update any existing admin test that
  asserts on removed chrome.

Not touched: admin router logic, `_ctx()` helpers, RBAC dependencies, admin page
content blocks, `report/` templates, `app.js`, the app (non-admin) pages.

## Testing & verification

- **New `tests/test_admin_shell.py`** (partial-render, no HTTP/DB — mirrors
  `tests/test_app_shell.py`):
  - `_admin_sidebar.html` with `system_role='system_admin'` renders Users /
    Groups / Claims / Feedback / Audit Log / Vision Models / Runtime Config with
    correct `/admin/system/*` (and `/admin/vision-models`) hrefs.
  - `system_role='internal_admin'` renders the 4 internal links; not the system
    ones.
  - `system_role='external_admin'` with a `group` (id `g1`) renders org links
    carrying `?group_id=g1`.
  - `_app_sidebar.html` includes the **Admin** label + a role link when
    `request.url.path` starts with `/admin/`, and omits the Admin group on `/`
    and `/dashboard`.
  - Feedback badge renders when `unread_count > 0` (system role).
- **Existing admin router tests** (`test_admin_system.py`,
  `test_admin_internal.py`, `test_admin_org.py`, `test_admin_vision_models.py`,
  `test_admin_feedback_router.py`, `test_admin_runtime_config.py`) must keep
  passing. Verified: none of them assert on admin chrome markup (no `bg-admin-*`,
  `panel_title`, breadcrumb, or sidebar-block references) — they check content and
  status — so no test edits are expected. If a page nonetheless fails to render in
  the new shell (e.g. a missing context var the old shell tolerated), fix the
  render, do not weaken the assertion.
- `uv run css` builds cleanly; `python scripts/audit_design_tokens.py` clean
  (only semantic tokens used).
- `uv run ruff format --check .` + `uv run ruff check .` clean.
- **Manual:** log in as each admin role, open its landing page, confirm: same
  topbar + theme-aware sidebar as the app; Dashboard/Claims present; Admin group
  with the role's links and correct active highlighting; System/Light/Dark toggle
  makes the admin sidebar light in light mode / dark in dark mode; org pages keep
  their `group_id` query param.

## Immutable-rules check

No conflicts. Auth/RBAC gating of admin routes is unchanged (this only reskins the
chrome). No currency/ACV/source/depreciation/legal/registration/Vision/cloud rule
is touched. UI uses existing design-system tokens only; no new colors, fonts, or
radii. No inline JS handlers added.
