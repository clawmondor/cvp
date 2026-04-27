# Role-Based Access Control

This document describes the two-tier permission model: system roles (who you are) and matter roles (what you can do to a specific matter).

---

## System Roles

Every user has a `system_role` stored on the `users` table. There are six roles.

| Role | Group | Description |
|---|---|---|
| `system_admin` | Internal | Full access to everything. Manages all users, groups, matters, and admin panels. |
| `internal_admin` | Internal | Manages internal users, external organizations, and matter access grants. |
| `internal_user` | Internal | Works on matters. No admin panel access. |
| `specialist` | Internal | Works on matters. No admin panel access. Same access level as `internal_user`. |
| `external_admin` | External | Admin of their own organization. Can invite external users and manage org matter access. |
| `external_user` | External | Works on matters they have been explicitly granted access to. |

System roles are set at user creation (via invite) and can only be changed by a System Admin.

---

## Groups

Users belong to a group. There are two kinds:

- **Internal group** — one per deployment. All `internal_*` and `specialist` roles belong here. Owns matters.
- **External groups** — one per law firm / client organization. All `external_*` roles belong here. Cannot own matters; they receive shared access.

The `group_kind` field on the `groups` table is either `"internal"` or `"external"`.

---

## Matter Roles

Access to a specific matter is controlled separately from system roles. The `matter_access` table grants a user one of four roles on a matter:

| Role | Can do |
|---|---|
| `viewer` | Read items, evidence, comments |
| `editor` | Everything a viewer can do, plus edit item fields (description, price, depreciation overrides) |
| `contributor` | Everything an editor can do, plus upload evidence and manage evidence files |
| `manager` | Everything a contributor can do, plus grant/revoke access to other users |

These roles form a strict hierarchy: `viewer < editor < contributor < manager`. A dependency check for `"editor"` will pass for any role at or above editor.

### How access is resolved

The `require_matter_role(minimum_role)` dependency on each route resolves matter access in this order:

1. **system_admin** → always granted, treated as `manager`.
2. **internal_admin or external_admin whose group owns the matter** → implicitly granted `manager`. A matter's `owner_group_id` field determines ownership.
3. **Explicit grant** → look up `matter_access` for the user + matter combination. If found, compare the granted role against the minimum required role using the hierarchy above.
4. **No match** → 403.

The dependency also resolves `matter_id` from path parameters automatically. It walks the resource chain: `matter_id` → `item_id` → `room_id` → `crop_id` → `file_id`.

```
GET /api/matters/{matter_id}/items     → matter_id in path, direct
PATCH /api/items/{item_id}             → item_id → item.matter_id
POST /api/evidence/{file_id}/recrop   → file_id → evidence_file.matter_id
```

---

## Admin Panels

Three admin panels are mounted under `/admin/`. Access is guarded by system role, not matter role.

### System Admin — `/admin/system/`

Accessible only to `system_admin`.

- View all users, create user invites with any system role
- Deactivate / activate users
- Reset a user's MFA
- View all groups, create external groups, deactivate groups
- View all matters
- View, filter, and export the audit log

### Internal Admin — `/admin/internal/`

Accessible to `system_admin` and `internal_admin`.

- Manage internal users (invite, deactivate)
- Manage external groups (create, invite external admins)
- Manage matter access grants (grant/revoke per-user per-matter roles)

### Org Admin — `/admin/org/`

Accessible to `system_admin`, `internal_admin`, and `external_admin`.

**Group scoping:**
- `external_admin` — always scoped to their own group. No group selector shown.
- `internal_admin` — must pass `?group_id=<id>` to select which external organization to manage. Without it, a group selector is shown.
- `system_admin` — same as internal_admin; must pass `?group_id=<id>`.

Within scope:
- View and invite external users
- View matters shared with the org
- Manage per-user access to those matters for org members
- Update the organization profile

---

## Comments Visibility

Comments on items have a `visibility` field:

- `"internal"` — visible only to users with an internal group (`group_kind == "internal"`). External users never see these comments.
- `"shared"` — visible to all users with matter access.

Internal users see a visibility selector when posting. External users always post as `"shared"`.

---

## Invite Flow

New users are created via invite, not self-registration.

1. Admin creates the user via the appropriate admin panel. The user row is written to the DB with `system_role`, `group_id`, `email`, `invite_code` (hashed), and `invite_expires_at = now + 7 days`. No password is set.
2. The admin receives a registration URL: `https://<host>/register/<raw_code>`.
3. The invitee visits the URL, enters a display name and password, and the account becomes active. The invite code is cleared.
4. Invite codes expire after 7 days. Expired codes show an "invalid invite" page.
5. A code cannot be reused once registration is complete (`password_changed_at` is set on completion).

---

## Testing

The scenarios below cover the full RBAC surface. Run them in a local dev environment with `uv run dev`. Use the System Admin panel (log in as a `system_admin` user) to set up accounts.

