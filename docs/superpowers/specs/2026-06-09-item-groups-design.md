# Item Groups — Design

**Status:** Draft
**Date:** 2026-06-09
**Owner:** chris.mondor@gmail.com

## Problem

When associates document a property on-site, they often capture multiple physical
items in a single photo and place a numbered or labeled placard in the frame as
an organizational marker. Today, the app has no concept of these on-site groupings:
specialists can't tell which items belong to the same placard, and the vision
pipeline doesn't know to ignore the placard itself when extracting items.

## Goals

1. Optional `Group` metadata on items that mirrors the on-site placard system.
2. A per-image dropdown in the evidence grid that, when a scan runs, applies a
   chosen group to all items extracted from that image.
3. Group management (create / rename / delete) from the Rooms tab, plus inline
   group creation from the evidence dropdown and the item edit form.
4. The vision scan auto-detects a placard in the image and uses its text as the
   group, when the dropdown is left on the default "Auto-detect" mode.
5. The placard is never extracted as a line item.

## Non-goals

- Reading multiple placards per image (one placard per photo in v0).
- Showing group membership in the report PDF or CSV exports.
- A Groups column or filter in the Items tab (deferred to backlog).
- Cross-matter groups, or any link between groups and rooms.

## Decisions

These were settled during brainstorming and the rest of the spec assumes them:

- **Scope:** Group belongs to a Matter, not to a Room. Items in one group may
  span rooms.
- **Identity:** Free-text name (e.g. `"12"`, `"Box A"`, `"Master bedroom dresser"`).
  Group is an optional field on items; not all matters use it.
- **Default UI state:** The per-image dropdown defaults to `"Auto-detect"`. If
  no placard is detected the items come in ungrouped.
- **Conflict rule:** When the dropdown is set to a specific group and the scan
  also detects a placard, the dropdown wins. The detected text is logged but
  ignored.
- **Auto-create on detection:** When auto-detect is on and a placard is read,
  the system either reuses an existing matching Group or creates a new one.
- **Dedupe:** Group names are matched case-insensitively with whitespace
  trimmed. `"12"`, `" 12 "`, and `"12 "` collapse to the same group; `"box a"`
  and `"Box A"` collapse.
- **Placard exclusion:** The vision prompt instructs the model to return the
  placard text in a dedicated JSON field, separate from the items list, so a
  placard can never be mis-classified as an item.
- **Selection persistence:** The dropdown's selection persists on the
  `EvidenceFile` row (survives reload; applies to every subsequent scan of that
  image).
- **Item edit form:** Combobox-style — select existing group, choose `(none)`,
  or `+ New group…` to create one inline.
- **Rooms tab:** Renamed visually to "Rooms & Groups"; groups are managed in a
  second panel alongside rooms.
- **Group delete:** `ON DELETE SET NULL` on both `items.group_id` and
  `evidence_files.pinned_group_id`. Items survive, evidence loses its pin.

## Data model

### New table: `groups`

| column            | type     | constraints                                  |
|-------------------|----------|----------------------------------------------|
| `id`              | string   | PK, uuid (matches existing convention)       |
| `matter_id`       | string   | FK → `matters.id`, NOT NULL, indexed         |
| `name`            | string   | NOT NULL, trimmed before storage             |
| `name_normalized` | string   | NOT NULL, `name.strip().lower()`             |
| `created_at`      | datetime | server_default `now()`                       |
| `updated_at`      | datetime | server_default `now()`, `onupdate now()`     |

- Unique constraint: `(matter_id, name_normalized)` — enforces dedupe at the DB.
- Index on `matter_id` for listing groups in a matter.

### Changes to existing tables

- **`items`**: add nullable `group_id: str | None` (FK → `groups.id`,
  `ON DELETE SET NULL`).
- **`evidence_files`**: add nullable `pinned_group_id: str | None`
  (FK → `groups.id`, `ON DELETE SET NULL`). `NULL` = "Auto-detect" mode;
  non-NULL = "this group, overriding any detected placard".

Why two separate FKs:
- `evidence_files.pinned_group_id` is a *scan-time instruction* attached to the
  source photo.
