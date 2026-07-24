# Claim nickname — design

**Date:** 2026-07-23
**Status:** Approved, ready for implementation plan

## Problem

A claim creator wants to give each claim a short **nickname** that identifies it
wherever multiple claims are displayed (dashboard, team claim tables, admin
pickers). The nickname is defined at claim-creation time and only needs to be
unique within the creator's group.

## Decisions

- **Required.** Every claim has a nickname. Enforced at the DB (`NOT NULL`) and
  in the create/edit form.
- **Unique per group, case-insensitive.** Uniqueness is scoped to
  `Claim.owner_group_id`. `"Smith File"` and `"smith file"` collide within the
  same group; identical nicknames in *different* groups are fine.
- **Primary label.** The nickname becomes the primary identifier in listings and
  the claim header; `policyholder_name` becomes secondary text.
- **Internal only.** The nickname is an internal ops label. It does **not** appear
  in the attorney-facing PDF/CSV report, which stays keyed on `policyholder_name`.
- **Backfill = short id.** Existing claims (live ClaimOS DB and rows copied from
  legacy CVP via `migrate-db`) are backfilled to `Claim <first-8-of-id>`.
  Specialists can rename afterward.

## Data model

Add to `Claim` (`src/claimos/models.py`):

```python
nickname: Mapped[str] = mapped_column(String, nullable=False)
```

- No server default — every write sets it explicitly.
- Trimmed; non-empty after trim; capped at 100 characters (validated in the
  router, not the DB).
- Uniqueness backed by a DB unique index on `(owner_group_id, lower(nickname))`.
  With a `NULL` `owner_group_id`, standard SQL treats each `NULL` as distinct, so
  ungrouped claims never falsely collide; app-level validation matches this
  scoping.

## Migration

Two independent code paths both create existing claims, and both must produce a
valid, unique, non-null nickname.

### 1. Alembic migration (live ClaimOS DB)

1. Add `nickname` column **nullable**.
2. Backfill every existing row: `nickname = 'Claim ' || substr(id, 1, 8)`.
3. Alter column to `NOT NULL`.
4. Create unique index `uq_claims_group_nickname_ci` on
   `(owner_group_id, lower(nickname))`.

`substr(id,1,8)` of a UUID is unique enough within any one group; the unique
index is the backstop for the astronomically unlikely clash.

### 2. `migrate_db.py` (legacy CVP → ClaimOS copy)

The legacy `matters` table has no nickname column, so a straight column copy
would violate `NOT NULL`. The claims copy must inject
`nickname = f"Claim {id[:8]}"` per row. Implement as a small, localized
special-case for the `claims` target table in the copy path (a per-table derive
hook or an explicit branch), not a change to the generic copy behavior for other
tables.

Add a `migrate_db` test asserting every copied claim row has a non-null,
group-unique nickname.

## Create / edit flow

`src/claimos/routers/claims.py`:

- `create_claim` and `update_claim` accept a `nickname: str = Form(...)` field.
- A shared validation helper (pure-ish, unit-testable) enforces:
  - strip whitespace; reject empty → error "Nickname is required";
  - reject length > 100;
  - reject if another claim in the same `owner_group_id` already uses the
    nickname case-insensitively → error "That nickname is already used in your
    group". The helper takes the id of the claim being edited and **excludes it**
    from the collision check so re-saving an unchanged claim passes.
- On **create** validation failure, re-render `claim_new.html` with the error
  message and the user's entered values preserved (no redirect — nothing is
  persisted yet, so the entered values must survive the round-trip).
- On **update** validation failure, nothing is committed (the DB keeps the old
  nickname) and the handler redirects back to `/claims/{claim_id}#overview` with
  an `error` query param; the overview tab renders an error banner. This avoids
  rebuilding the large `claim_detail` render context on the edit path.

## Templates

- **`claim_new.html`** — add a **required** Nickname text input, placed first as
  the claim's primary identifier.
- **`_tab_overview.html`** — add the same Nickname field (editable), with the
  uniqueness/required validation on save.
- **`dashboard.html`** — clickable link text becomes `claim.nickname`;
  `policyholder_name` and firm move to the secondary line. Column header
  "Firm / Policyholder" → "Claim".
- **`claim_detail.html`** — `{% block title %}`, topbar title, and the header use
  `claim.nickname`; policyholder shown as sub-text.
- **`team/_claims_table.html`** — link text uses `c.nickname`.
- **`admin/org/user_detail.html`** — option label uses `claim.nickname`.
- Report templates (`report/preview.html`, `report/pdf.html`) — **unchanged**;
  nickname is internal and must not leak into attorney work product.

## Testing

- **Unit:** the uniqueness/validation helper — case-insensitive match, per-group
  scoping, empty rejection, length cap, and exclusion of the edited claim's own
  id.
- **Integration:** create-with-duplicate-nickname is rejected (form re-rendered
  with error); create-with-unique-nickname succeeds; edit to a colliding
  nickname is rejected; edit that keeps the same nickname succeeds.
- **Migration:** `migrate_db` copy assigns non-null, group-unique nicknames.

## Out of scope

- Nickname in the attorney PDF/CSV report.
- Renaming/uniqueness across groups.
- Any search/filter-by-nickname UI (nicknames are display labels for now).
