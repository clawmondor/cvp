"""PDF and CSV export endpoints."""

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import FileResponse, HTMLResponse

from claimos.dependencies import CurrentUser, require_claim_role
from claimos.services import csv_export, pdf_generator
from claimos.services.audit import get_client_ip, write_audit_log

router = APIRouter()


@router.post("/api/claims/{claim_id}/exports/pdf", response_class=HTMLResponse)
def export_pdf(
    request: Request,
    claim_id: str,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_claim_role("manager")),
) -> HTMLResponse:
    try:
        out_path = pdf_generator.generate_pdf(claim_id)
    except Exception as exc:
        return HTMLResponse(
            f'<p class="text-sm text-red-600">PDF generation failed: {exc}</p>',
            status_code=500,
        )
    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="export.download",
        resource_type="claim",
        resource_id=claim_id,
        claim_id=claim_id,
        detail={"format": "pdf"},
        ip_address=get_client_ip(request),
    )
    return HTMLResponse(_export_result_html("PDF", out_path))


@router.post("/api/claims/{claim_id}/exports/csv", response_class=HTMLResponse)
def export_csv(
    request: Request,
    claim_id: str,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_claim_role("manager")),
) -> HTMLResponse:
    try:
        out_path = csv_export.generate_csv(claim_id)
    except Exception as exc:
        return HTMLResponse(
            f'<p class="text-sm text-red-600">CSV generation failed: {exc}</p>',
            status_code=500,
        )
    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="export.download",
        resource_type="claim",
        resource_id=claim_id,
        claim_id=claim_id,
        detail={"format": "csv"},
        ip_address=get_client_ip(request),
    )
    return HTMLResponse(_export_result_html("CSV", out_path))


@router.get("/api/claims/{claim_id}/exports/download")
def download_export(
    request: Request,
    claim_id: str,
    path: str,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_claim_role("manager")),
) -> FileResponse:
    """Serve a generated export file for download."""
    from claimos.config import settings

    export_base = Path(settings.export_dir).resolve()
    dest = (export_base / claim_id / Path(path).name).resolve()
    # Path-traversal guard
    if not str(dest).startswith(str(export_base)):
        return HTMLResponse("Invalid path", status_code=400)
    if not dest.exists():
        return HTMLResponse("File not found", status_code=404)
    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="export.download",
        resource_type="claim",
        resource_id=claim_id,
        claim_id=claim_id,
        detail={"filename": Path(path).name},
        ip_address=get_client_ip(request),
    )
    return FileResponse(dest, filename=dest.name)


def _export_result_html(label: str, path: Path) -> str:
    filename = path.name
    return f"""
<div class="rounded-lg border border-green-200 bg-green-50 p-4 space-y-2">
  <p class="text-sm font-semibold text-green-800">{label} generated successfully</p>
  <p class="text-xs text-green-700 font-mono break-all">{path}</p>
  <a href="/api/claims/placeholder/exports/download?path={filename}"
     class="inline-flex items-center rounded-md bg-green-700 px-3 py-1.5 text-xs
            font-semibold text-white hover:bg-green-600"
     download="{filename}">
    Download {filename}
  </a>
</div>
""".replace("placeholder", path.parent.name)
