# User Feedback — Design

**Date:** 2026-06-03
**Status:** Approved for planning

## Goal

Give logged-in users a frictionless way to send free-form feedback to system admins from any page in the app, and give system admins a single place to triage, status-track, and reply to that feedback. Feedback is critical signal for a tool used by a small founding team — the UX needs to make submitting cheap and replying cheaper.

## Out of scope (v0)

- Email or push notifications. In-app badges only.
- File or screenshot attachments. Tracked separately in `docs/BACKLOG.md`.
- Edits to feedback or comment text after submission. Soft-delete only.
- Public/anonymous submission. Login is required for all feedback actions.
- Voting, upvoting, tagging, or categorizing feedback.

## User stories

1. As any logged-in user, I can click a floating button on any authenticated page, type a feedback blurb, and submit it. The page URL I'm on is captured automatically.
2. As any logged-in user, I can see the list of feedback I've submitted, expand each one to see the full thread, and post comments to the thread.
3. As any logged-in user, I see an unread indicator on the floating button when an admin has replied to one of my threads or changed its status.
4. As a `system_admin`, I see an admin nav link with an unread count for feedback. The admin page lists every feedback in the system with filters and sorting.
5. As a `system_admin`, I can change the status of any feedback to one of `pending`, `reviewing`, `backlog`, `canceled`, or `done`. Only I can change status.
6. As a `system_admin`, I can reply on any thread, and I can submit a new feedback as myself or on behalf of another user.
7. As the author of a feedback or comment, I can soft-delete it. As a `system_admin`, I can soft-delete any feedback or comment.

## Access model

- **Author OR `system_admin`** can read a feedback thread, post comments on it, and mark it read.
- **Author OR `system_admin`** can soft-delete the feedback itself.
- **Comment author OR `system_admin`** can soft-delete a comment.
- **`system_admin` only** can change status or submit on behalf of another user.
- `internal_admin`, `external_admin`, `internal_user`, `specialist`, and `external_user` all use the widget the same way — submit feedback and view their own threads. None of them see other users' feedback.

Access check lives in `_check_feedback_access(db, user, feedback)` in `src/cvp/dependencies.py`.

## Data model

Two new tables in a new ORM module `src/cvp/models_feedback.py`, with one Alembic migration.

### `feedback`

| Column | Type | Notes |
|---|---|---|
| `id` | str | UUID, PK |
| `author_user_id` | str | FK `users.id`, NOT NULL |
| `author_group_id` | str | FK `groups.id`, NOT NULL — snapshot of the author's group at submission time |
| `page_url` | Text | NOT NULL, relative path; validated via `_clean_page_url()` |
| `body` | Text | NOT NULL, immutable after insert |
| `status` | str | NOT NULL, default `"pending"`, CHECK in `("pending","reviewing","backlog","canceled","done")` |
| `created_at` | DateTime (UTC) | server default `now()` |
| `status_changed_at` | DateTime (UTC) | nullable — updated on every status change |
| `status_changed_by_user_id` | str | FK `users.id`, nullable — updated on every status change |
| `deleted_at` | DateTime (UTC) | nullable — soft delete |
| `deleted_by_user_id` | str | FK `users.id`, nullable |
| `last_admin_read_at` | DateTime (UTC) | nullable — drives admin unread badge |
| `last_author_read_at` | DateTime (UTC) | nullable — drives author widget badge |

Indexes: `(author_user_id, created_at desc)`, `(status, created_at desc)`.

### `feedback_comment`

| Column | Type | Notes |
|---|---|---|
| `id` | str | UUID, PK |
| `feedback_id` | str | FK `feedback.id`, NOT NULL, indexed |
| `author_user_id` | str | FK `users.id`, NOT NULL |
| `body` | Text | NOT NULL, immutable after insert |
| `created_at` | DateTime (UTC) | server default `now()` |
| `deleted_at` | DateTime (UTC) | nullable — soft delete |
| `deleted_by_user_id` | str | FK `users.id`, nullable |

Index: `(feedback_id, created_at asc)`.

### Status semantics

| Status | Meaning | Set by |
|---|---|---|
| `pending` | Initial state. Admin has not yet looked. | System on insert |
| `reviewing` | Admin is actively considering it. | Admin |
| `backlog` | Acknowledged, scheduled for later. | Admin |
| `canceled` | Won't be acted on. | Admin |
| `done` | Resolved. | Admin |

Transitions are unrestricted — admin can move to any status from any status. `status_changed_at` and `status_changed_by_user_id` are updated on every status change.

### Unread badges

