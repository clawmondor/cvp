# Bulk Evidence Scan and Remove

**Date:** 2026-05-22
**Status:** Draft

## Problem

The evidence tab currently supports two per-image actions: **Scan Now** (vision scan of a single image) and **✕** (delete a single evidence file). A specialist working a matter with dozens or hundreds of photos must click each one individually. There is no way to:

1. Kick off a vision scan against every unscanned image in a matter in one action.
2. Remove every image from a matter in one action (e.g., when restarting evidence collection).

The naive fix — loop the existing per-image calls — has three problems on Railway's limited memory/vCPU instance:

- **Job state lives in an in-memory dict** (`src/cvp/services/vision.py:30`). A Railway worker restart mid-scan loses all progress and the user must retry the entire batch.
- **The progress UI relies on that in-memory dict.** Closing the tab or hitting a different worker drops the user's visibility into the job.
- **Failures vanish.** Today's `_jobs[id]["errors"]` list is wiped on restart and not visible after the user navigates away. Failed images silently stay as `scanned=False` with no surfaced reason.

We also have a latent bug: single-image delete (`src/cvp/routers/evidence.py:100`) does not cascade. Deleting an image leaves orphan `Item` rows and `ItemCrop` files on disk pointing at a deleted `EvidenceFile`.

## Design

### High-level

- Replace the in-memory `_jobs` dict with two new DB tables: `vision_jobs` and `vision_job_images`.
- One persistent background worker thread, started at app boot, processes `pending` images one at a time. It blocks on a `threading.Event` when the queue is empty — zero CPU and zero DB queries while idle.
- Two new bulk endpoints alongside existing per-image endpoints: `POST .../vision-scan-all` and `POST .../evidence/remove-all-images`.
- Per-image scan failures persist as `vision_job_images.error_message`, surfaced on the evidence card and in a matter-level banner.
- Pre-scan image downscaling: only images **larger than 1 MB** are resized to long-edge 1568px, JPEG quality 85, before being sent to the vision API.
- Individual delete and bulk delete share one cascade routine that removes dependent `Item`, `ItemCrop` (rows and crop files on disk), and `VisionRun` records (the last already cascades via existing FK).

### 1. Data model

Two new tables, one migration.

**`vision_jobs`**
| Column | Type | Notes |
|---|---|---|
| `id` | UUID string PK | |
| `matter_id` | FK → `matters.id` | |
| `model_slug` | string | The vision model selected at job creation. |
| `status` | string | `running` \| `done` \| `error`. Job is `done` once all images are non-pending. |
| `created_by_user_id` | FK → `users.id` | |
| `created_at` | DateTime | server default `now()` |
| `completed_at` | DateTime, nullable | set when status transitions out of `running` |

**`vision_job_images`**
| Column | Type | Notes |
|---|---|---|
| `id` | UUID string PK | |
| `job_id` | FK → `vision_jobs.id`, ON DELETE CASCADE | |
| `evidence_file_id` | FK → `evidence_files.id`, ON DELETE CASCADE | |
| `status` | string | `pending` \| `running` \| `done` \| `error` |
| `error_message` | Text, nullable | populated on failure |
| `items_created` | int, default 0 | |
| `created_at` | DateTime | server default `now()` |
| `started_at` | DateTime, nullable | when worker picked it up |
| `completed_at` | DateTime, nullable | success or failure |

Indexes:
- `vision_job_images(status, created_at)` — supports the worker's "pick oldest pending" query.
- `vision_job_images(evidence_file_id)` — supports the evidence-card per-image error lookup.
- `vision_jobs(matter_id, created_at DESC)` — supports the matter-level banner lookup.

We keep the existing `VisionRun` table unchanged. `VisionRun` records the *successful* outcome of one scan (raw response, items created, cost). `vision_job_images` records the *attempt* (including failures). A successful scan writes both rows.

### 2. Worker loop — idle-stopping

A single module-level worker thread, started at app boot in `src/cvp/main.py` lifespan startup. Lives in `src/cvp/services/vision_worker.py`.

