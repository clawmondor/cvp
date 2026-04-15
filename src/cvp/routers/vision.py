"""Vision scan endpoints — start scan, poll progress."""

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from cvp.db import SessionLocal
from cvp.models import EvidenceFile
from cvp.services import vision as vision_svc

BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")

router = APIRouter()


@router.post("/api/matters/{matter_id}/vision-scan", response_class=HTMLResponse)
async def start_scan(
    matter_id: str,
    background_tasks: BackgroundTasks,
    evidence_file_ids: list[str] = Form(default=[]),
) -> HTMLResponse:
    if not evidence_file_ids:
        return HTMLResponse(
            '<p class="text-sm text-red-600">Select at least one image to scan.</p>'
        )

    # Filter to image files only
    db = SessionLocal()
    try:
        files = (
            db.query(EvidenceFile)
            .filter(
                EvidenceFile.id.in_(evidence_file_ids),
                EvidenceFile.matter_id == matter_id,
                EvidenceFile.kind == "image",
            )
            .all()
        )
        image_ids = [f.id for f in files]
    finally:
        db.close()

    if not image_ids:
        return HTMLResponse(
            '<p class="text-sm text-red-600">'
            "No image files selected (only images can be scanned)."
            "</p>"
        )

    job_id = vision_svc.create_job(image_ids)
    background_tasks.add_task(vision_svc.run_scan, job_id, matter_id, image_ids)

    html = templates.get_template("_scan_progress.html").render(
        job_id=job_id, matter_id=matter_id, total=len(image_ids)
    )
    return HTMLResponse(html)


@router.get("/api/matters/{matter_id}/vision-scan/{job_id}", response_class=HTMLResponse)
def poll_scan(matter_id: str, job_id: str) -> HTMLResponse:
    job = vision_svc.get_job(job_id)
    if job is None:
        return HTMLResponse('<p class="text-sm text-red-600">Scan job not found.</p>')

    html = templates.get_template("_scan_progress.html").render(
        job_id=job_id, matter_id=matter_id, **job
    )
    return HTMLResponse(html)
