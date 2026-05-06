"""Vision scan endpoints — start scan, poll progress, estimate cost."""

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from cvp.db import SessionLocal
from cvp.dependencies import CurrentUser, require_matter_role
from cvp.models import EvidenceFile
from cvp.models_auth import User
from cvp.models_vision import VisionModel
from cvp.services import vision as vision_svc
from cvp.services.audit import get_client_ip, write_audit_log

BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")

router = APIRouter()


@router.post("/api/matters/{matter_id}/vision-scan", response_class=HTMLResponse)
async def start_scan(
    request: Request,
    matter_id: str,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_matter_role("contributor")),
    evidence_file_ids: list[str] = Form(default=[]),
    model_slug: str = Form(...),
) -> HTMLResponse:
    if not evidence_file_ids:
        return HTMLResponse(
            '<p class="text-sm text-red-600">Select at least one image to scan.</p>'
        )

    db = SessionLocal()
    try:
        vm = db.query(VisionModel).filter_by(slug=model_slug, is_enabled=True).first()
        if vm is None:
            raise HTTPException(400, f"unknown or disabled vision model: {model_slug}")

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

        u = db.query(User).filter_by(id=user.id).first()
        if u is not None:
            u.last_vision_model_slug = model_slug
            db.commit()
    finally:
        db.close()

    if not image_ids:
        return HTMLResponse('<p class="text-sm text-red-600">No image files selected.</p>')

    job_id = vision_svc.create_job(image_ids)
    background_tasks.add_task(vision_svc.run_scan, job_id, matter_id, image_ids, model_slug)
    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="vision.run",
        resource_type="matter",
        resource_id=matter_id,
        matter_id=matter_id,
        ip_address=get_client_ip(request),
        detail=f"model={model_slug}",
    )

    job = vision_svc.get_job(job_id)
    html = templates.get_template("_scan_progress.html").render(
        job_id=job_id, matter_id=matter_id, **job
    )
    return HTMLResponse(html)


@router.get("/api/matters/{matter_id}/vision-scan/{job_id}", response_class=HTMLResponse)
def poll_scan(
    matter_id: str,
    job_id: str,
    user: CurrentUser = Depends(require_matter_role("contributor")),
) -> HTMLResponse:
    job = vision_svc.get_job(job_id)
    if job is None:
        return HTMLResponse('<p class="text-sm text-red-600">Scan job not found.</p>')
    html = templates.get_template("_scan_progress.html").render(
        job_id=job_id, matter_id=matter_id, **job
    )
    return HTMLResponse(html)


@router.get("/api/matters/{matter_id}/vision-scan-estimate", response_class=HTMLResponse)
def estimate(
    matter_id: str,
    count: int,
    model_slug: str,
    user: CurrentUser = Depends(require_matter_role("contributor")),
) -> HTMLResponse:
    label = vision_svc.estimate_cost(count, model_slug)
    return HTMLResponse(f'<span id="cost-estimate" class="text-xs text-gray-500">{label}</span>')