```python
_wake = threading.Event()
_thread: threading.Thread | None = None

def wake() -> None:
    _wake.set()

def start_worker() -> None:
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _thread = threading.Thread(target=_loop, daemon=True, name="vision-worker")
    _thread.start()

def _loop() -> None:
    while True:
        item = _claim_next_pending()  # SELECT ... FOR UPDATE SKIP LOCKED on Postgres
        if item is None:
            _wake.clear()
            _wake.wait()
            continue
        _process(item)
        time.sleep(0.5)  # CLAUDE.md rule #8
```

`_claim_next_pending` runs in its own short transaction: select the oldest `pending` row, update to `running` with `started_at = now()`, commit. On Postgres we use `SELECT ... FOR UPDATE SKIP LOCKED` so the query is safe even if multiple workers ever existed (defense in depth — we only run one). On SQLite (dev) the same query without the locking clause is fine because we're single-threaded.

`_process(item)` performs the existing scan logic (open image, optionally downscale, call OpenRouter, parse response, create `Item`s and `ItemCrop`s, write `VisionRun`, set `EvidenceFile.scanned = True`). Wraps everything in try/except so one bad image cannot kill the thread. On exception: rollback, set `vision_job_images.status = 'error'` and `error_message`, leave `EvidenceFile.scanned = False`.

After `_process`, if there are no more pending images in the parent `vision_jobs` row, set the job's `status = 'done'` (or `error` if any of its images errored) and `completed_at = now()`.

**Who calls `wake()`:**
- `POST /api/matters/{id}/vision-scan` (existing — modified)
- `POST /api/matters/{id}/vision-scan-all` (new)
- App startup, after restart recovery (see §3)

### 3. Restart recovery

At app startup, before `start_worker()`:

```python
db.query(VisionJobImage).filter_by(status="running").update({"status": "pending"})
db.commit()
wake()  # in case anything was actually pending
```

A row left in `running` means a previous worker died mid-scan. We don't know how far it got, but the scan is idempotent enough — at worst, a duplicate API call against the same image, which creates duplicate `Item`s. To avoid duplicates, `_process` first checks: if `EvidenceFile.scanned == True` for this `evidence_file_id`, mark the job image `done` with `items_created=0` and skip. This handles the race where the prior worker committed the `VisionRun` and `ef.scanned = True` but crashed before marking the job image `done`.

### 4. Image downscaling (>1 MB only)

In `services/vision.py`, before the existing OpenRouter call:

```python
image_bytes = image_path.read_bytes()
if len(image_bytes) > 1_000_000:
    image_bytes, mime = _downscale(image_bytes)
```

`_downscale` opens the image with PIL, resizes to long-edge 1568px (preserving aspect ratio) only if either dimension exceeds 1568, re-encodes as JPEG quality 85, returns `(bytes, "image/jpeg")`. Bounding-box adapter math already uses `img_width`/`img_height` from the *original* image — the downscaled bytes go to the API, but coordinates are interpreted against the original dimensions. Most vision models accept this.

**Important constraint to verify in implementation:** the adapter math in `services/vision_adapters.py` interprets bounding boxes returned by the model relative to the image we sent. If we downscale, the model sees the downscaled dimensions. We pass `img_width`/`img_height` of the **downscaled** image to `build_scan_prompt` and to the adapter, then scale the resulting bbox back up to the original dimensions before storing on `ItemCrop`. This keeps `ItemCrop.bbox_*` in original-image coordinates so the existing crop pipeline works unchanged.

### 5. Cascade delete (shared by single + bulk)

New helper in `src/cvp/services/evidence_cleanup.py`:

```python
def delete_evidence_file(db: Session, ef: EvidenceFile, upload_base: Path, crop_base: Path) -> None:
    # 1. Find Items whose ONLY crops point at this evidence file.
    # 2. Delete crop files on disk for ItemCrops on this evidence file.
    # 3. ORM delete the EvidenceFile (cascades to ItemCrop and VisionRun via existing FK config).
    # 4. ORM delete the Items identified in step 1.
    # 5. Delete the EvidenceFile bytes on disk.
```

`EvidenceFile.crops` already has `cascade="all, delete-orphan"` (`models.py:184`), so deleting the file removes its `ItemCrop` rows. We must additionally:
- Delete the **crop image files on disk** (the `crop_path` column points at a file under `crop_dir`).
- Delete the parent `Item` rows when this evidence file was their only source.

