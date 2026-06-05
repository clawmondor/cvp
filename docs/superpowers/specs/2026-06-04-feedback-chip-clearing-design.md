# Feedback chip clearing — design

**Date:** 2026-06-04
**Status:** Approved for planning

## Problem

The admin sidebar feedback chip stays stuck at the count of every non-deleted feedback in the system. Changing status to `done` or `canceled` does not drop it; nothing the admin does clears it.

The user-side widget's red dot is broken the same way — once an admin replies or changes status on one of the user's items, the dot stays on forever.

**Root cause:** `count_admin_unread` and `has_author_unread` (`src/cvp/routers/feedback.py`) both branch on `last_admin_read_at` / `last_author_read_at` cursors, but those cursors are only updated by `POST /feedback/{id}/read`, and **no UI ever calls `/read`**. The cursors stay `NULL` forever, the "never been read" branch always fires, and the chips never clear.

## Goal

Both chips behave like an inbox: the count drops when the relevant user opens the thread, and a new non-self comment re-flags it.

- **Admin chip:** "items no admin has viewed since the last non-admin activity." Status (including `done` / `canceled`) is intentionally ignored — viewing is the clear action, not closing.
- **User widget dot:** "an admin has done something on one of your items since you last looked." Same model, per-author.

## Approach

Stamp the relevant read cursor as a side effect of the GET endpoints that already render the thread. No schema changes, no new endpoints, no JS changes. The user widget opens threads inline via HTMX; its floating badge is refreshed via an `hx-swap-oob` span on the thread response.

## Server changes

### `GET /feedback/{feedback_id}` (`get_thread` in `src/cvp/routers/feedback.py`)

After the access check, before rendering:

```python
now = datetime.now(tz=timezone.utc)
if user.system_role == "system_admin":
    fb.last_admin_read_at = now
else:
    fb.last_author_read_at = now
db.commit()
```

The same logic as the existing `mark_read` endpoint, inlined into the GET.

### `GET /admin/system/feedback/{feedback_id}` (`admin_thread` in `src/cvp/routers/admin/feedback.py`)

After loading the feedback, before rendering:

```python
fb.last_admin_read_at = datetime.now(tz=timezone.utc)
db.commit()
```

The user is guaranteed `system_admin` here by `require_system_admin`, so no role branch needed.

### `POST /feedback/{feedback_id}/comments` (`post_comment`)

Posting a comment is at least as strong a "I've seen this" signal as opening. After validation and persisting the new comment, stamp the same cursor before re-rendering the thread:

```python
if user.system_role == "system_admin":
    fb.last_admin_read_at = datetime.now(tz=timezone.utc)
else:
    fb.last_author_read_at = datetime.now(tz=timezone.utc)
db.commit()
```

### `POST /admin/system/feedback/{feedback_id}/status` (`change_status`)

Already sets `status_changed_at` and `status_changed_by_user_id`. Add `fb.last_admin_read_at = now` so changing status also counts as reading (consistent with the inbox model — the admin must have looked at the item to decide on a status).

### `POST /feedback/{feedback_id}/read` (`mark_read`)

Stays exactly as it is. Still an explicit "I've seen this" hook, useful for tests and for any future client that wants to mark-read without rendering. The existing tests against this endpoint stay green.

## User widget: OOB badge refresh

The widget's floating button hosts a child span:

```html
<span hx-get="/feedback/unread"
      hx-trigger="load, every 60s"
      hx-swap="outerHTML"></span>
```

Today that span's content is rendered by `_feedback_unread_badge.html` — either the visible red dot `<span id="feedback-badge-dot" …>` or a hidden span without the id.

After this change, `_feedback_thread.html` ends with an out-of-band copy of the same partial — but **only when rendering for a non-admin viewer**, since admin pages don't host the floating widget:

```html
{% if not is_admin_view %}
{% include "_feedback_unread_badge_oob.html" %}
{% endif %}
```

Where `_feedback_unread_badge_oob.html` is the same span as `_feedback_unread_badge.html` but with `hx-swap-oob="outerHTML"` attached to the visible (`id="feedback-badge-dot"`) branch AND to the hidden branch. The hidden branch needs the same id (and OOB attribute) on the swapped-in version so it can replace the visible badge that's currently in the DOM.

