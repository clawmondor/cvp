# Live items list — auto-surface new scan / region-rescan items

**Date:** 2026-06-19
**Status:** Approved design, pending implementation plan

## Problem

After a vision scan (single or "scan all") or a region rescan creates draft
items, those items do not appear in the Items tab until the user manually
refreshes the page. Specialists routinely hit F5 to see what a scan produced.

## Goal

When new items are created by a scan or a region rescan, surface them in the
Items tab without a manual page refresh, using an unobtrusive banner the user
opts into ("N new items added — View them"). No new background services, no new
polling loops, no change to currency/audit/depreciation rules.

## Constraints carried from the codebase

- The items list (`#items-tbody`) is **ordered by `line_number` ASC** and is
  **cursor-paginated** (`ITEMS_PAGE_SIZE = 50`) with infinite scroll via a
  `revealed` sentinel row (`_items_rows_fragment.html`).
- New scan/region items always receive the **highest line numbers**, so they
  sort to the **bottom** of the list.
- Full scans run on the **Evidence tab**. Progress lives in `#scan-status`
  (single) and `#scan-all-progress` (bulk), polled every 2s by
  `_scan_progress.html`; the terminal render already knows `items_created`.
- Region rescans run inside the **crop-editor modal**. `crop-editor.js` polls
  `GET /api/matters/{id}/vision-scan/{job_id}/status` (JSON) and already knows
  `d.items_created` on completion.
- The items list is on a **separate tab** (`data-panel="items"`), so the user is
  usually *not* viewing it when a scan finishes.
- The summary totals (Confirmed X of Y, RCV total, ACV total) in
  `_tab_items.html` are rendered **once at page load** from `matters.py`
  context with **no refresh path** — they are already stale after any item
  change (e.g. manual add). CSP forbids inline JS event handlers; all
  interactivity is wired via `data-*` attributes + delegated listeners in
  `app.js`.

## Design

### 1. Completion signal (reuse existing pollers)

Both scan paths already poll to completion. Both will dispatch one
document-level custom event:

```js
document.dispatchEvent(new CustomEvent('cvp:items-added', {
  detail: { matterId, jobId, count }
}));
```

- **Full scan:** `_scan_progress.html` adds, on its terminal (`done` / `error`)
  render, data attributes to the `#scan-status` root:
  `data-scan-state="done|error"`, `data-job-id`, `data-items-created`. In
  `app.js`, an `htmx:afterSwap` listener watches swaps whose target is the
  scan-status root; when it sees a terminal state with a `jobId` not already in
  a `handledScanJobs` Set and `items-created > 0`, it records the job and
  dispatches `cvp:items-added`. (The Set guards against the 2s poll re-firing on
  a state that stays terminal.)
- **Region rescan:** `crop-editor.js`, in `pollRegionJob`, dispatches the same
  `cvp:items-added` event when the job reaches `done` (or `error` with
  `items_created > 0`).

No new endpoints are required for detection; existing pollers carry the data.

### 2. The banner

Add a hidden `#items-new-banner` at the top of `_tab_items.html`, above the
add-item form / table. A delegated `cvp:items-added` handler in `app.js`:

- accumulates a running count (a module-scoped counter, summed across multiple
  jobs that may finish before the user views them),
- sets the banner text to `✦ {n} new item(s) added — View them →`,
- removes the `hidden` class.

The "View them" affordance is a control carrying `data-view-new-items` (and the
matter id via a data attribute), wired through a delegated `click` listener in
`app.js` — no inline handlers. If the user is on another tab, the banner simply
waits on the Items tab for when they switch to it.

### 3. "View them" action

The delegated click handler:

1. `htmx.ajax('GET', '/api/matters/{id}/items-rows', {target:'#items-tbody', swap:'innerHTML'})`
   — a full, dedup-safe reset of the paginated list to page 1 (re-establishes a
   correct cursor/sentinel; avoids the duplication that manual row-appending
   would cause against the forward-only ascending pagination).
2. `htmx.ajax('GET', '/api/matters/{id}/items-summary', {target:'#items-summary', swap:'outerHTML'})`
   — refreshes the totals (see §4).
3. On settle, **scroll the items section to the bottom** so the newest items
   come into view; this reveals the infinite-scroll sentinel and chain-loads
   further pages toward the bottom. For the common one-page case the new items
   are visible immediately; very large matters may need a further scroll (the
   banner is cleared regardless once viewed).
4. Reset the running counter and re-hide the banner.

### 4. Summary totals refresh

Add a small fragment `_items_summary.html` and endpoint
`GET /api/matters/{id}/items-summary` (in `routers/items.py`, `viewer` role)
that renders the Confirmed / RCV total / ACV total block, wrapped in
`#items-summary`. Extract the totals computation currently inline in
`matters.py` into a shared helper so both the full page render and the fragment
use one source of truth. Wrap the existing summary block in `_tab_items.html`
with `id="items-summary"` so it is the swap target.

This endpoint is the **only** new server route. As a bonus it lets the
pre-existing `item-created` HX-Trigger (already emitted by `create_item`) refresh
totals after manual adds — wire `#items-summary` to listen for `item-created`
via `hx-trigger="item-created from:body"`, fixing the current staleness. (This
hookup is in scope but minor.)

### 5. Large-matter visibility (resolved tradeoff)

New items sort to the bottom. Chosen approach: **refresh page 1 + scroll to
bottom** (§3). Rejected alternatives: filtering the list to only the new
batch's items (added complexity, changes list semantics); appending new rows
inline (duplicates against the forward ascending sentinel). A `?job_id` filter
view can be revisited later if large matters prove painful — explicitly
deferred (YAGNI).

## Files touched

- `src/cvp/templates/_scan_progress.html` — terminal-state data attributes.
- `src/cvp/templates/_tab_items.html` — `#items-new-banner`; wrap summary in
  `#items-summary` + `hx-trigger="item-created from:body"`.
- `src/cvp/templates/_items_summary.html` — **new** summary fragment.
- `src/cvp/static/app.js` — `htmx:afterSwap` scan-completion detector +
  `handledScanJobs` Set; `cvp:items-added` banner handler; `data-view-new-items`
  click handler.
- `src/cvp/static/crop-editor.js` — dispatch `cvp:items-added` on region-job
  completion.
- `src/cvp/routers/items.py` — `GET /api/matters/{id}/items-summary`; shared
  totals helper.
- `src/cvp/routers/matters.py` — use the shared totals helper.

## Out of scope

- No live row-by-row streaming during a scan; the banner appears on completion.
- No change to list ordering, page size, or pagination mechanism.
- No `?job_id` filtered review view (deferred).
- No new dependencies, background workers, SSE, or websockets.

## Testing

- `items-summary` endpoint: integration test (happy path) asserting it renders
  current Confirmed/RCV/ACV from the DB and respects `viewer` role.
- Shared totals helper: unit-test the cents arithmetic (confirmed-and-not-excluded
  filter, integer cents only).
- Manual / existing test harness for the JS banner flow (no JS unit harness in
  repo today); verify via the running app per the `verify` workflow.
