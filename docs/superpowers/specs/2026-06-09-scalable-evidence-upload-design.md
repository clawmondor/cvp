# Scalable evidence upload — design

**Status:** approved
**Date:** 2026-06-09
**Author:** chris.mondor@gmail.com (via Claude)
**Related issue:** follow-up to PR #7 (deferred DB session) after 524 timeout on 53-image upload

## Problem

A specialist tried to upload 53 evidence photos (~1 MB each, ~53 MB total) in one drop. The browser fired a single multipart POST to `/api/matters/{matter_id}/evidence`. Cloudflare returned **524** (origin timeout) before the request completed.

PR #7 already removed the DB-connection-during-I/O issue, but it does not address the remaining bottlenecks for batch uploads:

1. **Single huge multipart request.** Cloudflare's edge timeout (~100 s) and request-body limits apply to the whole batch. The bigger the drop, the closer we get to the cliff — and the user has already fallen off it once.
2. **Full-file in-memory reads.** `content = await upload.read()` (evidence.py:55) loads each file fully into a Python `bytes` object before writing. Starlette has already spooled the whole multipart payload before the handler runs.
3. **Blocking sync disk I/O on the event loop.** `dest.write_bytes(content)` (evidence.py:56) is synchronous; with one uvicorn worker the app freezes for the duration.
4. **All-or-nothing semantics.** One slow file fails the entire batch; no retry, no resume, no per-file progress.
5. **Heavyweight response.** The handler re-queries every evidence file for the matter and re-renders the full grid (`_evidence_grid.html`) on every batch upload — the response grows with matter size.

This spec addresses upload only. A companion spec ("Lazy evidence and items pages") handles the post-upload `QueuePool timeout` we saw on the evidence page load, via in-memory auth caching, pagination, and `loading="lazy"` thumbnails.

## Goals

- Uploading 500 × 10 MB images from one drop must succeed without hitting Cloudflare's edge timeout.
- Peak server memory bounded by concurrency × single-file size, not by total batch size.
- One slow/failed file does not fail the batch.
- Per-file progress visible to the user.
- Concurrency cap, per-file size cap, and per-batch file-count cap are runtime-configurable by a system admin without code change or Railway redeploy.

## Non-goals

- Resumable uploads of partially-transferred individual files (i.e. tus / chunked uploads inside a single file). Each file is still a single HTTP request; failed files are retried whole.
- Background workers, job queues, or Redis. Out of scope per `CLAUDE.md` immutable rule #7.
- Direct-to-storage uploads (S3 / R2 / GCS). Out of scope per same rule.
- Pagination, lazy thumbnails, or auth caching — see companion spec.

## Approach

**Browser fans out the batch into one POST per file**, with a small concurrency cap. The server endpoint accepts a single `UploadFile`, streams it to disk in chunks, inserts one row, and returns either a single tile of HTML (HTMX out-of-band swap) or a small JSON payload. When the client queue drains, the client triggers one grid refresh.

**Why not server-side streaming alone:** the 524 is a *Cloudflare* timeout on the request itself. Keeping it as one 53 MB POST means we are always one slow connection away from the same failure regardless of server-side memory work. The only way to make uploads scale with batch size is to make each request small.

## Components

### 1. Runtime configuration

Three settings need to be tunable by a system admin without redeploy:

| Key | Default | Bounds | Purpose |
|---|---|---|---|
| `evidence_upload_concurrency` | 4 | 1–16 | Browser-side in-flight POST cap |
| `evidence_upload_max_file_mb` | 10 | 1–100 | Server-enforced per-file size cap |
| `evidence_upload_max_batch_count` | 500 | 1–5000 | Client-enforced per-drop count cap (server also enforces a hard fail at 2× this number to defend against scripted abuse) |

**Storage.** A new `app_setting` table (`key TEXT PRIMARY KEY`, `value_json TEXT NOT NULL`, `updated_at TIMESTAMPTZ`, `updated_by_user_id TEXT`) holds overrides. A `get_setting(key, default)` helper in `src/cvp/services/runtime_config.py` reads the table with a small in-process TTL cache (30 s) to avoid hitting the DB on every request. Defaults live in `config.py` as new `Settings` fields so env vars still override at startup; the DB value, when present, supersedes the env value.

**Admin surface.** A new `/admin/system/runtime-config` page (system_admin only) following the `vision_models` admin pattern: form-rendered list of settings, edit-in-place, audit-logged on change. No Schema is needed beyond the three keys above for v1; the table is generic enough to accept more later.

**Client delivery.** The current `evidence_upload_concurrency` value is injected into the evidence-tab template as a `data-evidence-upload-concurrency` attribute on the drop zone (server-rendered). The browser reads it once on page load. Changing the value is therefore picked up on the next evidence-tab render — no redeploy, no client cache to bust.

### 2. Server endpoint

Replace the existing batch endpoint `POST /api/matters/{matter_id}/evidence` with a single-file endpoint at the same path that accepts exactly one file per request. (No back-compat shim — the only caller is our own JS.)

