# Team Management — Firm-Facing User & Privilege Administration

**Date:** 2026-07-16
**Status:** Design (approved for planning)
**Builds on:** RBAC v2 (`docs/superpowers/specs/2026-07-15-rbac-v2-granular-permissions-design.md`)
**Branch:** `rbac-v2-granular-permissions` (develops on the same branch / PR)

---

## 1. Problem

RBAC v2 shipped the permission *model* plus minimal grant plumbing inside the
`/admin/org` panel. External admins (Lawyers/Paralegals) still manage their firm
from the internal **admin area**, they cannot set per-user overrides from the UI,
and they cannot see a user's *effective* permissions or a per-claim access picture.

We want external admins to manage their firm entirely from a **first-class surface
in the main app** — not the `/admin` area — with a left-nav **Team** section. This
is a deliberate step in **migrating external admins off the admin area**.

### Goals

1. A `/team` surface in the main app for external admins, scoped to their own firm.
2. Polished **role assignment** (conditional claim picker, validation).
3. **Per-user override editor** (targeted per-grant overrides).
4. **Group-wide effective-permissions** matrix on the member page.
5. **Per-claim access view** with full resolution + the ability to grant claim access.
6. **Invite with role assignment** (picking a User Role sets the system role + an
   initial grant).
7. Left-nav **Team** section shown **only to external admins**.
8. **Retire** the legacy external claim-access UI; route external admins off
   `/admin/org`.

### Non-goals

- **Internal/system admin management is unchanged.** They keep `/admin/org` (with
  its group selector) for cross-firm management this slice. Unifying that onto
  `/team` is a later concern.
- **User Role definitions stay fixed** (code registry). Admins assign roles and add
  **per-user overrides**; they never edit a role's group-wide privileges.
- **Internal users are unchanged** (legacy `claim_access`).
- No new permission objects or claim-role levels; this is a UI/endpoint slice over
  the existing RBAC v2 model.

---

## 2. Architecture

### Surface & routing

A new router `src/claimos/routers/team.py`, prefix `/team`, registered in
`main.py`. Every route is guarded by a `require_external_admin` dependency:
`user.system_role == "external_admin"` (system_admin may pass through for support,
but with no group selector — it operates on its own `group_id`, which is the
internal group, so in practice this is external-admin-only). All queries are
**hard-scoped to `user.group_id`** (the firm) — no group selector, mirroring the
tenant isolation already enforced in `sharing.py`/`admin/org.py`.

Templates live in `src/claimos/templates/team/`. Read/query helpers that resolve
effective permissions live in a new `src/claimos/services/effective_permissions.py`.
Grant/override write logic extends `src/claimos/services/grants.py`.

### Navigation

`_app_sidebar.html` gains a **Team** section rendered only when
`user.system_role == "external_admin"`:

```
Team
  Members        → /team/users
  Claim Access   → /team/claims
  Firm Settings  → /team/settings
```

`base.html`'s topbar external_admin link (currently → `/admin/org`) is repointed to
`/team`. The `/admin/*` Admin nav section stays path-gated as today (external admins
simply won't be routed there).

### Retiring the admin path for external admins

- `admin/org.py`: add a guard so an `external_admin` hitting any `/admin/org/*`
  route is **redirected to `/team`** (302). Internal/system admins are unaffected.
- The legacy `/admin/org/claims/{id}/access` external-facing grant UI is superseded
  by `/team/claims/{id}/access`; the external POST path is already blocked (RBAC v2
  I1 fix) and this slice removes external admins' route into it entirely.

---

## 3. Pages

### 3.1 Members list — `GET /team/users`

Table of the firm's users (`group_id == user.group_id`): display name, email,
system role, status (active/inactive), a short summary of assigned roles, row link
to detail. An **Invite member** button (→ 3.3).

### 3.2 Member detail — `GET /team/users/{user_id}`

Tenant check: target's `group_id == user.group_id` else 404. Sections:

**a. Identity + lifecycle** — name, email, system role, status; Activate/Deactivate
(reuse existing behavior).

**b. Roles & Access** — the user's grants. Each grant row shows:
- User Role, scope (Group-wide / specific claims + which claims), and its overrides.
- **Override editor (targeted, option A):** an expandable area per grant listing
  current overrides (`object_type → role`) each with a Remove control, plus an
  **Add override** control (object-type select from `OBJECT_TYPES`, role select from
  the hierarchy). Overrides are per-user deviations on *that* grant; the role's
  baseline profile is never edited.
- Revoke control for the whole grant.
- An **Assign a role** form: User Role select, scope (Group-wide / Specific claims),
  and a claim multiselect **revealed only when scope = specific claims** (HTMX). For
  a single-claim role (Claimant) the form requires exactly one claim; violation
  returns an inline 400 message (from `GrantValidationError`).

**c. Group-wide effective permissions** — a read-only matrix: for each of the 10
object types, the resolved claim role from this user's **group-scoped** grants +
their overrides (`None` shown as "—/no access"). This answers "across all the firm's
claims, what can this member do." **Claim-scoped grants are listed separately below
the matrix** ("Also on specific claims: Claimant — Rossi claim") so the matrix stays
unambiguous.

### 3.3 Invite with role — `GET/POST /team/users/invite`

Form: email, display name, **User Role**, scope + claims (same control as 3.2b).
On submit:
1. Create the user with `system_role` derived from the chosen User Role
   (`roles.USER_ROLES[key].system_role`: Lawyer/Paralegal → `external_admin`, others
   → `external_user`), in the admin's group, with an invite code (reuse the existing
   invite mechanics from `admin/org.py`).
