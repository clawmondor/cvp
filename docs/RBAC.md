# Role-Based Access Control

This document describes the permission model: system roles (who you are), and — separately for
internal vs. external users — how claim-level access is resolved.

**RBAC v2 (this revision)** replaces the single-role `claim_access` model with granular,
object-level grants **for external (firm) users only**. Internal users
(`system_admin`, `internal_admin`, `internal_user`, `specialist`) are unchanged and continue to
use the legacy single-role `claim_access` table described in "Internal users: `claim_access`"
below. Folding internal users into the grants model is backlogged — see `docs/BACKLOG.md`.

---

## System Roles

Every user has a `system_role` stored on the `users` table. There are six roles.

| Role | Group | Description |
|---|---|---|
| `system_admin` | Internal | Full access to everything. Manages all users, groups, claims, and admin panels. |
| `internal_admin` | Internal | Manages internal users, external organizations, and claim access grants. |
| `internal_user` | Internal | Works on claims. No admin panel access. |
| `specialist` | Internal | Works on claims. No admin panel access. Same access level as `internal_user`. |
| `external_admin` | External | Admin of their own organization (Lawyer/Paralegal). Can invite external users and manage org role grants. |
| `external_user` | External | Works on claims per their User Role grant(s) (Adjuster, Claimant, Photographer, Valuator). |

System roles are set at user creation (via invite), defaulted from the assigned **User Role**
(§"External User Roles" below) for external invites, and can only be changed by a System Admin.

---

## Groups

Users belong to a group. There are two kinds:

- **Internal group** — one per deployment. All `internal_*` and `specialist` roles belong here. Owns claims created internally.
- **External groups** — one per law firm / client organization. All `external_*` roles belong here. **Firms own their claims**: a claim's `owner_group_id` can point to an external group, and that group's role grants (see below) cover exactly the claims it owns.

The `group_kind` field on the `groups` table is either `"internal"` or `"external"`.

---

## External User Roles (RBAC v2)

External access is driven by a fixed, code-defined registry of six **User Roles**
(`src/claimos/roles.py`) — not admin-editable, like `depreciation.py`. Each User Role bundles a
default `system_role` with a map of **canonical object type → claim role**. A role can map
different object types to different levels (e.g. Photographer is `contributor` on evidence but
only `viewer` on items), so a User Role is a *set* of `(object_type, claim_role)` entries, not a
single level.

**Canonical object types:** `items`, `evidence`, `reports`, `exports`, `crops`, `audit_logs`,
`rooms`, `item_groups`, `comments`, `users`.

Any object type **not** listed for a role has **no access** (default-deny) unless bumped by a
per-object override on the grant (see below).

| User Role | System Role | Object → Claim Role |
|---|---|---|
| **Lawyer** | `external_admin` | **all** objects → `manager` |
| **Paralegal** | `external_admin` | **all** objects → `manager` |
| **Adjuster** | `external_user` | `approver` on `users`, `items`, `evidence`, `reports`, `exports`, `crops`, `audit_logs`, `rooms`, `item_groups` |
| **Claimant** | `external_user` | `viewer` on `items`, `evidence`, `reports`, `audit_logs` — **single-claim only** |
| **Photographer** | `external_user` | `contributor` on `evidence`, `comments`, `rooms`, `item_groups`; `viewer` on `items` |
| **Valuator** | `external_user` | `contributor` on `items`, `comments`, `crops`, `audit_logs` |

Notes:
- Lawyer and Paralegal are functionally identical today (both full-manager `external_admin`); they
  are kept as separate registry keys because the firm-facing invite flow and future permission
  splits (see backlog) will likely need to distinguish them.
- Adjuster and Claimant do not have entries for every object type (e.g. neither has `crops` or
  `comments`/`rooms`/`item_groups` in every case) — anything absent from the table is denied.

---

## Claim-Role Hierarchy

```
viewer < editor < contributor < approver < manager
```

