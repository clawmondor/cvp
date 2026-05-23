"""Evidence file upload, serve, and delete endpoints."""

import mimetypes
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from cvp.config import settings
from cvp.db import SessionLocal
from cvp.dependencies import CurrentUser, require_matter_role
from cvp.models import EvidenceFile
from cvp.services.audit import get_client_ip, write_audit_log
from cvp.services.evidence_cleanup import delete_evidence_file

BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")

router = APIRouter()


def _kind_from_mime(mime: str) -> str:
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("video/"):
        return "video"
    if mime == "application/pdf":
        return "pdf"
    return "other"


@router.post("/api/matters/{matter_id}/evidence", response_class=HTMLResponse)
async def upload_evidence(
    request: Request,
    matter_id: str,
    background_tasks: BackgroundTasks,
    files: list[UploadFile],
    user: CurrentUser = Depends(require_matter_role("contributor")),
) -> HTMLResponse:
    upload_base = Path(settings.upload_dir).resolve()
    matter_dir = upload_base / matter_id
    matter_dir.mkdir(parents=True, exist_ok=True)

    # Write all files to disk first, building records in memory.
    # Opening the DB session only after I/O is complete prevents holding a
    # pool connection during the (potentially slow) multipart read loop.
    new_records: list[EvidenceFile] = []
    for upload in files:
        raw_name = Path(upload.filename or "file").name  # strip any path components
        uid8 = str(uuid.uuid4())[:8]
        stored_name = f"{uid8}_{raw_name}"
        dest = matter_dir / stored_name
        content = await upload.read()
        dest.write_bytes(content)

        mime = upload.content_type or (mimetypes.guess_type(raw_name)[0] or "")
        new_records.append(
            EvidenceFile(
                matter_id=matter_id,
                filename=raw_name,
                stored_path=f"{matter_id}/{stored_name}",
                mime_type=mime,
                size_bytes=len(content),
                kind=_kind_from_mime(mime),
            )
        )

    db = SessionLocal()
    try:
        for ef in new_records:
            db.add(ef)
        db.commit()

        evidence_files = (
            db.query(EvidenceFile)
            .filter(EvidenceFile.matter_id == matter_id)
            .order_by(EvidenceFile.created_at.desc())
            .all()
        )
    finally:
        db.close()

    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="evidence.create",
        resource_type="evidence",
        resource_id=matter_id,
        matter_id=matter_id,
        ip_address=get_client_ip(request),
    )
    return HTMLResponse(
        templates.get_template("_evidence_grid.html").render(
            evidence_files=evidence_files, matter_id=matter_id
        )
    )


@router.delete("/api/evidence/{file_id}", response_class=HTMLResponse)
def delete_evidence(
    request: Request,
    file_id: str,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_matter_role("manager")),
) -> HTMLResponse:
    matter_id: str | None = None
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
        matter_id = ef.matter_id
        delete_evidence_file(db, ef, upload_base, crop_base)
    finally:
        db.close()

    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="evidence.delete",
        resource_type="evidence",
        resource_id=file_id,
        matter_id=matter_id,
        ip_address=get_client_ip(request),
    )
    return HTMLResponse("", status_code=200)


@router.post("/api/matters/{matter_id}/evidence/remove-all-images", response_class=HTMLResponse)
def remove_all_images(
    request: Request,
    matter_id: str,
    background_tasks: BackgroundTasks,
    confirm_count: int = Form(...),
    user: CurrentUser = Depends(require_matter_role("manager")),
) -> HTMLResponse:
    db = SessionLocal()
    try:
        image_files = (
            db.query(EvidenceFile)
            .filter_by(matter_id=matter_id, kind="image")
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
            .filter_by(matter_id=matter_id)
            .order_by(EvidenceFile.created_at.desc())
            .all()
        )
    finally:
        db.close()

    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="evidence.remove_all_images",
        resource_type="matter",
        resource_id=matter_id,
        matter_id=matter_id,
        ip_address=get_client_ip(request),
        detail={"count": deleted_count},
    )
    return HTMLResponse(
        templates.get_template("_evidence_grid.html").render(
            evidence_files=evidence_files, matter_id=matter_id
        )
    )


@router.get("/files/{matter_id}/{filename:path}")
def serve_file(
    matter_id: str,
    filename: str,
    user: CurrentUser = Depends(require_matter_role("viewer")),
) -> FileResponse:
    stored_path = f"{matter_id}/{filename}"
    upload_base = Path(settings.upload_dir).resolve()
    dest = (upload_base / stored_path).resolve()
    # Path-traversal guard
    if not dest.is_relative_to(upload_base):
        raise HTTPException(status_code=400, detail="Invalid path")
    if not dest.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(dest)