"Only source" check: `Item` has many `ItemCrop`s (one per scan that produced it; in practice ~1). If an Item has crops from multiple evidence files, deleting one source leaves the Item with the remaining crops — keep the Item. Today's scan creates exactly one crop per item, so in practice all touched Items will lose their only crop and get deleted with their evidence file.

Both `delete_evidence` (single) and the new bulk endpoint route through this helper.

### 6. Endpoints

**Modified:** `POST /api/matters/{matter_id}/vision-scan` (`routers/vision.py:23`)
- Stop using `BackgroundTasks` and the in-memory `_jobs` dict.
- Insert one `vision_jobs` row and one `vision_job_images` row per selected file.
- Call `vision_worker.wake()`.
- Return the same `_scan_progress.html` partial, now bound to the new `job_id`.

**New:** `POST /api/matters/{matter_id}/vision-scan-all`
- Selects all `EvidenceFile` rows where `matter_id == matter_id`, `kind == "image"`, `scanned == False`.
- Hard cap: 250 images per job. If exceeded, return an inline error explaining the cap and asking the user to scan in batches.
- Otherwise: insert `vision_jobs` row + N `vision_job_images` rows, call `wake()`, return `_scan_progress.html`.
- Role: `contributor` (same as existing single scan).
- Writes one audit log row `vision.run_all` with `detail=model=X count=N`.

**Modified:** `GET /api/matters/{matter_id}/vision-scan/{job_id}`
- Now reads progress from `vision_jobs` + `vision_job_images` joined counts instead of `_jobs[job_id]`.
- Response shape (the template variables) unchanged: `status`, `progress`, `total`, `items_created`, `errors`.

**Modified:** `DELETE /api/evidence/{file_id}` (`routers/evidence.py:100`)
- Routes through the new `evidence_cleanup.delete_evidence_file` helper. Same role, same audit log.

