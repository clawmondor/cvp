# TODO

## Tech debt

### Collapse the double-session pattern in HTTP request handlers

**Context.** Surfaced while debugging the `QueuePool limit ... reached` error
on bulk vision scans (see `src/cvp/db.py` pool sizing and the commit-before-API
fix in `src/cvp/services/vision.py`).

**Problem.** Every authenticated request currently holds two pool connections
concurrently:

1. `require_matter_role` in `src/cvp/dependencies.py` declares
   `db: Session = Depends(get_db)`. FastAPI's generator-yield contract keeps
   that session open for the entire request lifecycle, even though the
   dependency only needs it briefly to check `MatterAccess`.
2. Nearly every router endpoint (`routers/matters.py`, `routers/items.py`,
   `routers/vision.py`, `routers/rooms.py`, `routers/crops.py`,
   `routers/evidence.py`, `routers/serp.py`) then opens its *own*
   `SessionLocal()` for the real work.

Net effect: the effective concurrency ceiling is `pool_size / 2`, not
`pool_size`. The pool bump in `db.py` masks this but doesn't fix it.

**Options to consider.**

- Refactor `require_matter_role` to open a short-lived `SessionLocal()` for
  the access check and close it before yielding, instead of taking
  `Depends(get_db)`.
- Or, migrate router endpoints to use the dependency-injected `db: Session`
  from `Depends(get_db)` and drop the explicit `SessionLocal()` block —
  unifying everything to one session per request. This is the bigger but
  more idiomatic FastAPI change.

**Out of scope** for the bulk-scan fix. Repo-wide; needs its own PR and
careful audit (transaction boundaries differ between dep-injected sessions
and the current explicit-commit patterns).
