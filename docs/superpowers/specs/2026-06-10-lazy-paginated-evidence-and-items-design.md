# Lazy & paginated evidence and items pages — design

**Status:** approved
**Date:** 2026-06-10
**Author:** chris.mondor@gmail.com (via Claude)
**Related issue:** follow-up to the post-upload `sqlalchemy.exc.TimeoutError: QueuePool limit of size 10 overflow 20 reached` observed on the evidence page after PR #17 fixed the upload-side 524.

## Problem

After Spec 1 fixed the upload 524, loading the matter's Evidence tab with 50+ images exhausted the SQLAlchemy connection pool:

```
sqlalchemy.exc.TimeoutError: QueuePool limit of size 10 overflow 20 reached,
connection timed out, timeout 10.00
```

Root cause: every `<img src="/files/{matter_id}/{filename}">` thumbnail fires a separate request to `serve_file` (`routers/evidence.py:200`), which calls `require_matter_role("viewer")` → `_check_matter_access` (`dependencies.py:179-215`) → opens a DB session and runs two queries (`Matter.get` + `MatterAccess.filter`). Browsers over HTTP/2 happily fan out 50+ concurrent thumbnail requests, asking for 50+ simultaneous DB sessions while the pool maxes at 30.

Secondary problem on the same screen: `matters.py:123` loads the full `Matter.evidence_files` collection via `selectinload` on every render, and `items.py:86` does the same for `Item` rows. Both grow unbounded with matter size; rendering 200+ tiles or rows is wasted work even before the pool issue.

This spec addresses both — the load-time exhaustion *and* the underlying "render everything" pattern that will keep causing problems as matters grow.

## Goals

- Loading a matter with 500+ evidence files or 1000+ items does not exhaust the SQLAlchemy pool, even on a 2 vCPU / 2 GB Railway box.
- Initial page render is bounded in cost regardless of matter size.
- Pagination is seamless (no clicks to load more on scroll).
- Auth-check staleness after a role revocation is at most 60 s.

## Non-goals

- Deep links to specific pages (`?page=7`). Cursor-based pagination doesn't support this; nobody links to "evidence page 7" today.
- Replacing the cookie-based auth model with signed URLs. Listed as a backlog alternative if the cache shows pain.
- Server-side downscaled thumbnails. Independent win, backlogged.
- Pagination of any other list (rooms, item groups, etc.). The two affected by the incident are evidence and items; out of scope to chase others speculatively.
- Background workers / Redis / additional managed services. Out of bounds per `CLAUDE.md` immutable rule #7.

## Approach

Three independent units, all targeting the same root incident:

1. **In-memory matter-access cache.** Wraps `_check_matter_access` with a 60 s TTL cache keyed on `(user_id, matter_id, minimum_role)`. A 50-thumbnail page burst becomes 1 DB check + 49 cache hits.
2. **Cursor-based pagination + HTMX infinite scroll** for evidence (page size 24) and items (page size 50). First page inlines; subsequent pages load via a sentinel element with `hx-trigger="revealed"`.
3. **Two trivial settings:** `loading="lazy"` and `decoding="async"` on thumbnail `<img>` tags; bump SQLAlchemy pool to 20 + 30 on Postgres.

Each unit is independently revertable but ships in one PR — they all serve the same incident and the auth cache is the load-bearing fix without which pagination alone would still hammer the pool.

## Components

### 1. Access decision cache

**Module:** `src/cvp/services/access_cache.py`.

**Public interface (single function):**

```python
def check_matter_access_cached(
    db: Session,
    user: CurrentUser,
    matter_id: str,
    minimum_role: str,
) -> bool
```

Drop-in replacement at the one call site in `dependencies.py:271`. `_check_matter_access` stays as-is; the cache wrapper calls it on miss.

**Storage.** Single module-level `dict` mapping `(user_id, matter_id, minimum_role) -> (loaded_at, allowed)`. Same pattern as `runtime_config._cache` from Spec 1. No `functools.lru_cache` — we need TTL, not just size eviction.

**TTL:** 60 s, named constant `_TTL_SECONDS`.

**Eviction:** When the cache exceeds 1024 entries, sweep the 256 oldest in a single pass (by `loaded_at`). One-shot batch eviction keeps amortized write cost flat.

**System admin short-circuit.** `_check_matter_access` already returns `True` immediately for `system_role == "system_admin"` (`dependencies.py:190-191`). The cache wrapper checks the same condition *before* hitting the cache so admins never poison or share entries.

**Concurrency.** Uvicorn workers are single-process; FastAPI handlers share one asyncio event loop; CPython dict reads/writes are atomic. No lock needed. If we ever switch to a multi-worker Uvicorn, the worst case is a per-worker cache duplicate — still correct, just less efficient.