2. Create the initial grant via `create_grant` with the chosen scope/claims.
   Single-claim roles (Claimant) require a claim selection here.
3. Show the registration URL (as the org invite flow does today).

### 3.4 Claim access list — `GET /team/claims`

The firm's claims (`owner_group_id == user.group_id`): policyholder/claim label,
status, and a link to each claim's access view (3.5).

### 3.5 Per-claim access — `GET /team/claims/{claim_id}/access`

Tenant check: `claim.owner_group_id == user.group_id` else 404. Shows, for **this
claim**, every firm member with any resolved access, and their **fully-resolved role
per object type** (group + claim-scoped grants + overrides — the real resolver
answer, via `_external_effective_role` per object). Actionable:
- **Grant claim access:** pick a firm member + a User Role → creates a
  **claims-scoped** grant narrowed to this claim (`POST /team/claims/{claim_id}/grant`).
- Each member row links to their member detail (3.2) to adjust.

### 3.6 Firm settings — `GET/POST /team/settings`

Port the existing `/admin/org/profile` org-profile form so external admins can edit
their firm profile without the admin area. (Minimal: reuse the existing fields.)

---

## 4. Endpoints (new)

All guarded by `require_external_admin` + per-target tenant checks.

| Method + path | Purpose |
|---|---|
| `GET /team/users` | Members list (3.1) |
| `GET /team/users/{user_id}` | Member detail (3.2) |
| `GET/POST /team/users/invite` | Invite with role (3.3) |
| `POST /team/users/{user_id}/deactivate` / `/activate` | Lifecycle (reuse logic) |
| `POST /team/users/{user_id}/grants` | Assign a role (wraps `create_grant`) |
| `POST /team/grants/{grant_id}/overrides` | Add override (object_type, role) |
| `POST /team/grants/{grant_id}/overrides/{object_type}/remove` | Remove override |
| `POST /team/grants/{grant_id}/revoke` | Revoke a grant (reuse `revoke_grant`) |
| `GET /team/claims` | Claim access list (3.4) |
| `GET /team/claims/{claim_id}/access` | Per-claim access view (3.5) |
| `POST /team/claims/{claim_id}/grant` | Grant a member claim-scoped access (3.5) |
| `GET/POST /team/settings` | Firm profile (3.6) |

### Service additions

`services/grants.py`:
- `add_override(db, grant_id, object_type, role) -> RoleGrantOverride` — validates
  `object_type ∈ OBJECT_TYPES` and `role ∈ ROLE_HIERARCHY`; upserts (one override
  per (grant, object_type)); invalidates the grantee's cache.
- `remove_override(db, grant_id, object_type) -> None` — deletes if present;
  invalidates cache.

`services/effective_permissions.py` (new, pure read helpers):
- `group_effective_matrix(db, user_id, group_id) -> dict[str, str | None]` — per
  object type, max role over the user's **group-scoped** grants + overrides.
- `claim_effective_matrix(db, current_user, claim_id) -> dict[str, str | None]` —
  per object type via the existing `_external_effective_role` (full resolution).
