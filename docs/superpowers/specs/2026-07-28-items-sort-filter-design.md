# Items page: sort & filter — design

**Date:** 2026-07-28
**Branch:** `feat/items-sort-filter` (off `cvp-legacy`)
**Status:** Approved, ready for planning

## Problem

The items table on a matter's Items tab renders in a fixed order (`line_number ASC`)
with cursor-based infinite scroll (50 rows/page). Specialists working a large
inventory can't reorder by value/room/category or narrow to a subset. They need
to sort by any column and filter by room, category, status, and free text.

## Core decisions

1. **Server-side, not client-side.** The DOM only holds ~50 rows at a time, so a
   client-side sort/filter would silently operate on a partial set. Sort/filter
   must run in the query, across the whole matter.
2. **Offset pagination replaces the `line_number` cursor for this list.** Cursor
   pagination is only clean when paging by a single unique column; sorting by
   non-unique columns (Category, Room, RCV total, Condition, …) would require
   compound cursors. Per project scale ("one laptop, a few thousand items,
   don't optimize prematurely") we use `LIMIT/OFFSET`. `paginate_by_cursor`
   stays untouched for its other callers (e.g. evidence).
3. **Totals stay whole-matter.** The Confirmed / RCV total / ACV total summary
   always reflects the full matter regardless of the active filter — these feed
   the report and must not move. A separate "Showing X of Y items" count
   communicates the filtered view.

## Sortable columns

`#` (line_number), Description, Room, Category, Qty, Age, Condition,
RCV/unit (`retail_unit_cents`), RCV total (`rcv_total_cents`),
ACV total (`acv_total_cents`), Status.

- **Condition** sorts by a meaningful `CASE` rank
  (`excellent > above_average > average > below_average`), not alphabetically.
- **Room / Category** sort by name (join), so the ordering is human-legible.
- **Status** sorts by `(excluded, confirmed)` — asc surfaces active-unconfirmed
  rows first (the work queue), desc surfaces excluded/confirmed last.
- Invalid/unknown `sort` value falls back to `line_number ASC`.

## Filters

- `room_id` — exact match (dropdown; includes "— unassigned —").
- `category_id` — exact match (dropdown).
- `status` — one of: `all` (default), `unconfirmed`, `confirmed`, `excluded`,
  `missing_price` (confirmed & not excluded & `retail_unit_cents == 0`).
- `q` — case-insensitive substring match on description / brand / model.

Filters compose (AND). "Clear filters" resets all of them and the sort.

## Query builder

`_build_items_query(db, matter_id, *, room_id, category_id, status, q, sort, dir)`
in `routers/items.py`:

- Starts from `db.query(Item).options(selectinload(Item.crops)).filter(Item.matter_id == matter_id)`.
- Applies each filter when its param is non-empty.
- Applies `ORDER BY` from a whitelist map `{sort_key: column-or-expression}`,
  with `dir` in `{asc, desc}`; appends `Item.id` as a stable tiebreaker so
  offset paging never skips/repeats rows on ties.
- Returns a `Query`; the endpoints apply `.offset(...).limit(...)`.

A companion `_count_items(query)` returns the filtered row count for
"Showing X of Y".

## Endpoints (`routers/items.py`)

- `GET /api/matters/{matter_id}/items-region` **(new)** — renders the full
  swappable region: filter bar + thead (with active-sort arrows) +
  first page of rows + sentinel. Used on every filter/sort change and for the
  initial inline render in the tab. Accepts all sort/filter params (no offset;
  always page 0).
- `GET /api/matters/{matter_id}/items-rows` **(modified)** — rows-only +
  sentinel for a given `offset`, carrying all sort/filter params. Used by the
  scroll sentinel and by app.js refreshes. Replaces the `cursor` param with
  `offset`.

Both parse the same param set via a small `_parse_item_filters(request)` helper
returning a dataclass/dict, so the querystring is built and echoed consistently.

## Templates

- `_items_controls.html` **(new)** — filter bar inside
  `<form id="items-controls" hx-get=".../items-region" hx-target="#items-region"
  hx-swap="outerHTML" hx-trigger="change, keyup changed delay:300ms from:find input[name=q]">`.
  Room/Category/Status selects + search box, preselected from current params.
  Shows "Showing X of Y items" and a "Clear filters" link when any filter is active.
- `_items_head.html` **(new)** — thead; each sortable header is an `hx-get` link
  to `items-region` carrying the current querystring with `dir` flipped for that
  column, plus an ▲/▼ indicator on the active column. Non-sortable columns
  (Photo, Actions) render as plain `<th>`.
- `_items_region.html` **(new)** — wraps controls + `<table>` (thead include +
  `<tbody id="items-tbody">` first page) + within-tbody sentinel, all under
  `id="items-region"`.
- `_tab_items.html` **(modified)** — replace the inline `<table>` block with
  `{% include "_items_region.html" %}`. The "+ Add item" form and
  `_items_summary.html` are unchanged.
- `_items_rows_fragment.html` **(modified)** — the load-more sentinel points at
  `items-rows` with the current querystring + next `offset` instead of `cursor`.

State threading: the endpoints build one `items_qs` querystring (current
filters + sort) and pass it to the templates; header links flip only `dir` for
their own column; the sentinel appends `offset`.

## app.js

- Add `currentItemsQuery()` — serializes `#items-controls` + the active
  sort/dir (read from `data-*` on `#items-region`) into a querystring.
- "View them" (new-scan banner) refresh: re-fetch `#items-region` (outerHTML)
  with `currentItemsQuery()` so surfaced items respect the active view; keep the
  scroll-to-bottom-on-settle behavior, retargeted to the region/tbody.
- item-created / item-updated refreshes reuse the same querystring.

## Known limitation (accepted)

The "+ Add item" form appends the new row to the bottom of the tbody (existing
behavior). Under a non-default sort its visual position is only corrected on the
next region refresh. Acceptable for v0; noted here so it isn't mistaken for a bug.

## Testing

- **Unit — `_build_items_query`:** each filter in isolation and composed; each
  sortable column asc + desc; condition `CASE` order; `q` substring; unknown
  `sort`/`dir` fall back to `line_number asc`; `id` tiebreaker present.
- **Unit — `_count_items`:** filtered count matches.
- **Router happy-path:** `items-region` returns 200 with filters applied and the
  controls preselected; `items-rows?offset=50&sort=…` returns the correct slice
  and a sentinel whose URL preserves the params.
- Totals (`compute_items_totals`) are unaffected — assert they ignore filters.

## Out of scope

- Multi-column sort, saved views, per-user default sort.
- Compound-cursor pagination (approach B) — deferred unless scale demands it.
- Re-sorting the newly added row in place on the client.