- `items.group_id` is the *actual* group membership of an extracted item, which
  a specialist can edit independently of how it was originally scanned.

## Vision pipeline changes

### Prompt (`src/cvp/services/vision_prompts.py`)

Add an instruction block explaining that any numbered/labeled placard, sticky
note, card, or organizational marker visible in the photo is *metadata*, not an
item, and must be:

1. Excluded from the `items` array entirely.
2. Returned, if present, as the raw text it shows, in a new top-level field
   `placard_text` (string, `""` when no placard is detected).

### Response schema (`vision_models.py`, `vision_adapters.py`)

Extend the structured-output schema so the model returns:

```json
{
  "items": [ ... existing item shape ... ],
  "placard_text": "12"
}
```

Adapters that flatten the response must surface `placard_text` to the worker
alongside the items list. Empty string when absent.

### Worker (`src/cvp/services/vision_worker.py`, `vision.py`)

After parsing the model response, compute the effective `group_id` for the scan
in this order:

1. If `EvidenceFile.pinned_group_id` is set → use it (dropdown wins).
   - If `placard_text` is also non-empty and does not normalize to the pinned
     group's `name_normalized`, log at INFO: pinned group id, detected text,
     evidence file id. No user-facing alert in v0.
2. Else if `placard_text` is non-empty → call
   `services.groups.find_or_create(session, matter_id, placard_text)` and use
   the returned group.
3. Else → effective `group_id` is `None`.

Apply the resulting `group_id` to every `Item` row created by this scan
(including items created via `ItemCrop`). The placard never appears in `items`
because the prompt routes it to its own field.

### New service: `src/cvp/services/groups.py`

```python
def find_or_create(session, matter_id: str, name: str) -> Group:
    normalized = name.strip().lower()
    if not normalized:
        raise ValueError("group name cannot be empty")
    existing = session.execute(
        select(Group).where(
            Group.matter_id == matter_id,
            Group.name_normalized == normalized,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    group = Group(matter_id=matter_id, name=name.strip(), name_normalized=normalized)
    session.add(group)
    session.flush()
    return group
```

Race condition under the unique constraint: catch `IntegrityError` on insert and
re-query.

## UI changes

### Evidence grid (`src/cvp/templates/_evidence_grid.html`)

Next to each image's scan controls, render a `<select>` whose `change` event
issues an HTMX `PATCH /matters/{matter_id}/evidence/{file_id}/group`:

- `(Auto-detect)` — `value=""`, default when `pinned_group_id` is NULL.
- One `<option>` per existing Group in the matter, sorted by `created_at`.
- `+ New group…` — sentinel value (`__new__`). On selection, HTMX swaps in a
  small inline name prompt fragment. Submitting the prompt:
  1. `POST /matters/{matter_id}/groups` with the name.
  2. Server creates the group (via `find_or_create`) and responds with the
     refreshed `<select>` fragment, with the new group selected and persisted
     as the file's `pinned_group_id`.

Per-CLAUDE.md, all interactivity is wired via `data-*` attributes and delegated
listeners in `static/app.js` (lines 225–275 pattern). No inline `onclick=` /
`onchange=`.

### Item edit form (`src/cvp/templates/_item_row_edit.html`)

Add a Group field:

- `<select>` populated with the matter's groups plus `(none)` (default) and
  `+ New group…` sentinel.
- Choosing `+ New group…` swaps in a text input (HTMX) where the user types the
  new name; on save, the items router calls `find_or_create` first, then sets
  `item.group_id`.

### Rooms & Groups tab (`src/cvp/templates/_tab_rooms.html`)

- Rename the tab label from "Rooms" to "Rooms & Groups" in
  `matter_detail.html`. The template filename and router path stay the same to
  avoid churn.
- Add a "Groups" panel below the existing rooms panel:
  - Header + create form (name input, Add button), HTMX-driven; mirrors the
    rooms create UX.
  - List of groups: each row shows name (inline-editable), item count, and a
    delete button with a confirmation step. Item count = `COUNT(items WHERE group_id = g.id)`.
  - Delete triggers `DELETE /matters/{id}/groups/{group_id}`; on success, the
    panel re-renders. Items keep their data but lose their group reference via
    `ON DELETE SET NULL`.