RBAC v2 inserts **`approver`** between `contributor` and `manager`. `approver` is everything
`contributor` can do, **plus approving items** (confirming/unconfirming them — see "Item
approval" below). `editor` remains in the hierarchy because some item routes still gate on it
(editing item fields), but no external User Role maps to `editor` directly — any role at
`contributor` or higher already clears the `editor` rung. A dependency check for a given minimum
role passes for any claim role at or above it in this ladder.

| Role | Can do |
|---|---|
| `viewer` | Read items, evidence, comments, reports |
| `editor` | Everything a viewer can do, plus edit item fields (description, price, depreciation overrides) |
| `contributor` | Everything an editor can do, plus upload evidence, create/edit rooms and item groups, generate exports/reports |
| `approver` | Everything a contributor can do, plus approve (confirm/unconfirm) items |
| `manager` | Everything an approver can do, plus delete objects and grant/revoke access to other users |

---

## Grants (external users)

RBAC v2 replaces the single-role `claim_access` row **for external users** with a **grant**: a
User Role assigned to a user, in the context of their group, scoped either to **all** the group's
claims or to a **specific subset**, with optional per-object **overrides**. See
`docs/data-model.md` for the `role_grants` / `role_grant_claims` / `role_grant_overrides` table
definitions.

- **Group scope (`scope = "group"`)** — the grant covers every claim the group owns, i.e. every
  claim where `claims.owner_group_id == grant.group_id`. This is "the group's claims."
- **Claims scope (`scope = "claims"`)** — the grant covers only the specific claims linked via
  `role_grant_claims`.
- **Claimant single-claim rule** — a Claimant grant must always be `scope = "claims"` with
  **exactly one** linked claim. This is enforced structurally (not just by convention), so a
  claimant can never reach a sibling claim through their own grant.
- **Overrides** — a per-object bump attached to a grant, e.g. `items → contributor` on a
  Photographer grant, or `items → approver` to make a Valuator an item approver without full
  manager. An override can only raise a role for that object type, never lower it. Overrides are
  the only path to `approver` for a User Role that doesn't already have it on that object.
- A user may hold **multiple grants** (e.g. multiple roles, or the same role scoped differently);
  effective access is the max across all of them (see resolution algorithm below).

### Resolution algorithm

```
effective_role(user, claim, object_type) -> claim_role | None
```

For an **external** user:

1. Collect every `role_grants` row for the user whose scope covers the claim:
   - `scope = "group"` and `claim.owner_group_id == grant.group_id`, **or**
   - `scope = "claims"` and a `role_grant_claims` row links the grant to the claim.
2. For each covering grant, look up the User Role's base claim role for `object_type`; then apply
   any `role_grant_overrides` row for that grant + `object_type` (the override wins only if it's
   higher than the base role).
3. Return the **max** (highest in the hierarchy) across all covering grants, or `None` (→ 403) if
   no covering grant yields a role for that object type. **Default-deny.**

Short-circuits (checked before the grants resolution, unchanged from v1):
1. `system_admin` → always granted, treated as `manager`.
2. `internal_admin` or `external_admin` whose group owns the claim (`claim.owner_group_id == user.group_id`) → implicitly granted `manager`.

`require_claim_role(minimum_role, object_type)` is the FastAPI dependency each route uses:

```python
Depends(require_claim_role("contributor", "evidence"))
```

Every object-tagged route supplies its object type; routes not yet tagged (`object_type=None`)
fall back to the legacy `claim_access` path, which is also what internal users always use (see
below). `services/access_cache.check_claim_access_cached` is object-aware — its cache key includes
`object_type`.

The dependency also resolves `claim_id` from path parameters automatically. It walks the resource
chain: `claim_id` → `item_id` → `room_id` → `crop_id` → `file_id`.

```
GET /api/claims/{claim_id}/items     → claim_id in path, direct
PATCH /api/items/{item_id}             → item_id → item.claim_id
POST /api/evidence/{file_id}/recrop   → file_id → evidence_file.claim_id
```

---

## Item approval (`approver`)

"Approving" an item is toggling the `item.confirmed` flag (with `confirmed_by_id` /
`confirmed_at`). In RBAC v2 this is split out from general item editing:

- `PATCH /api/items/{item_id}` (editor-level field edits) no longer accepts `confirmed` as an
  editable field.
- `POST /api/items/{item_id}/confirm` and `POST /api/items/{item_id}/unconfirm` are dedicated
  endpoints gated on `require_claim_role("approver", "items")`.

**Behavior change from v1:** editors and contributors can no longer confirm items directly through
the field-edit path; only `approver` and above (Adjuster by profile, Valuator or others via an
`items → approver` override, or any `manager`) can confirm/unconfirm. No new schema — the existing
`confirmed` / `confirmed_by_id` / `confirmed_at` fields remain the approval marker.

---

## Per-Object Action Ladder

Each action requires a minimum claim role on its object type, enforced by `require_claim_role(min_role, object_type)` on the route. Membership (whether a role has *any* access to an object type at all) is enforced by the resolution algorithm above — a role with no entry for an object type gets `None` regardless of this table. These rungs only gate the *level* once membership is established.

| Object | Action | Min role | Delta from v1? |
|---|---|---|---|
| items | view | viewer | — |
| items | create | contributor | — |
| items | edit fields | editor | — |
| items | **approve / confirm / unconfirm** | **approver** | **was reachable via editor-level PATCH; now split out** |
| items | delete / exclude | manager | — |
| evidence | view | viewer | — |
| evidence | upload / Vision scan | contributor | — |
| evidence | delete / manage | manager | — |
| crops | view | viewer | — |
| crops | create / recrop | contributor | — |
| rooms | view | viewer | — |
| rooms | create / edit | **contributor** | **was manager** |
| rooms | delete | manager | — |
| item_groups | view | viewer | — |
| item_groups | create / edit | **contributor** | **was manager** |
| item_groups | delete | manager | — |
| comments | view | viewer | — |
| comments | post | viewer | — |
| reports | preview (on-screen) | viewer | — |
| exports | generate (PDF) / generate (CSV) / download | **contributor** | **was manager (CSV); PDF moved from `reports` to `exports`** |
| audit_logs | view | viewer | — (read-only object) |
| users | view list / sharing | contributor | — |
| users | grant / revoke roles | manager | — (keeps role management with Lawyers/Paralegals) |

The rooms / item_groups / exports downgrades to `contributor` are required so that Photographer
(`contributor` on rooms/item_groups) and Adjuster (`approver` on exports, which clears
`contributor`) can actually perform their intended actions. Deletes stay at `manager` across the
board.

Note: `reports` and `exports` are tagged as distinct object types even though both live in
`routers/exports.py` and `routers/claims.py` — `reports` is the on-screen claim-preview route only
(`claims.py::claim_preview`); generating any downloadable deliverable — PDF export, CSV export, and
file download — is tagged `exports`. PDF generation was previously tagged `reports`; it moved to
`exports` because producing a PDF is an export action, the same class as CSV, not a preview.

---

## Internal users: `claim_access` (unchanged)

Internal users (`system_admin`, `internal_admin`, `internal_user`, `specialist`) do **not** use
role grants. They continue to use the pre-v2 model: a single row per `(user, claim)` in the
`claim_access` table, granting one of `viewer` / `editor` / `contributor` / `manager` (no
`approver` — internal users' single role is checked against the same hierarchy, but nothing
currently grants them a raw `approver` row; `manager`/`system_admin`/owning-group `internal_admin`
already clear the `approver` rung via the hierarchy comparison, so no internal user is blocked from
approving).

Routes not yet tagged with an `object_type` (`object_type=None` in `require_claim_role`) also
resolve through this same legacy `claim_access` path regardless of whether the caller is internal
or external.

### How access is resolved for `claim_access`

1. **system_admin** → always granted, treated as `manager`.
2. **internal_admin or external_admin whose group owns the claim** → implicitly granted `manager`. A claim's `owner_group_id` field determines ownership.
3. **Explicit grant** → look up `claim_access` for the user + claim combination. If found, compare the granted role against the minimum required role using the hierarchy above.
4. **No match** → 403.

---

## Admin Panels

Three admin panels are mounted under `/admin/`. Access is guarded by system role, not claim role.

### System Admin — `/admin/system/`

Accessible only to `system_admin`.

- View all users, create user invites with any system role
- Deactivate / activate users
- Reset a user's MFA
- View all groups, create external groups, deactivate groups
- View all claims
- View, filter, and export the audit log

### Internal Admin — `/admin/internal/`

Accessible to `system_admin` and `internal_admin`.

- Manage internal users (invite, deactivate)
- Manage external groups (create, invite external admins)
- Manage claim access grants (grant/revoke per-user per-claim roles) — internal `claim_access` and,
  for external users, the minimal role-grant plumbing described below

### Org Admin — `/admin/org/`

Accessible to `system_admin`, `internal_admin`, and `external_admin`.

**Group scoping:**
- `external_admin` — always scoped to their own group. No group selector shown.
- `internal_admin` — must pass `?group_id=<id>` to select which external organization to manage. Without it, a group selector is shown.
- `system_admin` — same as internal_admin; must pass `?group_id=<id>`.

Within scope:
- View and invite external users
- View claims shared with (owned by, or shared with) the org
- Assign a **User Role** to an org member, choose scope (group-wide or specific claims), add
  per-object overrides, and list/edit/revoke a member's grants — this slice's minimal plumbing on
  top of the existing org-panel templates (no new visual design). The polished, dedicated
  firm-facing **Users** page is backlogged (see `docs/BACKLOG.md`).
- Update the organization profile

### Team surface (external admins) — `/team`

External admins (and `system_admin`, operating on its own `group_id`) manage their
firm from a first-class surface in the main app, not the admin area. Left nav has a
single top-level **Team** entry that opens `/team`, a combined page showing
**Members** and **Claim Access** as stacked sections (Members first).

- **Members** (`/team` — Members section; `/team/users` redirects to `/team`) —
  list of the firm's users; row link to detail.
  An **Invite member** flow (`/team/users/invite`) picks a **User Role**, which
  sets the invitee's `system_role` (Lawyer/Paralegal → `external_admin`, others →
  `external_user`) and creates their initial grant in one step.