### Setup: Seed the required accounts

Before running scenarios, create these users from the System Admin panel at `/admin/system/users`:

| User | Role | Group |
|---|---|---|
| `sysadmin@test.local` | `system_admin` | Internal |
| `intadmin@test.local` | `internal_admin` | Internal |
| `intuser@test.local` | `internal_user` | Internal |
| `extadmin@test.local` | `external_admin` | Acme Corp (external) |
| `extuser@test.local` | `external_user` | Acme Corp (external) |
| `extuser2@test.local` | `external_user` | Other Firm (a different external group) |

Create two external groups: **Acme Corp** and **Other Firm** (from `/admin/internal/groups`).

Create two matters: **Matter A** (owned by Internal group) and **Matter B** (owned by Internal group).

---

### Scenario 1: System admin has unrestricted access

1. Log in as `sysadmin@test.local`.
2. Navigate to `/admin/system/` — expect: System Admin panel loads.
3. Navigate to `/admin/internal/` — expect: Internal Admin panel loads.
4. Navigate to `/admin/org/?group_id=<acme_id>` — expect: Org panel for Acme Corp loads.
5. Navigate to Matter A — expect: full access, all edit controls visible.
6. Navigate to Matter B — expect: full access.

---

### Scenario 2: Internal admin access boundaries

1. Log in as `intadmin@test.local`.
2. Navigate to `/admin/system/` — expect: **403**.
3. Navigate to `/admin/internal/` — expect: Internal Admin panel loads.
4. Navigate to `/admin/org/?group_id=<acme_id>` — expect: Org panel for Acme Corp loads.
5. Navigate to Matter A — expect: full access (internal admin implicitly has manager on internal-owned matters).

---

### Scenario 3: External admin scoped to own org

1. Log in as `extadmin@test.local`.
2. Navigate to `/admin/system/` — expect: **403**.
3. Navigate to `/admin/internal/` — expect: **403**.
4. Navigate to `/admin/org/` — expect: Org panel loads, scoped to Acme Corp. No group selector shown.
5. Navigate to `/admin/org/?group_id=<other_firm_id>` — expect: **403** or redirected to Acme Corp scope (Acme data shown, not Other Firm's).

---

### Scenario 4: Matter role — explicit grants required for external users

1. Log in as `extuser@test.local`.
2. Navigate to Matter A — expect: **403** (no grant yet).
3. Log in as `intadmin@test.local`. Go to `/admin/internal/matters/<matter_a_id>/access`. Grant `extuser@test.local` the `viewer` role on Matter A.
4. Log back in as `extuser@test.local`. Navigate to Matter A — expect: loads, read-only. Edit controls not present.
5. Attempt `PATCH /api/items/<item_id>` on an item in Matter A — expect: **403** (viewer cannot edit).
6. Log in as `intadmin@test.local`. Upgrade `extuser@test.local` to `editor` on Matter A.
7. Log back in as `extuser@test.local`. Attempt to edit an item — expect: succeeds.

---

### Scenario 5: External user cannot see another org's data

1. Grant `extuser@test.local` (Acme Corp) viewer access to Matter A.
2. Log in as `extuser2@test.local` (Other Firm).
3. Navigate to Matter A — expect: **403**.
4. Log in as `extadmin@test.local` (Acme Corp). Navigate to `/admin/org/users` — expect: only Acme Corp users listed (not Other Firm users).

---

### Scenario 6: Comments visibility

1. Grant `extuser@test.local` viewer access to Matter A. Grant `intuser@test.local` viewer access to Matter A.
2. Log in as `intuser@test.local`. Open an item in Matter A. Post a comment with visibility **Internal**.
3. Log in as `extuser@test.local`. Open the same item — expect: the internal comment is **not visible**.
4. Log in as `intuser@test.local`. Post another comment with visibility **Shared**.
5. Log in as `extuser@test.local`. Open the item — expect: the shared comment **is visible**. The internal comment is still not visible.

---

### Scenario 7: Internal admin manages matter access

1. Log in as `intadmin@test.local`. Navigate to `/admin/internal/matters/<matter_a_id>/access`.
2. Grant `extuser@test.local` the `contributor` role.
3. Revoke the grant.
4. Verify `extuser@test.local` can no longer access Matter A (403).

---

### Scenario 8: External admin invites a user to their org

1. Log in as `extadmin@test.local`. Navigate to `/admin/org/users`.
2. Invite `newuser@test.local` as `external_user` in Acme Corp.
3. Copy the invite URL shown.
4. Open the invite URL in a new browser session. Complete registration.
5. Log in as `sysadmin@test.local`. Verify `newuser@test.local` appears in Acme Corp's user list in the System Admin panel.
6. Verify `newuser@test.local` cannot log in with a different org's invite URL (wrong or expired code shows invalid page).