## Endpoints

New router: `src/cvp/routers/groups.py` (keeps `rooms.py` focused per the
under-200-lines convention).

| method | path                                                    | purpose                              |
|--------|---------------------------------------------------------|--------------------------------------|
| POST   | `/matters/{matter_id}/groups`                           | Create a group (uses `find_or_create`) |
| PATCH  | `/matters/{matter_id}/groups/{group_id}`                | Rename                               |
| DELETE | `/matters/{matter_id}/groups/{group_id}`                | Delete                               |
| PATCH  | `/matters/{matter_id}/evidence/{file_id}/group`         | Set / clear `pinned_group_id`        |

The existing item update handler (in `routers/items.py`) is extended:

- Accepts `group_id` (existing group) or `new_group_name` (string). If
  `new_group_name` is present and non-empty, the handler calls `find_or_create`
  before assigning `item.group_id`.
- Sending `group_id=""` clears the item's group (sets `item.group_id` to NULL).
  Same convention applies to `PATCH /evidence/{file_id}/group` for clearing
  the file's pinned group.

All endpoints follow the existing auth/RBAC patterns used by `rooms.py` and
`evidence.py`. Routes require an authenticated user with access to the matter.

## Migration

Single Alembic revision (`uv run alembic revision --autogenerate -m "add item groups"` followed by manual review):

1. Create `groups` table with columns above.
2. Add `items.group_id` (nullable, FK with `ON DELETE SET NULL`).
3. Add `evidence_files.pinned_group_id` (nullable, FK with `ON DELETE SET NULL`).
4. Index `groups.matter_id`; unique index on `(matter_id, name_normalized)`.
5. No data backfill — every new column defaults to NULL.

## Tests

`tests/` mirrors `src/cvp/`:

- `tests/services/test_groups.py`
  - `find_or_create` happy path
  - dedupe: `"12"`, `" 12 "`, `"12 "` collapse; `"Box A"` vs `"box a"` collapse
  - empty / whitespace-only name raises `ValueError`
  - `IntegrityError` race is recovered by re-query
- `tests/services/test_vision_worker_groups.py`
  - pinned set, placard empty → items get pinned group
  - pinned set, placard present and conflicting → pinned wins; INFO log emitted
  - pinned NULL, placard present → group created; items tagged
  - pinned NULL, placard empty → items have `group_id IS NULL`
  - two scans with the same placard text reuse the same group row
- `tests/routers/test_groups.py`
  - POST creates and returns group; duplicate POST returns the existing one
  - PATCH renames; DELETE nulls items' `group_id`
  - PATCH evidence group persists `pinned_group_id` and clears on `""`
  - Permissions: another matter's user gets 403/404
- `tests/routers/test_items_group_assignment.py`
  - PATCH item with `new_group_name` creates and assigns
  - PATCH item with `group_id=""` clears the assignment
- `tests/templates/test_tab_rooms.py` (or extend the existing tab test)
  - Rooms & Groups panel renders with item counts

Vision API calls remain mocked, per project convention.

## Risks and open questions

- **Placard OCR variance.** Hand-written placards may be misread by the model
  (`"l2"` vs `"12"`). The dedupe rule helps with case/whitespace only.
  Mitigation: surface the auto-created group in the dropdown immediately so the
  specialist sees it and can rename / merge. Merge tooling is out of scope for
  v0 — flagged as backlog if it becomes painful.
- **Per-model schema support.** Not every vision adapter may support a custom
  top-level field cleanly. The adapters layer must normalize so the worker
  sees a uniform `placard_text` regardless of the underlying model. Adapters
  that can't be made to return structured output fall back to parsing
  `placard_text: ...` from the raw text response.
- **Rescan semantics.** Rescanning an image creates fresh items today; this
  spec does not retag previously-extracted items. If a specialist changes the
  dropdown after the first scan and rescans, only the new items inherit the
  new group. Acceptable for v0.

## Out of scope (backlog)

- Items tab gains a Group column + filter.
- Group display in PDF / CSV exports.
- Group merge / split tooling.
- Per-room placard scope.
- Multiple placards in one image.
