# Regenerate Invite Link — Design Spec

**Date:** 2026-05-30
**Branch:** feat/regenerate-invite-link (to be created)

## Overview

System admins and internal admins can regenerate a fresh invite link for any existing user. This is useful when an original invite expires before the user registers, or when an admin needs to reset a registered user's credentials via the invite flow.

## Behaviour

Regenerating an invite:
- Creates a new raw invite code via `generate_invite_code()`
- Stores its SHA-256 hash in `user.invite_code`
- Sets `user.invite_expires_at` to 7 days from now
- Clears `user.password_changed_at` (so the registration form will accept the new code even for already-registered users)
- Writes an audit log entry: `action="admin.invite_regenerated"`, `resource_type="user"`, `resource_id=user_id`
- Re-renders the user detail page with `invite_url` in context

No schema migration is required — `invite_code`, `invite_expires_at`, and `password_changed_at` are all existing columns on `User`.

## RBAC

| Admin role | Scope |
|---|---|
| `system_admin` | Any user |
| `internal_admin` | Users whose `group_id` matches the admin's own `group_id` |

## Backend

### New endpoint — system admin

```
POST /admin/system/users/{user_id}/regenerate-invite
```

- Auth: `require_system_admin`
- 404 if `user_id` not found
- Generates code, updates user, commits, writes audit log
- Re-renders `admin/system/user_detail.html` with `invite_url` and existing context

### New endpoint — internal admin

```
POST /admin/internal/users/{user_id}/regenerate-invite
```

- Auth: `_require_internal_or_above`
- 404 if `user_id` not found or `target.group_id != user.group_id`
- Same generate/update/commit/audit logic
- Re-renders `admin/internal/user_detail.html` with `invite_url` and existing context

Both endpoints follow the same pattern as `system_reset_mfa` in `routers/admin/system.py` for audit logging, and the same re-render pattern as the existing invite endpoints.

## Frontend

### Invite URL banner

Added to both user detail templates at the top of `{% block content %}`, shown only when `invite_url` is in context. Uses the same green banner style as the list pages:

```html
{% if invite_url %}
<div class="mb-6 p-4 bg-green-50 border border-green-200 rounded-lg">
  <p class="text-sm font-medium text-green-800">New invite link (valid 7 days):</p>
  <p class="mt-1 text-sm text-green-700 font-mono break-all">{{ invite_url }}</p>
</div>
{% endif %}
```

### Regenerate button

Added to the `flex gap-3` button row in both user detail templates. Always visible (no conditional — the feature works for any user):

```html
<form method="POST" action="/admin/system/users/{{ target.id }}/regenerate-invite">
  <button type="submit" class="bg-indigo-600 text-white px-4 py-2 rounded text-sm hover:bg-indigo-700">
    Regenerate Invite Link
  </button>
</form>
```

The internal admin template uses `/admin/internal/users/{{ target.id }}/regenerate-invite`.

**No inline JS.** The button is a plain form POST per the CSP policy.

## Files changed

| File | Change |
|---|---|
| `src/cvp/routers/admin/system.py` | Add `system_regenerate_invite` endpoint |
| `src/cvp/routers/admin/internal.py` | Add `internal_regenerate_invite` endpoint |
| `src/cvp/templates/admin/system/user_detail.html` | Add invite_url banner + Regenerate button |
| `src/cvp/templates/admin/internal/user_detail.html` | Add invite_url banner + Regenerate button |
| `tests/routers/admin/test_system_regenerate_invite.py` | New test file |
| `tests/routers/admin/test_internal_regenerate_invite.py` | New test file |

## Tests

Each test file covers:
1. Happy path — code is updated, `password_changed_at` is cleared, response contains the invite URL
2. 404 — unknown `user_id` returns 404
3. Scope enforcement — internal admin cannot regenerate for a user in a different group (returns 404)
4. Auth enforcement — non-admin user is rejected (403)