Concretely, `_feedback_unread_badge_oob.html`:

```html
{% if show_dot %}
<span id="feedback-badge-dot" hx-swap-oob="outerHTML"
      class="absolute top-1 right-1 inline-block h-2.5 w-2.5 rounded-full bg-red-500 ring-2 ring-white"></span>
{% else %}
<span id="feedback-badge-dot" hx-swap-oob="outerHTML" class="hidden"></span>
{% endif %}
```

The thread render path computes `show_dot = has_author_unread(db, user.id)` after stamping the cursor, then passes it to `_feedback_thread.html`, which includes the OOB partial at the end. HTMX's OOB swap picks up the span by id and replaces the badge that lives inside the floating button.

`_render_thread` (`src/cvp/routers/feedback.py`) gains:

```python
show_dot = False if is_admin_view else has_author_unread(db, user.id)
```

and threads it through the template render call.

**For admins:** opening a thread is a full page navigation (`GET /admin/system/feedback/{id}`) which re-renders the sidebar with a fresh `count_admin_unread(db)`. No OOB needed. Inline HTMX flows on the admin side (posting a comment, changing status) re-render the thread partial — but since `is_admin_view=True` the OOB span is skipped, keeping the admin response free of badge-related markup.

## Admin chip

`count_admin_unread(db)` is unchanged. The fix is upstream — now that the GET stamps `last_admin_read_at`, the existing counter correctly drops items the admin has viewed.

## Edge cases

- **Two admins viewing back-to-back:** shared `last_admin_read_at` (per the existing spec). First admin's GET stamps the cursor; second admin sees the same cleared state. Acceptable.
- **Author opens a thread that has no admin activity yet:** stamping `last_author_read_at` is harmless; `has_author_unread` already returns False since there's nothing newer than `now`.
- **Status change without an admin opening first:** the admin must have viewed the row in the list at minimum, but the `change_status` POST now also stamps `last_admin_read_at`, so the explicit "status change" action is treated as a read too. Without this, an admin who triages straight from the list (filter → click pill on detail → done) might leave items technically "unread."
- **Rapid double-clicks:** idempotent. Each handler just sets the cursor to `now()`.
- **A non-admin user comments on their own thread (impossible in current UX — they can only comment on threads they own, but if it happens):** the author's own comment is the only comment by the author; the OOB swap renders `show_dot = False` (no non-author activity), which matches the existing semantics of `has_author_unread`.

## Files touched

| File | Change |
|---|---|
| `src/cvp/routers/feedback.py` | `get_thread`, `post_comment`, `_render_thread` stamp cursor + compute `show_dot`; pass to template. |
| `src/cvp/routers/admin/feedback.py` | `admin_thread`, `change_status` stamp `last_admin_read_at`. |
| `src/cvp/templates/_feedback_thread.html` | Include OOB badge partial at the end. |
| `src/cvp/templates/_feedback_unread_badge_oob.html` | New file — OOB-tagged twin of the existing badge partial. |
| `tests/test_feedback_router.py` | New tests for cursor stamping and OOB inclusion. |
| `tests/test_admin_feedback_router.py` | New tests for admin GET and status change stamping. |

No schema migration. No new endpoints. No client-side JavaScript changes.

## Testing

Behavior to verify with new tests:

- `GET /feedback/{id}` as the author stamps `last_author_read_at` and does NOT touch `last_admin_read_at`.
- `GET /feedback/{id}` as a `system_admin` stamps `last_admin_read_at` and does NOT touch `last_author_read_at`.
- `GET /admin/system/feedback/{id}` stamps `last_admin_read_at`.
- `POST /admin/system/feedback/{id}/status` stamps `last_admin_read_at` (in addition to status fields).
- `POST /feedback/{id}/comments` stamps the appropriate cursor based on commenter role.
- `count_admin_unread` decrements after admin GETs the detail page.
- `has_author_unread` returns False after author GETs the thread.
- The thread response body contains `id="feedback-badge-dot"` with `hx-swap-oob` (so the floating widget badge gets replaced).

Existing tests must continue to pass — particularly `test_mark_read_as_author_updates_author_cursor` (which exercises `POST /read`) and `test_change_status_updates_row` (which now also sets `last_admin_read_at` as a side effect, but its assertions are only on status fields, so still green).