- **Author widget red dot** lights up when any of the author's non-deleted feedback has `(status_changed_at > last_author_read_at)` OR the latest non-author comment has `created_at > last_author_read_at`. Calling `POST /feedback/{id}/read` as the author sets `last_author_read_at = now()`.
- **Admin nav unread count** is the number of feedback rows where `(created_at > last_admin_read_at)` OR `(latest non-admin comment created_at > last_admin_read_at)`. Calling `POST /feedback/{id}/read` as an admin sets `last_admin_read_at = now()`. `last_admin_read_at` is shared across all admins — this is a small founding team, so a single read-cursor is fine.

## Routes

### User-facing — `src/cvp/routers/feedback.py`, mounted at `/feedback`

| Method | Path | Purpose | Access |
|---|---|---|---|
| GET | `/feedback/widget` | Returns the floating widget partial (button + popover panel + author's threads list + badge state). | Any authenticated user |
| POST | `/feedback` | Submit new feedback. Form: `body`, `page_url`. Sets `author_user_id`, `author_group_id`, `status="pending"`. | Any authenticated user |
| GET | `/feedback/{id}` | Render a single feedback thread (initial post + comments + composer). | Author OR `system_admin` |
| POST | `/feedback/{id}/comments` | Add comment to thread. | Author OR `system_admin` |
| POST | `/feedback/{id}/read` | Mark thread read. Sets `last_author_read_at` (author) or `last_admin_read_at` (admin). | Author OR `system_admin` |
| POST | `/feedback/{id}/delete` | Soft-delete the feedback. | Author OR `system_admin` |
| POST | `/feedback/comments/{id}/delete` | Soft-delete a comment. | Comment author OR `system_admin` |

### Admin — `src/cvp/routers/admin/feedback.py`, mounted at `/admin/system/feedback`

| Method | Path | Purpose |
|---|---|---|
| GET | `/admin/system/feedback` | List view with filters (status multi-select, group, author search, include-deleted toggle) and sort (by status/created/group/author, asc/desc). |
| GET | `/admin/system/feedback/{id}` | Admin view of a single thread. Shares the thread partial with the user view; adds the status-control sidebar and the soft-delete control. |
| POST | `/admin/system/feedback/{id}/status` | Change status. Validates against the allowed set. Updates `status_changed_at` and `status_changed_by_user_id`. |
| POST | `/admin/system/feedback/new-as` | Create a feedback item. Form: `body`, `page_url`, `author_user_id` (defaults to the admin). Same write path as the user submit endpoint, but with a chooseable author. |

All admin routes are guarded by a `require_system_admin` dependency.

### CSRF

All POSTs use the existing `cvp_csrf` cookie / header mechanism already enforced across the app.

## Input sanitization

All user input passes through these checks before reaching the database:

- **`body` (feedback)**: `.strip()`, must be non-empty after strip, hard cap 5000 characters. Rejected with 400 otherwise.
- **`body` (comments)**: same shape, hard cap 2000 characters.
- **`page_url`**: must start with `/`, must not start with `//` (protocol-relative URLs are rejected — `//evil.com` would otherwise become an off-origin link in the admin view), max 2048 characters. Validated by a `_clean_page_url(raw: str) -> str` helper in the feedback router; on failure it stores `"/"` and logs a warning rather than 400-ing the submission.
- **`status`**: validated against a hard-coded module-level `ALLOWED_STATUSES` set. The wire value is never echoed into HTML or SQL as a raw string.
- **`author_user_id`** on `POST /admin/system/feedback/new-as`: must resolve to an active user; 400 otherwise.
- **Rendering**: all user-controlled text is rendered through Jinja autoescape. No `| safe`. No markdown. No raw HTML.
- **SQL**: all ORM access is parameterized via SQLAlchemy 2.x. No raw SQL.

## Widget UI

- **Floating button** — fixed `bottom-4 right-4`, circular 48px, indigo background to match the app's existing buttons. Small red dot in the top-right corner when the author has unread admin activity.
- **Popover panel** opens on click, 380px × 480px, rounded card with shadow. Sections, top to bottom:
  1. Header: "Feedback" + close (×) button.
  2. New-feedback form: `<textarea>` with a 5000-char counter, hidden `page_url` input populated client-side from `window.location.pathname + window.location.search`, Submit button. HTMX `hx-post="/feedback"` swaps the panel body to show the new thread.
  3. "My feedback" list: author's threads in reverse-chronological order. Each row shows status pill, first 80 chars of body, time-ago, and a red dot if unread. Click expands inline to the full thread + comment composer.
- Soft-deleted feedback the author deleted is filtered out of their own list. Admin-deleted feedback shows a tombstone ("Removed by admin"); the author's own deletion shows ("Removed by you").

### Status pill colors

| Status | Tailwind classes |
|---|---|
| `pending` | `bg-gray-100 text-gray-800` |
| `reviewing` | `bg-blue-100 text-blue-800` |
| `backlog` | `bg-yellow-100 text-yellow-800` |
| `canceled` | `bg-red-100 text-red-800` |
| `done` | `bg-green-100 text-green-800` |

### Where the widget appears

Included in `base.html` only when `user` is truthy AND `request.url.path` is not in `{"/", "/login", "/register", "/splash"}`. Lives behind a single Jinja include so the gating is in one place.

### Interactivity

Pure HTMX + delegated listeners in `src/cvp/static/app.js`. New `data-feedback-*` attributes wire up open/close/expand/collapse via the existing delegated `document.addEventListener('click', …)` block. **No inline JavaScript event handlers** (CSP).

## Admin page

`/admin/system/feedback`, linked from the existing `/admin/system/` admin nav as "Feedback" with an unread-count chip when > 0.

### List view

- **Filter bar** at top:
  - Status multi-select (checkboxes for all 5 statuses; default: all checked except `done` and `canceled`).
  - Group dropdown (single-select; "All groups" default).
  - Author search (typeahead by email or display_name).
  - Include-deleted toggle (off by default).
- **Sort**: column headers on Status, Created, Group, Author toggle asc/desc. Default `Created desc`.
- **Columns**: Status pill • Author (email + group label) • Page URL (linkified, `target="_blank"`, `rel="noopener noreferrer"`) • Excerpt (first 120 chars) • Created (relative time) • Unread indicator.
- Row click navigates to `/admin/system/feedback/{id}`.
- "New feedback" button at top opens the same form as the widget, plus a user-picker (defaults to the admin themselves). Lets the admin submit either as themselves or on behalf of another user.

### Thread view

Shared template (`templates/_feedback_thread.html`) used by both the user widget expansion and the admin thread page. Admin gets an extra sidebar:

- Status buttons (5 buttons, current status highlighted).
- "Delete feedback" button (soft delete with confirm).
- Per-comment "Delete" link (soft delete with confirm).

## File layout (new files)

```
alembic/versions/<rev>_add_feedback_tables.py
src/cvp/models_feedback.py
src/cvp/routers/feedback.py
src/cvp/routers/admin/feedback.py
src/cvp/templates/_feedback_widget.html       # floating button + popover shell
src/cvp/templates/_feedback_thread.html       # shared thread partial (user + admin)
src/cvp/templates/_feedback_list_row.html     # row used by widget + admin list
src/cvp/templates/admin/system/feedback.html  # admin list view
src/cvp/templates/admin/system/feedback_detail.html  # admin thread page
tests/test_models_feedback.py
tests/test_feedback_router.py
tests/test_admin_feedback_router.py
tests/test_feedback_sanitization.py
```

Touched existing files:

- `src/cvp/main.py` — register the two new routers.
- `src/cvp/templates/base.html` — include `_feedback_widget.html` when gating allows.
- `src/cvp/templates/admin/system/base.html` (or whichever admin nav is shared) — add "Feedback" link with unread-count chip.
- `src/cvp/dependencies.py` — add `_check_feedback_access()` and `require_system_admin` (if not already present).
- `src/cvp/static/app.js` — add delegated handlers under the existing pattern at lines 225–275.
- `docs/BACKLOG.md` — append the "Feedback attachments" entry.

## Testing

Following the project convention (depreciation has near-100% coverage; routers have one happy-path integration test each; sanitization/pure logic is unit-tested):

- **`tests/test_models_feedback.py`** — model defaults; the `status` CHECK constraint rejects unknown values; soft-delete columns default to null.
- **`tests/test_feedback_router.py`** — happy paths for submit, list own, view own thread, comment, soft-delete; access denials (other user can't view, anonymous can't submit, external_user only sees their own threads).
- **`tests/test_admin_feedback_router.py`** — happy paths for list with filter/sort, change status, submit-on-behalf; `internal_admin` and `external_admin` both get 403 on every admin route.
- **`tests/test_feedback_sanitization.py`** — `_clean_page_url()` rejects schemes, protocol-relative URLs, and over-length input; body length caps enforced; empty bodies rejected; `status` whitelist enforced server-side.

## Open considerations (acknowledged, deferred)

- **Notifications beyond in-app badges** — deferred until email infra exists for the rest of the app.
- **Attachments** — tracked in `docs/BACKLOG.md`.
- **Per-admin read state** — current design uses a single shared `last_admin_read_at`. Adequate for the current team size; if multiple admins triage simultaneously we may want per-admin read receipts.
- **Search inside feedback bodies** — admin filter is by status/group/author only; full-text search is deferred.
