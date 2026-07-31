# Custom CSV Export Templates — Design

**Date:** 2026-07-31
**Status:** Approved (brainstorming), ready for implementation plan
**Area:** `src/cvp` — exports

## Summary

Let a user define named **custom CSV export templates** that are shared across every
claim (matter) in their group. Each template selects which data columns appear, in what
order, with optional renamed headers and arbitrary static columns, plus row-scope
controls (which items to include and how to sort). On the export tab a dropdown picks a
template and produces the CSV, alongside the existing PDF and Xactimate CSV exports.

## Guardrails (non-negotiable)

- **Additive, separate from Xactimate.** The existing `generate_csv` and the immutable
  Xactimate column headers are untouched. Custom exports are a new code path. (CLAUDE.md:
  Xactimate column names must never change — carriers/attorneys match on them.)
- **Confidential header always written.** Every custom CSV begins with the
  `# Confidential — Attorney Work Product | Matter: … | Generated: …` comment line, same
  as the Xactimate export. Not configurable.
- **Currency formats from integer cents at the export layer only.** No floats stored or
  computed. The registry renders `cents → "%.2f"` at emit time.
- **Group-scoped sharing.** A template belongs to a `Group` and is usable on every matter
  where `matter.owner_group_id == template.group_id`.
- **Any user in the group** may create/edit/delete the group's templates.

## Data model (new tables + one Alembic migration)

```
export_templates
  id            (str uuid, pk)
  group_id      (str, FK groups.id, not null)
  name          (str, not null)
  description   (str, default "")
  created_by_id (str, FK users.id, nullable)
  include_needs_review (bool, not null, default false, server_default "0")
  include_excluded     (bool, not null, default false, server_default "0")
  sort_field    (str, not null, default "line_number")  # line_number|room|category|description
  created_at, updated_at (tz-aware UTC)

export_template_columns          # ordered child rows, cascade delete with template
  id           (str uuid, pk)
  template_id  (str, FK export_templates.id, ondelete CASCADE, not null)
  position     (int, not null)          # 0-based order
  field_key    (str, nullable)          # null ⇒ static column
  header_label (str, nullable)          # null ⇒ use the field's default header
  static_value (str, nullable)          # set only when field_key is null
```

**Column invariant** (enforced in the service/validation layer, not just DB): exactly one
of `field_key` / `static_value` is set. `field_key` must exist in the registry.
`header_label` is required (non-empty) for static columns; optional for field columns.

Relational child table (not JSON) to match the codebase's house style (ItemCrop, Room,
etc. are all child tables) and keep Alembic/Postgres simple.

## Field registry — the testable core

New pure module `src/cvp/services/export_fields.py`, styled after `depreciation.py`
(no DB access inside render functions; values come from a pre-built context).

```python
@dataclass(frozen=True)
class ExportField:
    key: str
    default_header: str
    group: str                     # UI section: "Item" | "Money" | "Source" | "Context" | "Matter"
    render: Callable[[RowContext], str]

FIELD_REGISTRY: dict[str, ExportField]  # keyed by field.key
```

`RowContext` bundles the `Item` plus the lookups needed to render context fields:
`room_name`, `category_name`, `item_group_name`, and the `Matter`. Built once per row by
the caller; the registry never queries the DB.

### Catalog (v1)

| group   | key                | default_header   | source / rendering |
|---------|--------------------|------------------|--------------------|
| Item    | line_number        | LineItem         | `item.line_number` |
| Item    | description        | Description      | `item.description` |
| Item    | brand              | Brand            | `item.brand or ""` |
| Item    | model              | Model            | `item.model or ""` |
| Item    | quantity           | Qty              | `item.quantity` |
| Item    | unit               | Unit             | constant `"EA"` |
| Item    | age                | Age              | `int(round(item.age_years))` |
| Item    | condition          | Condition        | `item.condition` |
| Money   | unit_price         | UnitPrice        | `_dollars(item.retail_unit_cents)` |
| Money   | shipping           | Shipping         | `_dollars(item.shipping_cents)` |
| Money   | rcv_total          | Total            | `_dollars(item.rcv_total_cents)` |
| Money   | depreciation       | Depreciation     | `_dollars(rcv_total_cents - acv_total_cents)` |
| Money   | acv_total          | ACV              | `_dollars(item.acv_total_cents)` |
| Source  | match_type         | MatchType        | `item.match_type` |
| Source  | source_retailer    | Retailer         | `item.source_retailer` |
| Source  | source_url         | SourceURL        | `item.source_url` |
| Source  | source_captured_at | SourceCapturedAt | ISO date or `""` |
| Source  | needs_review       | NeedsReview      | `"yes"/"no"` |
| Source  | confirmed_at       | ConfirmedAt      | ISO date or `""` |
| Source  | source_notes       | Notes            | today's Xactimate Notes blob (retailer\|url\|match_type\|Shipping) |
| Source  | item_notes         | ItemNotes        | `item.notes` |
| Context | category           | Category         | category name |
| Context | room               | Room             | room name or `"Unassigned"` |
| Context | item_group         | Group            | on-site item-group name or `""` |
| Matter  | policyholder_name  | Policyholder     | `matter.policyholder_name` (constant per row) |
| Matter  | firm_name          | Firm             | `matter.firm_name` |
| Matter  | attorney_name      | Attorney         | `matter.attorney_name` |
| Matter  | carrier            | Carrier          | `matter.carrier` |
| Matter  | claim_number       | ClaimNumber      | `matter.claim_number` |
| Matter  | policy_number      | PolicyNumber     | `matter.policy_number` |
| Matter  | loss_date          | LossDate         | ISO date or `""` |