- **Member detail** (`/team/users/{user_id}`) — identity + lifecycle
  (activate/deactivate); the member's grants with **role assignment**
  (group-wide or claim-scoped, with a claim picker shown only when scope is
  "specific claims"); a **per-user per-grant override editor** (add/remove
  `object_type → role` overrides on top of a grant's baseline role); and a
  read-only **group-wide effective-permissions matrix** — the resolved role per
  object type across the user's group-scoped grants, with claim-scoped grants
  listed separately underneath.
- **Claim Access** (`/team` — Claim Access section; `/team/claims` redirects to
  `/team`) — the firm's claims, each linking to a
  **per-claim access view** (`/team/claims/{claim_id}/access`) showing every firm
  member with any access to that claim and their fully-resolved role per object
  type (group + claim-scoped grants + overrides), plus a **grant claim access**
  action (pick a member + User Role → creates a claims-scoped grant for that
  claim).

All `/team` routes are hard-scoped to `user.group_id` (the firm) — no group
selector, ever. External admins are redirected off `/admin/org` to `/team`
(302), **except `/admin/org/profile`**, which remains their firm-profile editor
until the backlogged `/team/settings` ships (see `docs/BACKLOG.md`). Internal and
system admins are unaffected by this redirect and keep using `/admin/org` for
cross-firm management.

---

## Comments Visibility

Comments on items have a `visibility` field:

- `"internal"` — visible only to users with an internal group (`group_kind == "internal"`). External users never see these comments.
- `"shared"` — visible to all users with claim access.

Internal users see a visibility selector when posting. External users always post as `"shared"`.

---

## Invite Flow

New users are created via invite, not self-registration.

1. Admin creates the user via the appropriate admin panel. For external invites, the admin assigns a **User Role** (Lawyer, Paralegal, Adjuster, Claimant, Photographer, Valuator), which defaults `system_role` (Lawyer/Paralegal → `external_admin`; the rest → `external_user`). The user row is written to the DB with `system_role`, `group_id`, `email`, `invite_code` (hashed), and `invite_expires_at = now + 7 days`. No password is set.
2. The admin receives a registration URL: `https://<host>/register/<raw_code>`.
3. The invitee visits the URL, enters a display name and password, and the account becomes active. The invite code is cleared.
4. Invite codes expire after 7 days. Expired codes show an "invalid invite" page.
5. A code cannot be reused once registration is complete (`password_changed_at` is set on completion).

---

## Testing

The scenarios below cover the full RBAC surface, including the RBAC v2 object-level grants. Run
them in a local dev environment with `uv run dev`. Use the System Admin panel (log in as a
`system_admin` user) to set up accounts.

> **Shortcut for local manual testing:** `uv run seed-rbac-demo` creates a ready-made external
> firm with one user per role, two claims, and the matching grants, and prints each user's id for
> `AUTO_LOGIN_USER_ID` (requires `ENVIRONMENT=dev`). See
> [README → Testing RBAC v2 locally](../README.md#testing-rbac-v2-locally). Scenarios 2–7 below
> map directly onto the users it seeds.

### Setup: Seed the required accounts

Before running scenarios, create these users from the System Admin panel at `/admin/system/users`:

| User | System Role | Group |
|---|---|---|
| `sysadmin@test.local` | `system_admin` | Internal |
| `intadmin@test.local` | `internal_admin` | Internal |
| `intuser@test.local` | `internal_user` | Internal |

Create one external group, **Acme Law**, and a second, **Other Firm**, from `/admin/internal/groups`.

From `/admin/org/?group_id=<acme_id>` (or the internal admin equivalent), create these Acme Law users with the given **User Role** (each defaults `system_role` as shown):

| User | User Role | system_role (defaulted) |
|---|---|---|
| `lawyer@acme.test` | Lawyer | `external_admin` |
| `adjuster@acme.test` | Adjuster | `external_user` |
| `claimant@acme.test` | Claimant | `external_user` |
| `photographer@acme.test` | Photographer | `external_user` |
| `valuator@acme.test` | Valuator | `external_user` |

Create one Other Firm user, `otheruser@test.local`, as a Lawyer.

Create two claims owned by Acme Law: **Claim A** and **Claim B** (`owner_group_id` = Acme Law's group id).

---

### Scenario 1: System admin has unrestricted access

1. Log in as `sysadmin@test.local`.
2. Navigate to `/admin/system/` — expect: System Admin panel loads.
3. Navigate to `/admin/internal/` — expect: Internal Admin panel loads.
4. Navigate to `/admin/org/?group_id=<acme_id>` — expect: Org panel for Acme Law loads.
5. Navigate to Claim A — expect: full access, all edit controls visible, can confirm items, can delete rooms.

---

### Scenario 2: Lawyer has manager on every object on the firm's claims

1. Log in as `lawyer@acme.test`.
2. Navigate to Claim A (owned by Acme Law) — expect: full access — create/edit/delete items, rooms, item groups; confirm/unconfirm items; generate and download exports; grant/revoke other Acme users' access.
3. Navigate to Claim B — expect: same full access (grant is group-scoped, covers every claim `owner_group_id == acme_id`).
4. Attempt to access a claim owned by Other Firm — expect: **403**.

---

### Scenario 3: Photographer can upload evidence but cannot edit items

1. Log in as `photographer@acme.test`.
2. Navigate to Claim A — expect: loads; can view items (read-only) and upload evidence.
3. Attempt `POST /api/evidence/{claim_id}` (upload) on Claim A — expect: succeeds (contributor on evidence).
4. Attempt `PATCH /api/items/{item_id}` on an item in Claim A — expect: **403** (viewer-only on items).
5. Attempt to create a room on Claim A — expect: succeeds (contributor on rooms).
6. Attempt to delete a room on Claim A — expect: **403** (delete requires manager).

---

### Scenario 4: Adjuster can approve items

1. Log in as `adjuster@acme.test`.
2. Navigate to Claim A — expect: loads with approver-level access on the Adjuster's 9 objects.
3. Attempt `POST /api/items/{item_id}/confirm` on an item in Claim A — expect: succeeds (approver on items).
4. Attempt `DELETE /api/items/{item_id}` — expect: **403** (delete requires manager; Adjuster tops out at approver).
5. Attempt `POST /api/claims/{claim_id}/exports/csv` — expect: succeeds (approver clears the `contributor` rung on exports).

---

### Scenario 5: Valuator can edit items but cannot export

1. Log in as `valuator@acme.test`.
2. Navigate to Claim A — expect: loads; can edit item fields and crops.
3. Attempt `PATCH /api/items/{item_id}` — expect: succeeds (contributor on items).
4. Attempt `POST /api/items/{item_id}/confirm` — expect: **403** (Valuator is contributor, not approver, on items — no override granted).
5. Attempt `POST /api/claims/{claim_id}/exports/csv` — expect: **403** (Valuator has no grant at all on `exports` — default-deny; `exports` isn't in the Valuator profile).

---

### Scenario 6: Claimant is confined to a single claim, read-only

1. Confirm `claimant@acme.test`'s grant is `scope = "claims"` with exactly Claim A linked.
2. Log in as `claimant@acme.test`.
3. Navigate to Claim A — expect: loads read-only (viewer on items/evidence/reports/audit_logs). No edit controls.
4. Attempt `PATCH /api/items/{item_id}` on Claim A — expect: **403** (viewer cannot edit).
5. Navigate to Claim B (also owned by Acme Law, but not linked to the claimant's grant) — expect: **403**. The claimant's single-claim grant does not extend to a sibling claim even though the same firm owns both.

---

### Scenario 7: Override grants a bump without a full role change

1. As `lawyer@acme.test`, add an override to the Photographer's grant: `items → contributor`.
2. Log in as `photographer@acme.test`.
3. Attempt `PATCH /api/items/{item_id}` on Claim A — expect: succeeds now (override raised `items` from `viewer` to `contributor`).
4. Attempt `POST /api/items/{item_id}/confirm` — expect: still **403** (override only raised to `contributor`, not `approver`).

---

### Scenario 8: Internal admin manages internal `claim_access` (unchanged)

1. Log in as `intadmin@test.local`. Navigate to `/admin/internal/claims/<claim_a_id>/access`.
2. Grant `intuser@test.local` the `contributor` role via `claim_access` (internal users are unaffected by RBAC v2).
3. Revoke the grant.
4. Verify `intuser@test.local` can no longer access Claim A (403).

---

### Scenario 9: External admin invites a user to their org

1. Log in as `lawyer@acme.test`. Navigate to `/admin/org/users`.
2. Invite `newuser@acme.test` with User Role **Valuator**.
3. Copy the invite URL shown.
4. Open the invite URL in a new browser session. Complete registration.
5. Log in as `sysadmin@test.local`. Verify `newuser@acme.test` appears in Acme Law's user list with `system_role = external_user`.
6. Log in as `newuser@acme.test` and confirm they have `contributor` on items/comments/crops/audit_logs on Acme Law's claims, per the Valuator profile.