- `claim_members_access(db, group_id, claim_id) -> list[(user, matrix)]` — every
  firm member with any non-empty resolved access on the claim.

Tenant isolation on every write: load the grant/target user/claim and verify its
`group_id`/`owner_group_id` equals the acting admin's `group_id` before mutating —
identical to the RBAC v2 I1 fix pattern.

---

## 5. Interactivity (CSP-safe)

No inline JS event handlers (CSP blocks them). All interactivity uses `data-*`
attributes + delegated listeners in `src/claimos/static/app.js`, and HTMX for
partial swaps:
- **Conditional claim picker:** scope select toggles the claim multiselect via a
  delegated `change` listener (show/hide) — no server round-trip needed.
- **Add/remove override, revoke, grant:** HTMX POSTs that swap the affected grant
  row / matrix fragment. Endpoints return the refreshed partial.
- Follow the existing delegated-listener pattern already in `app.js`.

---

## 6. Design system

All new templates follow `@DESIGN.md` tokens and reuse the existing org-panel
patterns (cards, tables, form controls, `bg-primary`/`text-neutral-*` etc.). No new
tokens, colors, or radii. The member/claim pages get a light `frontend-design` pass
during implementation for layout polish, staying within the token set. New templates
must pass the design-token guard test.

---

## 7. Testing

- **Tenant isolation (critical):** an external_admin cannot list/view/mutate users,
  grants, overrides, or claims outside their own `group_id` (404/403 before any
  mutation) — one test per write endpoint.
- **Override editor:** add/remove override changes the effective resolution
  (e.g. photographer + `items→contributor` override → can edit items); duplicate
  add upserts; invalid object_type/role → 400.
- **Group-wide effective matrix:** matches `role_for_object` over group-scoped
  grants; claim-scoped grants excluded from the matrix but listed separately.
- **Per-claim view:** resolved roles match `_external_effective_role`; granting
  claim access creates a claims-scoped grant covering only that claim; a claimant
  still can't reach a sibling claim.
- **Invite with role:** sets `system_role` from the role and creates the initial
  grant; single-claim role requires a claim.
- **Nav gating:** Team section renders for external_admin only; not for
  internal/external users or internal_admin.
- **Admin redirect:** external_admin hitting `/admin/org/*` → 302 to `/team`;
  internal/system admin unaffected.

---

## 8. Build order (phases)

1. **Scaffold + nav + read:** `team.py` router, `require_external_admin`, nav Team
   section, Members list (3.1), Member detail read-only (3.2a + grants list + 3.2c
   effective matrix), lifecycle activate/deactivate. Redirect external_admin off
   `/admin/org`.
2. **Role assignment + override editor:** assign-role form + `create_grant` wiring;
   `add_override`/`remove_override` service + endpoints + override editor UI.
3. **Invite with role + Firm settings:** invite-with-role flow; port org profile to
   `/team/settings`.
4. **Per-claim access:** claim list (3.4), per-claim access view (3.5), grant claim
   access.
5. **Retire legacy UI + cleanup:** remove external admins' entry points into
   `/admin/org` legacy claim-access; docs (`RBAC.md`, `BACKLOG.md`) updated.

Each phase produces a working, testable increment.

---

## 9. Docs & backlog

- `docs/RBAC.md` — add a "Team (external admin) surface" section; note external
  admins use `/team`, internal/system admins keep `/admin/org`.
- `docs/BACKLOG.md` — resolve the "firm-facing Users page" item; add follow-ups:
  unify internal/system admin cross-firm management onto a `/team`-style surface;
  fold internal users into RBAC v2 (already tracked).

---

## 10. Open questions / risks

- **system_admin on `/team`:** treat as external-admin-equivalent scoped to its own
  (internal) group, or 403? Proposed: allow but it operates on its own group (a
  no-op for real firms); the real cross-firm tool stays `/admin/org`. Confirm during
  review.
- **Override lower than baseline:** the resolver only lets an override *raise* the
  role. Adding an override ≤ baseline has no effect. Proposed: allow it but show a
  hint ("no effect — below the role's level"); do not hard-error.
- **Effective matrix cost:** the per-claim members view resolves 10 object types per
  member; fine at this scale (a firm has few members/claims), and the access cache
  absorbs repeats.