**New:** `POST /api/matters/{matter_id}/evidence/remove-all-images`
- Two-step confirm: the request must include a form field `confirm_count` matching the count of image files in the matter. The UI computes this client-side and submits it; mismatch → 409 with an inline error.
- Iterates `EvidenceFile` rows where `kind == "image"` and routes each through `delete_evidence_file`.
- Role: `manager` (matches today's single-delete role).
- Writes one audit log row `evidence.remove_all_images` with `detail=count=N`.
- Returns the re-rendered `_evidence_grid.html` for HTMX swap.

### 7. UI

**Evidence tab header (`_tab_evidence.html`):** add two buttons above the upload zone, only visible when at least one image file exists in the matter.

```
[ Scan all unscanned (12) ]    [ Remove all images ]
```

The "Scan all unscanned" button is disabled and grayed when the count of `scanned=False` images is zero. The "Remove all images" button opens a confirmation modal: *"Remove all 47 images and their scanned items? This cannot be undone. Type **47** to confirm."* The count is the safety check — required to match the server's `confirm_count` validation.

**Per-image card (`_evidence_grid.html`):** when the latest `vision_job_images` row for this file has `status == "error"`, render a red badge below the "Scan Now" button:

```
[ Scan Now ]
[!] Scan failed: <error message preview, truncated>
```

The full message shows on hover (HTML `title` attribute). The "Scan Now" button remains functional for retry.

**Matter-level banner:** when the matter has a `vision_jobs` row with `status == "done"` or `status == "error"` and at least one image with `status == "error"`, and the user has not yet dismissed it (track via a `dismissed_at` column on `vision_jobs` or, simpler, a session cookie keyed by job id), show a dismissible banner at the top of the evidence tab:

```
Last bulk scan: 47 of 50 succeeded, 3 failed.  [ Details ▾ ]  [ ✕ ]
```

Clicking Details expands an inline list of failed filenames + reasons. For v0, prefer the **session-cookie dismissal** to avoid a schema change just for this UI affordance.

### 8. Concurrency policy

- One worker thread per Railway process. The worker processes images sequentially with a 500ms pause (CLAUDE.md rule #8).
- If two users hit "Scan all" on different matters simultaneously, their `vision_job_images` rows interleave in `created_at` order — both jobs make progress, but only one image at a time is in flight globally. This matches the rule.
- The in-memory `_jobs` dict and `threading.Lock` from today's code are removed entirely.

### 9. Files touched

**New:**
- `src/cvp/services/vision_worker.py` — the worker thread + `wake()` + boot recovery.
- `src/cvp/services/evidence_cleanup.py` — shared cascade-delete helper.
- `alembic/versions/<rev>_vision_job_tables.py` — migration creating `vision_jobs` and `vision_job_images`.

**Modified:**
- `src/cvp/models.py` — add `VisionJob` and `VisionJobImage` ORM models.
- `src/cvp/services/vision.py` — remove in-memory `_jobs` and `run_scan`'s outer loop; expose `process_one_image(job_image_id)` used by the worker. Add `_downscale` for the >1 MB path.
- `src/cvp/routers/vision.py` — `start_scan` writes DB rows + calls `wake()`; `poll_scan` reads DB.
- `src/cvp/routers/evidence.py` — `delete_evidence` and new `remove_all_images` endpoint route through `evidence_cleanup`.
- `src/cvp/main.py` — lifespan startup: run restart recovery, call `start_worker()`.
- `src/cvp/templates/_tab_evidence.html` — bulk buttons.
- `src/cvp/templates/_evidence_grid.html` — failed-scan badge, banner.
- `src/cvp/templates/_scan_progress.html` — no schema change in template variables, but worth a read to ensure it works with the new data source.

### 10. Tests

- `tests/services/test_vision_worker.py` — unit test the worker loop with a fake scan function: assert it processes pending rows in order, idles on empty queue, recovers running→pending on simulated restart.
- `tests/services/test_evidence_cleanup.py` — unit test: deleting an EvidenceFile removes ItemCrop rows, removes Item rows whose only crops pointed at that file, removes crop files on disk, leaves untouched Items alone.
- `tests/services/test_vision_downscale.py` — `_downscale` returns original bytes for ≤1 MB input; for >1 MB returns smaller bytes with long-edge ≤1568px.
- `tests/routers/test_vision_scan_all.py` — happy path: POST scan-all returns a job_id, polling shows progress, DB rows materialize. Cap path: 251 unscanned images → 400 with cap message.
- `tests/routers/test_evidence_remove_all.py` — happy path: with `confirm_count` matching, all images deleted, Items/ItemCrops/files gone, non-image evidence (PDFs, videos) untouched. Mismatch path: 409 with inline error.

Vision API calls are mocked. The 500ms pause is monkey-patched to zero for test speed.

## Scope

- New endpoints for bulk scan and bulk image remove.
- DB-backed persistent job state replacing the in-memory dict.
- Single resumable worker with idle-stopping event-based wake.
- Cascade delete unified between single and bulk paths.
- >1 MB image downscaling.
- UI affordances: bulk buttons, per-card error badge, dismissible matter banner.

## Out of Scope

- Parallel scanning across matters (Approach C from brainstorming). Reconsider once the team grows past 2–3 active specialists.
- Auto-retry of failed images. v0 surfaces the error and lets the user decide.
- Bulk remove of non-image evidence (PDFs, videos). Out of scope; the "Remove all images" action explicitly excludes them.
- Email notifications when a bulk scan finishes. Specialists are working interactively in the app.
- A separate `/admin/vision-jobs` system view. Audit log entries already capture the action.
- Replacing the existing `VisionRun` table or migrating its rows. The two tables coexist; `VisionRun` continues to record successful scan outputs.

## Risks

- **Bounding box coordinate drift after downscale.** If the adapter math is wrong, all crops from downscaled images will be misaligned. Mitigation: explicit unit test covering downscaled-image scan path; manual smoke test with one ≥5 MB photo before merging.
- **Worker thread death.** If `_loop` itself raises (not just inner scan), no more scans happen until app restart. Mitigation: outer `while True` wraps a try/except that logs and continues. Single-image errors are already caught inside.
- **Cascade delete is destructive.** Removing an image deletes user-edited Items if they had no other source. The "type the count to confirm" UI is the safety net. Audit log captures who did it and when.
- **Migration on existing data.** The `vision_jobs` and `vision_job_images` tables start empty. The in-memory `_jobs` state in the running process is lost on deploy, but bulk scans aren't yet a feature so there are no in-flight jobs to migrate.