**Invalidation helpers:**

```python
def invalidate_matter(matter_id: str) -> None
def invalidate_user(user_id: str) -> None
```

**Wiring of those calls is BACKLOGGED** (see Backlog). For this spec, worst-case staleness after a role revocation is 60 s — acceptable per the brainstorming decision and documented in the in-app help text on the share/revoke screens at implementation time.

**Tests:** hit/miss, TTL expiry (via monkeypatched `_now`), batch eviction at 1024 → 768, system_admin bypass, `invalidate_matter` and `invalidate_user` both clear matching entries.

### 2. Pagination

**Shared helper.** `src/cvp/services/pagination.py`:

```python
def paginate_by_cursor(
    query,
    *,
    cursor_col,
    cursor_value: str | int | None,
    limit: int,
) -> tuple[list, str | None]
```

Applies `cursor_col < cursor_value` when `cursor_value` is not None, orders descending by `cursor_col`, fetches `limit + 1` rows, and returns `(rows[:limit], next_cursor)` where `next_cursor` is the `cursor_col` value of `rows[limit]` if present, else `None`. Pure function, no DB session opened internally.

For evidence the cursor is `EvidenceFile.created_at` (ISO timestamp). For items it's `Item.line_number` (int — and we order *ascending* for items, so the comparator inverts; the helper takes an `order: Literal["asc", "desc"]` arg).

**Evidence endpoint.** `GET /api/matters/{matter_id}/evidence-grid?cursor=<iso-or-empty>&limit=24` in `routers/evidence.py`. Renders a fragment:

```html
{% for f in evidence_files %}{% include "_evidence_tile.html" %}{% endfor %}
{% if next_cursor %}
<div hx-get="/api/matters/{{ matter_id }}/evidence-grid?cursor={{ next_cursor }}"
     hx-trigger="revealed"
     hx-swap="outerHTML"
     class="col-span-full h-4 text-center text-xs text-gray-400">
  Loading…
</div>
{% endif %}
```

The sentinel replaces *itself* with the next batch (`hx-swap="outerHTML"`), which means the new batch's own sentinel (if any) becomes the new bottom of the list. This is the standard HTMX infinite-scroll idiom.

**Items endpoint.** `GET /api/matters/{matter_id}/items?cursor=<line-number-or-empty>&limit=50`. Same shape, sentinel is a `<tr>` instead of a `<div>` to fit inside `<tbody>`:

```html
{% for it in items %}{% include "_item_row.html" %}{% endfor %}
{% if next_cursor %}
<tr hx-get="/api/matters/{{ matter_id }}/items?cursor={{ next_cursor }}"
    hx-trigger="revealed"
    hx-swap="outerHTML">
  <td colspan="N" class="text-center text-xs text-gray-400 py-2">Loading…</td>
</tr>
{% endif %}
```

(`N` = current column count in `_items_tbody.html` — copy the existing colspan if one already exists for empty-state rows.)

**Page-load wiring.** `matters.py:123-228` (the matter detail handler) currently calls `selectinload(Matter.evidence_files)` and passes the full list into the template. Change:

- Drop `selectinload(Matter.evidence_files)` from the eager-load.
- Run the same cursor query the new endpoint uses with `cursor=None, limit=24` to get the first page.
- Pass `evidence_files` (first page only) and `evidence_next_cursor` (str or None) into the template.
- Same treatment for items: replace the `sorted(matter.items, ...)` line with a `paginate_by_cursor(...)` call on `Item.line_number`, ascending, limit 50, and pass `items_next_cursor`.

`_evidence_grid.html` and `_items_tbody.html` get a trailing `{% if next_cursor %}…{% endif %}` sentinel block.

**Post-upload interaction (Spec 1 carries over).** The upload queue in `app.js` already inserts new tiles via OOB swap and fires one `htmx.ajax('GET', evidence-grid-url)` on drain. After this spec, that drain-refresh request hits the new paginated endpoint with no cursor → fetches page 1 → which is what we want (newest first). New tiles added via OOB during upload that happen to be on page 1 will be redrawn from the canonical response; tiles inserted after page 1 will be dropped, which is correct — they'll reappear on scroll. Document this in the spec's "behavior under concurrent uploads" note.

**Tests:**
- `tests/test_pagination.py` — helper unit tests against in-memory SQLite (forward/backward, limit, exhaustion).
- `tests/test_evidence_grid_endpoint.py` — first page returns 24 + sentinel; second page (`cursor=<oldest_in_page>`) returns next 24; last page omits sentinel.
- `tests/test_items_endpoint.py` — same shape with `line_number` cursor.