Static columns are not registry entries — they render `static_value` verbatim.

## Generation (`csv_export.py`, new function)

```python
def generate_custom_csv(matter_id: str, template_id: str) -> Path
```

1. Load matter (with items, rooms), template, ordered columns, category/item-group maps.
   Validate template belongs to the matter's `owner_group_id`.
2. Row set: start with `confirmed ∧ ¬excluded`; if `include_needs_review` then also keep
   needs_review items (they are still confirmed — this toggle only matters if the row set
   is later broadened; documented so behavior is explicit), if `include_excluded` then also
   keep excluded items. **Precise rule:** an item is included when
   `item.confirmed and (include_excluded or not item.excluded) and (include_needs_review or not item.needs_review)`.
3. Sort by `sort_field` (line_number default; room/category by resolved name; description).
4. Write the Confidential comment line, then a header row (`header_label or default_header`
   per column), then one row per item: each column is `static_value` or
   `FIELD_REGISTRY[field_key].render(ctx)`.
5. Output path `…/exports/{matter_id}/contents_{template_slug}_{YYYYMMDD}.csv`.

## Routers & RBAC

New router `src/cvp/routers/export_templates.py` (keeps `exports.py` under the 200-line
rule):

```
GET    /matters/{matter_id}/export-templates            builder page (group's templates)
POST   /api/matters/{matter_id}/export-templates        create
GET    /api/matters/{matter_id}/export-templates/{tid}  edit form (HTMX partial)
PUT    /api/matters/{matter_id}/export-templates/{tid}  update (name, flags, sort, columns)
DELETE /api/matters/{matter_id}/export-templates/{tid}  delete
```

- **Scope derives from the matter, never from a client-supplied group id.** Every route
  resolves `group_id = matter.owner_group_id`; template queries filter on both `id` and
  `group_id`, so a template id from another group 404s (no IDOR).
- Access gate reuses `require_matter_role(...)`. "Any group member" ⇒ use the same matter
  role that grants access to the export tab; confirm the exact role name against
  `dependencies.py` at build time (the Xactimate export currently requires `manager`; match
  or drop to the lowest role that can already open the matter, per the approved
  "any user in the group" decision).
- One new export endpoint in `exports.py`:
  `POST /api/matters/{matter_id}/exports/custom` (form field `template_id`) →
  `generate_custom_csv` → existing `_export_result_html` + audit log
  `detail={"format": "custom", "template_id": tid}`.

## Builder UI + export dropdown

**`_tab_export.html`** gains a third card, "Custom Export":
- `<select>` of the group's templates + an **Export** button (`hx-post` to
  `/api/matters/{id}/exports/custom`, same result/spinner pattern as the CSV card).
- A "Manage templates →" link to the builder page.

**Builder page** `GET /matters/{id}/export-templates` — two columns:
- **Left:** field catalog grouped by the section headings above; each field is an "Add"
  button (`data-action="add-col"`, `data-field-key=…`).
- **Right:** ordered column list. Each row: field name, editable header-label input,
  **↑ / ↓ / ✕** controls. Static columns get a free-text value input plus a required
  header input. Name, description, the two include-toggles, and the sort dropdown sit at
  the top.
- **"Start from Xactimate layout"** button pre-loads a template matching today's 13
  Xactimate columns, so users clone-and-tweak instead of starting empty.

**Reordering without inline JS** (CSP has no `unsafe-inline`; global rule forbids `onclick`
etc.): use **↑/↓ buttons**, not drag-and-drop. Controls carry `data-action`
(`move-col-up` / `move-col-down` / `remove-col` / `add-col`) handled by a delegated
listener in `app.js` following the existing pattern (lines ~225–275). Reorder mutates the
DOM client-side and renumbers hidden `position` inputs; no per-move server round-trip, no
drag library. The whole builder is one form; Save `PUT`s the full column list, and the
server rewrites the template's child rows transactionally (delete + recreate by position).

## Testing

- `tests/services/test_export_fields.py` — near-full coverage of the registry: every field
  renders expected output for a fixture item; money fields format cents correctly;
  null/empty handling. Pure, no DB (mirrors depreciation tests).
- `tests/services/test_csv_export_custom.py` — `generate_custom_csv` end-to-end against a
  seeded matter: column order, renamed headers, static columns, include-toggles, sort
  field, Confidential header line present.
- `tests/routers/test_export_templates.py` — happy-path create/edit/delete; cross-group
  template id 404s; custom export endpoint returns the download result.

## Out of scope (v1)

- Drag-and-drop reordering (↑/↓ only).
- Per-user (non-shared) templates — templates are group-shared only.
- Custom PDF layouts — CSV only.
- Computed/derived columns beyond the fixed registry and static text.
- Row filtering beyond the two include-toggles (e.g. per-room or per-category filters).
