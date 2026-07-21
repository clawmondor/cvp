# RBAC v2 — Granular, Object-Level Permissions

**Date:** 2026-07-15
**Status:** Design (approved for planning)
**Scope:** External (firm) users only. Internal users unchanged — folding them in is backlogged.

---

## 1. Problem

Today access to a claim is a single role per `(user, claim)` in the `claim_access`
table, on a strict hierarchy `viewer < editor < contributor < manager`. Every route
hardcodes a minimum via `require_claim_role("X")`. This is too coarse:

- A **Photographer** should upload evidence but only *view* items — not edit them.
- Different firm job functions (Adjuster, Claimant, Valuator, Lawyer, Paralegal)
  need different access to different **object types** on the same claim.
- A specific user sometimes needs a one-off bump (e.g. a photographer who also needs
  to edit items) without changing everyone's role.
- Firms need one person to **approve** items while others only contribute.

We want permissions resolved at the **object-type level**, driven by named **User
Roles**, scoped to a **group** with optional narrowing to specific claims, with
per-user **overrides**.

### What we are NOT doing (non-goals)

- **No per-verb permission matrix.** Verb distinctions (upload vs. delete) stay encoded
  as different minimum roles on routes, as they are today. Object-type × role is enough
  — e.g. evidence *delete* is already manager-only in code, so "upload but not remove"
  falls out for free.
- **No change to internal users.** `system_admin`, `internal_admin`, `internal_user`,
  and `specialist` keep today's model. Folding them into this system is a later slice
  (see §12).
- **No dedicated firm-facing Users page in this slice.** This spec adds the *model* plus
  minimal plumbing in the existing `/admin/org` panel so grants are creatable/testable.
  The polished Users page is the next slice (§12).
- **No admin-editable role definitions.** The six User Roles are a fixed, code-defined
  registry (like `depreciation.py`). A DB-backed editable registry is deferred (YAGNI).

---

## 2. Concepts

### User Role (fixed registry — `src/claimos/roles.py`)

A named bundle of a `system_role` plus a map of `object_type → claim_role`. Product-
defined and fixed. Some roles map an object to different levels (Photographer is
`contributor` on evidence but `viewer` on items), so a role is a *set* of
`(object_type, claim_role)` entries, not one level.

| User Role | System Role | Object → Claim Role |
|---|---|---|
| **Lawyer** | external_admin | **all** objects → `manager` |
| **Paralegal** | external_admin | **all** objects → `manager` |
| **Adjuster** | external_user | `approver` on users, items, evidence, reports, exports, crops, audit_logs, rooms, item_groups |
| **Claimant** | external_user | `viewer` on items, evidence, reports, audit_logs — **single-claim only** |
| **Photographer** | external_user | `contributor` on evidence, comments, rooms, item_groups; `viewer` on items |
| **Valuator** | external_user | `contributor` on items, comments, crops, audit_logs |

**Canonical object types:** `items, evidence, reports, exports, crops, audit_logs,
rooms, item_groups, comments, users`. "all" (Lawyer/Paralegal) means every object type
at `manager`.

Any object type **not** listed for a role → **no access** (default-deny).

### Claim-role hierarchy (adds `approver`)

```
viewer < editor < contributor < approver < manager
```

- `approver` = everything `contributor` can do **plus approve items** (§4).
- The user roles above use `viewer / contributor / approver / manager`. `editor`
  remains in the hierarchy (some item routes require it) but no User Role maps to it
  directly — a role at `contributor` or higher clears the `editor` rung.

### Grant (group-scoped, claim-narrowable)

Replaces the single-role `claim_access` row **for external users**. A grant assigns a
User Role to a user, in the context of their group, either across **all** the group's
claims or a **specific subset**, with optional per-object overrides.

### Override

A per-object bump attached to a grant, e.g. `items → contributor` on a Photographer, or
`items → approver` to make a Valuator an item approver without full manager. Overrides
are the only path to `approver` for a role that doesn't already have it.

---

## 3. Data model

Internal users keep `claim_access` untouched. External users use three new tables.