### 3. Lazy thumbnails + pool bump

- `src/cvp/templates/_evidence_tile.html`: add `loading="lazy"` and `decoding="async"` to the existing `<img>` tag.
- `src/cvp/db.py`: change Postgres engine params from `pool_size=10, max_overflow=20` to `pool_size=20, max_overflow=30`. Keep `pool_timeout=10, pool_recycle=1800, pool_pre_ping=True`.

No tests needed for either change — they're configuration. Verify the matter page still renders in the existing matter-detail test (or add a smoke test if there isn't one).

## Behavior under concurrent uploads

After upload-queue drain, the client fetches page 1 of the evidence grid. If a user is uploading hundreds of files and scrolling at the same time:

- New tiles land in the grid via OOB swap from individual upload responses (Spec 1 behavior).
- Sentinels fire as the user scrolls; each sentinel response is a slice ordered by `created_at desc`.
- Tiles inserted by OOB swap above the current scroll position are not disturbed.
- Tiles inserted *between* sentinel batches (i.e. a tile whose `created_at` falls inside a cursor window the user has already loaded) can appear twice in the DOM, briefly. After the next drain-refresh (the `htmx.ajax` page-1 fetch when the queue is idle), page 1 is canonical again.

This is acceptable: visual de-duping is not worth the complexity; uploads-while-scrolling is a rare combination.

## Data model

No schema changes. No migrations.

## Configuration

No new runtime-config knobs in this spec. Page sizes (24 and 50) and TTL (60 s) are constants in code. If we end up wanting to tune them at runtime, we can add them to the `app_setting` table later — Spec 1's `runtime_config` service already supports arbitrary keys.

## Audit & security

- Cache poisoning: cache key includes `user_id` so one user's grant cannot leak to another. `minimum_role` is also part of the key so a "viewer" grant cached for a "viewer" check is not consulted for a later "manager" check.
- TTL of 60 s ≥ no worse than the same-screen behavior we have today during a 60 s window after a role change. Documented as accepted risk.
- Pagination endpoints inherit `require_matter_role("viewer")` (same as `serve_file`). The cache applies — only the first thumbnail in a burst pays the DB cost.

## Testing strategy

- Unit tests for `access_cache` (5–6 tests), `paginate_by_cursor` (4–5 tests).
- Integration tests for the two new paginated endpoints (3 tests each — first page with sentinel, middle page, last page without sentinel).
- Manual: drop 60 evidence files, reload the matter, scroll. Confirm sentinel fires once per visible threshold, no QueuePool error, image counts on the bulk-action bar match server state.

## Rollout

Single PR. Three commits suggested (one per unit) plus tests, in this order so each is independently revertable:

1. Access cache + integration into `require_matter_role`.
2. Lazy thumbnails + pool bump (trivial).
3. Pagination helper + evidence endpoint + items endpoint + template wiring.

The auth cache alone would likely fix the QueuePool incident; pagination is the durable fix for grid render cost. Lazy + pool are insurance.

## Backlog

- **Short-lived signed URLs as an alternative to the auth cache.** HMAC of `(matter_id, filename, expiry)` baked into thumbnail `src` at page-render time. Eliminates the auth check entirely for `serve_file`. Revisit if (a) the cache shows staleness pain in practice, or (b) we need to share matter URLs with non-cookie clients (e.g. signed report links).
- **Cache invalidation wiring** in `MatterAccess` grant/revoke endpoints and user role-change paths. Without this, worst-case staleness is 60 s after a role change. Acceptable for now; tracked as follow-up because it requires spelunking through the sharing flow that this spec does not otherwise touch.
- **Server-side downscaled thumbnails.** `<img src="/files/...">` currently serves the full-resolution original. A separate `/thumbs/...` endpoint that returns a 256 px JPEG would cut bytes per thumbnail by 10–20×. Independent of pagination/cache; worth doing if Cloudflare cache hits on full-res images turn out poor.
- **Make page sizes runtime-configurable** via the existing `app_setting` table from Spec 1. Defer until we have a reason to tune them.

## Open questions

None.

## Spec self-review

- **Placeholders:** none.
- **Internal consistency:** auth cache 60 s TTL appears in goals, components, and security — consistent. Page sizes 24 (evidence) / 50 (items) consistent throughout. Cursor cols (`created_at` desc for evidence, `line_number` asc for items) consistent.
- **Scope:** one PR, three independently revertable units, ~7 new test files, no migration. Single plan-sized.
- **Ambiguity:** "drop `selectinload(Matter.evidence_files)`" is unambiguous; the items page change is described with the same call site and pattern. The N in items-sentinel `colspan` is parameterized on the existing template's column count — explicit instruction to copy from current code.
