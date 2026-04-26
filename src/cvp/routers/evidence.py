"""Evidence file upload, serve, and delete endpoints."""

import mimetypes
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from cvp.config import settings
from cvp.db import SessionLocal
from cvp.dependencies import CurrentUser, require_active_user
from cvp.models import EvidenceFile

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
    matter_id: str,
    files: list[UploadFile],
    user: CurrentUser = Depends(require_active_user),
) -> HTMLResponse:
    upload_base = Path(settings.upload_dir).resolve()
    matter_dir = upload_base / matter_id
    matter_dir.mkdir(parents=True, exist_ok=True)

    db = SessionLocal()
    try:
        for upload in files:
            raw_name = Path(upload.filename or "file").name  # strip any path components
            uid8 = str(uuid.uuid4())[:8]
            stored_name = f"{uid8}_{raw_name}"
            dest = matter_dir / stored_name
            content = await upload.read()
            dest.write_bytes(content)

            mime = upload.content_type or (mimetypes.guess_type(raw_name)[0] or "")
            ef = EvidenceFile(
                matter_id=matter_id,
                filename=raw_name,
                stored_path=f"{matter_id}/{stored_name}",
                mime_type=mime,
                size_bytes=len(content),
                kind=_kind_from_mime(mime),
            )
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

    return HTMLResponse(
        templates.get_template("_evidence_grid.html").render(
            evidence_files=evidence_files, matter_id=matter_id
        )
    )


@router.delete("/api/evidence/{file_id}", response_class=HTMLResponse)
def delete_evidence(file_id: str, user: CurrentUser = Depends(require_active_user)) -> HTMLResponse:
    db = SessionLocal()
    try:
        ef = db.get(EvidenceFile, file_id)
        if ef is None:
            raise HTTPException(status_code=404, detail="File not found")
        upload_base = Path(settings.upload_dir).resolve()
        dest = (upload_base / ef.stored_path).resolve()
        # Path-traversal guard
        if not str(dest).startswith(str(upload_base)):
            raise HTTPException(status_code=400, detail="Invalid path")
        if dest.exists():
            dest.unlink()
        db.delete(ef)
        db.commit()
    finally:
        db.close()

    return HTMLResponse("", status_code=200)


@router.get("/files/{stored_path:path}")
def serve_file(stored_path: str, user: CurrentUser = Depends(require_active_user)) -> FileResponse:
    upload_base = Path(settings.upload_dir).resolve()
    dest = (upload_base / stored_path).resolve()
    # Path-traversal guard
    if not str(dest).startswith(str(upload_base)):
        raise HTTPException(status_code=400, detail="Invalid path")
    if not dest.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(dest)