### `role_grants`
| column | type | notes |
|---|---|---|
| `id` | str (uuid) | pk |
| `user_id` | str fk users.id | grantee (external user) |
| `group_id` | str fk groups.id | the firm context; must equal grantee's group |
| `user_role` | str | registry key: `lawyer`/`paralegal`/`adjuster`/`claimant`/`photographer`/`valuator` |
| `scope` | str | `"group"` or `"claims"` |
| `granted_by_id` | str fk users.id | who granted it |
| `created_at`/`updated_at` | datetime | |

Uniqueness: a user may hold multiple grants (multiple roles), so no unique on
`(user_id, user_role)` is required, but we add one to prevent exact duplicates:
`uq_role_grant (user_id, group_id, user_role, scope)` — narrowing lives in child rows.

### `role_grant_claims`
| column | type | notes |
|---|---|---|
| `grant_id` | str fk role_grants.id (cascade) | |
| `claim_id` | str fk claims.id | |

Present **only** when `scope = "claims"`. A group-scoped grant has none.

### `role_grant_overrides`
| column | type | notes |
|---|---|---|
| `grant_id` | str fk role_grants.id (cascade) | |
| `object_type` | str | one of the canonical object types |
| `role` | str | a claim role at least as high as the base profile for that object |

**Constraints / validation (enforced in the service layer, not just DB):**
- `group_id` must equal the grantee's `group_id` and be an **external** group.
- **Claimant** grants must have `scope = "claims"` with **exactly one** `role_grant_claims`
  row (structurally prevents a claimant reaching a sibling claim).
- A group-scoped grant covers exactly the claims where `claims.owner_group_id == group_id`
  (Option A: **the firm owns its claims**).

---

## 4. Approver / item approval

"Approving" an item today is just toggling the `item.confirmed` flag (with
`confirmed_by_id` / `confirmed_at`), and it currently rides on the **editor**-level item
PATCH (`routers/items.py`). This slice:

1. Removes `confirmed` from the editable fields of the editor-level `PATCH /api/items/{id}`.
2. Adds an approver-gated action (e.g. `POST /api/items/{id}/confirm` and
   `/unconfirm`, or a dedicated form field guarded separately) requiring
   `require_claim_role("approver", "items")`.

**Behavior change:** editors/contributors can no longer confirm items; only `approver`
and above can. This is the intended restriction. No new schema — the existing
`confirmed` fields remain the approval marker.

---

## 5. Resolution algorithm

```
effective_role(user, claim, object_type) -> claim_role | None
```

For an **external** user:

1. Collect all `role_grants` for `user` whose scope covers `claim`:
   - `scope = "group"` and `claim.owner_group_id == grant.group_id`, OR
   - `scope = "claims"` and a `role_grant_claims` row links the grant to `claim`.
2. For each covering grant, look up the base role for `object_type` from the User Role
   registry; then apply any `role_grant_overrides` for that `object_type` (override wins
   if higher).
3. Return the **max** (highest in the hierarchy) across all covering grants, or `None`
   (→ 403) if no grant yields a role for that object type.

Short-circuits (unchanged): `system_admin` → allow; `internal_admin` / `external_admin`
whose group owns the claim → treated as `manager`. Internal `internal_user` /
`specialist` continue to resolve through `claim_access` (their single role applies to
all object types).

`require_claim_role(min_role, object_type)`:

```python
Depends(require_claim_role("contributor", "evidence"))
```

Every existing route is tagged with its object type; its current minimum role is
preserved except for the deltas in §6. `services/access_cache.check_claim_access_cached`
becomes object-aware (cache key includes `object_type`).

---

## 6. Per-object action ladder (route min-roles)

Each action requires a minimum claim role on its object type. Derived from current code;
**deltas** flagged. Membership is enforced by resolution (an object absent from a user's
profile yields `None`), so these rungs only gate *level*.

