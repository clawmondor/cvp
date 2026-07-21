"""Evidence file upload, serve, and delete endpoints."""

import mimetypes
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy.orm import Session

from claimos.config import settings
from claimos.db import SessionLocal, get_db
from claimos.dependencies import CurrentUser, require_claim_role
from claimos.models import EvidenceFile
from claimos.services import runtime_config
from claimos.services.audit import get_client_ip, write_audit_log
from claimos.services.evidence_cleanup import delete_evidence_file
from claimos.services.pagination import paginate_by_cursor
from claimos.templating import templates

router = APIRouter()


def _kind_from_mime(mime: str) -> str:
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("video/"):
        return "video"
    if mime == "application/pdf":
        return "pdf"
    return "other"


@router.post("/api/claims/{claim_id}/evidence", response_class=HTMLResponse)
async def upload_evidence(
    request: Request,
    claim_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile,
    user: CurrentUser = Depends(require_claim_role("contributor", "evidence")),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Accept a single evidence file, stream it to disk, return its tile fragment.

    Streaming + per-file requests replace the previous batch endpoint so we
    don't hit Cloudflare's edge timeout on big drops. Concurrency is handled
    by the browser queue in app.js.
    """
    max_mb = runtime_config.get_int(db, "evidence_upload_max_file_mb")
    max_bytes = max_mb * 1024 * 1024
    hard_ceiling = 2 * max_bytes

    # Cheap pre-check: if Content-Length is present and clearly oversize, reject
    # before reading any bytes.
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > hard_ceiling:
        raise HTTPException(status_code=413, detail=f"File exceeds {max_mb} MB cap")

    upload_base = Path(settings.upload_dir).resolve()
    claim_dir = upload_base / claim_id
    claim_dir.mkdir(parents=True, exist_ok=True)

    raw_name = Path(file.filename or "file").name
    uid8 = str(uuid.uuid4())[:8]
    stored_name = f"{uid8}_{raw_name}"
    dest = claim_dir / stored_name

    # Stream to disk in 1 MB chunks, enforcing the size cap as we go.
    bytes_written = 0
    chunk_size = 1 << 20  # 1 MB
    try:
        with dest.open("wb") as out:
            while True:
                chunk = await file.read(chunk_size)
                if not chunk:
                    break
                bytes_written += len(chunk)
                if bytes_written > max_bytes:
                    out.close()
                    dest.unlink(missing_ok=True)
                    raise HTTPException(status_code=413, detail=f"File exceeds {max_mb} MB cap")
                await run_in_threadpool(out.write, chunk)
    except HTTPException:
        raise
    except Exception:
        dest.unlink(missing_ok=True)
        raise

    mime = file.content_type or (mimetypes.guess_type(raw_name)[0] or "")
    ef = EvidenceFile(
        claim_id=claim_id,
        filename=raw_name,
        stored_path=f"{claim_id}/{stored_name}",
        mime_type=mime,
        size_bytes=bytes_written,
        kind=_kind_from_mime(mime),
    )

    write_db = SessionLocal()
    try:
        write_db.add(ef)
        write_db.commit()
        write_db.refresh(ef)
    finally:
        write_db.close()

    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="evidence.create",
        resource_type="evidence",
        resource_id=ef.id,
        claim_id=claim_id,
        ip_address=get_client_ip(request),
    )

    return HTMLResponse(
        templates.get_template("_evidence_tile.html").render(f=ef, claim_id=claim_id)
    )


EVIDENCE_PAGE_SIZE = 24


@router.get("/api/claims/{claim_id}/evidence-grid", response_class=HTMLResponse)
def get_evidence_grid(
    request: Request,
    claim_id: str,
    cursor: str = "",
    user: CurrentUser = Depends(require_claim_role("viewer", "evidence")),
) -> HTMLResponse:
    """Render one cursor-paginated page of evidence tiles + sentinel.

    `cursor` is the ISO timestamp of the oldest tile from the previous page
    (empty string for the first page). Tiles are ordered by `created_at DESC`.
    """
    from datetime import datetime

    cursor_dt = datetime.fromisoformat(cursor) if cursor else None
    db = SessionLocal()
    try:
        rows, next_cursor = paginate_by_cursor(
            db.query(EvidenceFile).filter(EvidenceFile.claim_id == claim_id),
            cursor_col=EvidenceFile.created_at,
            cursor_value=cursor_dt,
            limit=EVIDENCE_PAGE_SIZE,
            order="desc",
        )
    finally:
        db.close()
    next_cursor_str = next_cursor.isoformat() if next_cursor else None
    return HTMLResponse(
        templates.get_template("_evidence_grid_fragment.html").render(
            evidence_files=rows,
            evidence_next_cursor=next_cursor_str,
            claim_id=claim_id,
        )
    )


@router.delete("/api/evidence/{file_id}", response_class=HTMLResponse)
def delete_evidence(
    request: Request,
    file_id: str,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_claim_role("manager", "evidence")),
) -> HTMLResponse:
    claim_id: str | None = None
    db = SessionLocal()
    try:
        ef = db.get(EvidenceFile, file_id)
        if ef is None:
            raise HTTPException(status_code=404, detail="File not found")
        upload_base = Path(settings.upload_dir).resolve()
        crop_base = Path(settings.crop_dir).resolve()
        dest = (upload_base / ef.stored_path).resolve()
        if not dest.is_relative_to(upload_base):
            raise HTTPException(status_code=400, detail="Invalid path")
        claim_id = ef.claim_id
        delete_evidence_file(db, ef, upload_base, crop_base)
    finally:
        db.close()

    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="evidence.delete",
        resource_type="evidence",
        resource_id=file_id,
        claim_id=claim_id,
        ip_address=get_client_ip(request),
    )
    return HTMLResponse("", status_code=200)


@router.post("/api/claims/{claim_id}/evidence/remove-all-images", response_class=HTMLResponse)
def remove_all_images(
    request: Request,
    claim_id: str,
    background_tasks: BackgroundTasks,
    confirm_count: int = Form(...),
    user: CurrentUser = Depends(require_claim_role("manager", "evidence")),
) -> HTMLResponse:
    db = SessionLocal()
    try:
        image_files = (
            db.query(EvidenceFile)
            .filter_by(claim_id=claim_id, kind="image")
            .order_by(EvidenceFile.created_at)
            .all()
        )
        if len(image_files) != confirm_count:
            return HTMLResponse(
                '<p class="text-sm text-red-600">'
                "Count mismatch — please refresh and try again.</p>",
                status_code=409,
            )

        upload_base = Path(settings.upload_dir).resolve()
        crop_base = Path(settings.crop_dir).resolve()
        file_ids = [ef.id for ef in image_files]
        deleted_count = len(file_ids)

        for file_id in file_ids:
            ef = db.get(EvidenceFile, file_id)
            if ef is None:
                continue
            dest = (upload_base / ef.stored_path).resolve()
            if not dest.is_relative_to(upload_base):
                continue
            delete_evidence_file(db, ef, upload_base, crop_base)

        evidence_files = (
            db.query(EvidenceFile)
            .filter_by(claim_id=claim_id)
            .order_by(EvidenceFile.created_at.desc())
            .all()
        )
    finally:
        db.close()

    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="evidence.remove_all_images",
        resource_type="claim",
        resource_id=claim_id,
        claim_id=claim_id,
        ip_address=get_client_ip(request),
        detail={"count": deleted_count},
    )
    return HTMLResponse(
        templates.get_template("_evidence_grid.html").render(
            evidence_files=evidence_files, claim_id=claim_id
        )
    )


@router.get("/files/{claim_id}/{filename:path}")
def serve_file(
    claim_id: str,
    filename: str,
    user: CurrentUser = Depends(require_claim_role("viewer", "evidence")),
) -> FileResponse:
    stored_path = f"{claim_id}/{filename}"
    upload_base = Path(settings.upload_dir).resolve()
    dest = (upload_base / stored_path).resolve()
    # Path-traversal guard
    if not dest.is_relative_to(upload_base):
        raise HTTPException(status_code=400, detail="Invalid path")
    if not dest.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(dest)