Responsibilities:
- Validate the file's size against `evidence_upload_max_file_mb` (use `Content-Length` if present, then re-check during streaming). Reject with `413` and a small HTML error fragment otherwise.
- Validate mime type at the same boundary the existing helper does (`_kind_from_mime`).
- Stream the upload to disk in 1 MB chunks via `shutil.copyfileobj(upload.file, fp, length=1 << 20)`, wrapped in `await run_in_threadpool(...)` so the event loop is not blocked.
- Open a short-lived `SessionLocal()`, insert one `EvidenceFile` row, commit, close. No matter-wide re-query.
- Return a 200 with an HTML fragment containing **only the new tile** (a new `_evidence_tile.html` partial extracted from `_evidence_grid.html`). HTMX inserts it via `hx-swap="beforeend"` on the grid's tile container.
- Audit log the create (same as today) via `background_tasks`.

The endpoint name and verb stay identical so URL inventory does not churn. The signature changes from `files: list[UploadFile]` to `file: UploadFile`.

Server-side hard ceiling: the endpoint also rejects requests whose `Content-Length` exceeds `2 × evidence_upload_max_file_mb` outright, before reading any bytes, as a cheap abuse guard.

### 3. Browser queue

A new `EvidenceUploadQueue` in `app.js` (extending the existing `initEvidenceUpload`, lines 154–183):

- Reads `data-evidence-upload-concurrency` from the drop zone (fallback 4 if missing).
- Reads `data-evidence-upload-max-file-mb` and `data-evidence-upload-max-batch-count` similarly.
- On file selection / drop:
  - Filters out any file larger than the per-file cap, surfaces a per-file error chip immediately.
  - If the remaining count exceeds the batch cap, rejects the whole drop with a single error toast ("Limit is N files per drop. Try smaller batches.") rather than silently truncating.
  - Pushes the rest into a FIFO queue.
- Runs up to `concurrency` workers, each pulling the next file and POSTing it with the CSRF header and the matter's URL.
- Per-file UI state, rendered in a small progress strip above the grid:
  - `queued` (gray dot), `uploading` (blue spinner), `done` (green check, fades out after 2 s), `failed` (red, click to retry).
- On completion of each successful upload, the returned tile fragment is appended to the grid (HTMX `hx-swap-oob` or direct DOM insert).
- When the queue is fully drained (no in-flight, no queued), the client fires a single `htmx.ajax('GET', evidence-grid-url)` to ensure ordering and counts (image_count, unscanned_count) on the surrounding chrome match server state.

CSP compliance: all event wiring is delegated via `data-*` attributes per `CLAUDE.md` rule. No inline handlers.

### 4. Database

One Alembic migration:

- Creates `app_setting` (key, value_json, updated_at, updated_by_user_id).
- No change to `evidence_files`. No data migration needed.

### 5. Audit logging

Existing pattern in `audit.py` is per-file already (we logged once per batch, which was wrong granularity anyway). New endpoint emits one `evidence.create` audit entry per file. No schema change.

## Error handling

- **Per-file 413 (too large)** — surfaces in the strip as "Too large (max N MB)" with no retry.
- **Per-file 4xx other** — surfaces with the response body's error text; retryable.
- **Per-file 5xx / network** — surfaces as "Upload failed — retry"; one-click retry.
- **CSRF rotation mid-batch** — if a single upload returns 403 with `cvp_csrf` mismatch, the queue re-reads the cookie on every retry; no special handling needed.
- **User navigates away mid-batch** — `beforeunload` warning if the queue is not empty.

## Testing

- `tests/test_evidence_upload.py` (new): unit + integration tests for the single-file endpoint covering happy path, oversize rejection, mime detection, CSRF.
- `tests/test_runtime_config.py` (new): unit tests for `get_setting` cache TTL, env-var fallback, DB override.
- Manual: drop 500 × 10 MB synthetic JPEGs, confirm all 500 land, no 524, no QueuePool error (companion spec covers the latter).

## Rollout

Single PR. There is no production-ready "old client" to support — the JS and endpoint ship together. Steps:

1. Add `app_setting` table + migration.
2. Add `runtime_config` service + admin page.
3. Replace evidence endpoint with single-file version.
4. Replace `initEvidenceUpload` with `EvidenceUploadQueue`.
5. Manual QA, then merge.

## Backlog

Items deliberately deferred:

- **Client-side image downscaling.** Big drops are usually iPhone HEICs at 4–8 MB. Optional client-side `<canvas>` downscale to ~2000 px max edge / JPEG quality 0.85 would cut bytes dramatically. Independent win, can ship later.
- **Per-file resumable uploads (tus protocol).** Useful on flaky networks, but a 10 MB cap makes one-shot retries cheap. Defer.
- **Background virus / mime sniffing.** Out of scope here.

## Open questions

None.

## Spec self-review

- Placeholders: none.
- Internal consistency: client cap 500, server cap 2× = 1000, settings bounds 1–5000 (admin can raise client cap up to 5000; server hard ceiling auto-scales as 2×). Consistent.
- Scope: one PR, three new files, one migration, one endpoint replacement, one JS module. Single plan-sized.
- Ambiguity: drop-zone attributes spelled out; tile fragment vs OOB swap noted; CSRF handling explicit. No remaining ambiguity.