| Object | Action | Min role | Delta? |
|---|---|---|---|
| items | view | viewer | — |
| items | create | contributor | — |
| items | edit fields | editor | — |
| items | **approve / confirm** | **approver** | **was editor (via PATCH)** |
| items | delete | manager | — |
| evidence | view | viewer | — |
| evidence | upload | contributor | — |
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
| exports | generate / download | **contributor** | **was manager** |
| reports | view | viewer | — |
| reports | generate | contributor | — |
| audit_logs | view | viewer | — (read-only object) |
| users | view list | contributor | — |
| users | grant / revoke roles | manager | — (keeps role mgmt with Lawyers/Paralegals) |

The rooms / item_groups / exports downgrades are required so that Photographer
(`contributor` on rooms/item_groups) and Adjuster (`approver` on exports) can actually
perform their intended actions. Deletes stay at `manager`.

---

## 7. System role

`users.system_role` stays a **global column**, set at invite and **defaulted from the
assigned User Role** (Lawyer/Paralegal → `external_admin`; the rest → `external_user`).
Admin-panel gating is unchanged. This keeps global gating decoupled from per-claim
grants (chosen over deriving it, which would couple global gating to grant state and
leave role-less users undefined).

---

## 8. Minimal `/admin/org` plumbing (this slice)

Extend the existing Org Admin panel (already available to external_admin, scoped to
their group) just enough to make grants usable and testable:

- Assign a **User Role** to an org member.
- Choose **scope**: group-wide, or pick one/more of the group's claims.
- Add per-object **overrides**.
- List / edit / revoke a member's grants.

No new visual design work; reuse existing org-panel templates and patterns. The polished
firm-facing **Users** page is the next slice (§12).

---

## 9. Migration

Alembic migration adds `role_grants`, `role_grant_claims`, `role_grant_overrides`.

Data migration for existing **external** `claim_access` rows → convert each to a
`role_grants` row with `scope = "claims"` (single claim) and a synthesized profile that
grants the old single role uniformly across all object types (preserving current
behavior). A synthetic registry entry / "custom" marker represents "same role on
everything." Internal `claim_access` rows are left untouched. Migration is idempotent
and covered by a test asserting pre/post access parity for a sample external user.

---

## 10. Docs to update

- **`docs/RBAC.md`** — rewrite for the two-layer external model; correct the stale
  "external groups cannot own claims" line (firms **do** own their claims via
  `owner_group_id`); document the object ladder and resolution.
- **`docs/data-model.md`** — the three new tables and their rationale + migration note.
- **`docs/BACKLOG.md`** — add the firm-facing Users page slice and the "fold internal
  users into RBAC v2" item.

---

## 11. Testing

- **Registry** (`roles.py`): unit tests asserting each User Role's object→role map
  matches the table in §2 (near-100%, like depreciation).
- **Resolver**: unit tests for group vs. claims scope coverage, override precedence,
  max-across-grants, default-deny, and the claimant single-claim constraint.
- **Enforcement**: one integration test per object type asserting a representative role
  is allowed/denied at the right rung (photographer uploads evidence ✓ / edits item ✗;
  adjuster approves item ✓; valuator edits item ✓ but can't export ✗; claimant read-only
  and cannot see a sibling claim ✗).
- **Approver**: editor can edit but not confirm; approver can confirm.
- **Migration**: access parity before/after for an existing external grant.
- Update `docs/RBAC.md` test scenarios to the new model.

---

## 12. Follow-up slices (backlog)

1. **Firm-facing Users page** — dedicated management UI (user CRUD, role assignment,
   scope picker, override editor, invite flow) replacing the `/admin/org` screens for
   Lawyers/Paralegals. Its own spec → plan → build with a `@DESIGN.md` pass.
2. **Fold internal users into RBAC v2** — define internal user roles and migrate internal
   `claim_access` onto the grants model for one uniform system.

---

## 13. Open questions / risks

- **`editor` rung usage:** confirm which item routes truly need `editor` vs.
  `contributor` after the confirm split, so no external role is unintentionally blocked.
- **Report vs. export object boundary:** verify which routes are "reports" vs. "exports"
  so the ladder tags them correctly (both currently live near the exports router).
- **Caching:** `check_claim_access_cached` gains `object_type` in its key — verify cache
  invalidation on grant/override changes still holds.
