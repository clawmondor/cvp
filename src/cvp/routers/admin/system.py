"""System Admin panel router."""

import csv
import datetime
import io
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException
from fastapi.requests import Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from cvp.auth import generate_invite_code, hash_token
from cvp.db import get_db
from cvp.dependencies import CurrentUser, require_system_admin
from cvp.models import Matter
from cvp.models_audit import AuditLog
from cvp.models_auth import Group, User
from cvp.services.audit import get_client_ip, write_audit_log

BASE_DIR = Path(__file__).parent.parent.parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")

router = APIRouter(prefix="/admin/system")

_CTX = {"panel_color": "slate", "panel_title": "System Administration"}


def _ctx(user: CurrentUser, **kwargs) -> dict[str, object]:
    return {**_CTX, "user": user, **kwargs}


@router.get("/", response_class=HTMLResponse)
def system_dashboard(
    request: Request,
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    user_count = db.query(User).count()
    group_count = db.query(Group).count()
    matter_count = db.query(Matter).count()
    return templates.TemplateResponse(
        request=request,
        name="admin/system/dashboard.html",
        context=_ctx(
            user,
            user_count=user_count,
            group_count=group_count,
            matter_count=matter_count,
            breadcrumbs=[{"label": "System Admin", "url": "/admin/system/"}],
        ),
    )


@router.get("/users", response_class=HTMLResponse)
def system_users(
    request: Request,
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    users = db.query(User).order_by(User.email).all()
    groups = db.query(Group).order_by(Group.name).all()
    return templates.TemplateResponse(
        request=request,
        name="admin/system/users.html",
        context=_ctx(
            user,
            users=users,
            groups=groups,
            breadcrumbs=[
                {"label": "System Admin", "url": "/admin/system/"},
                {"label": "Users", "url": "/admin/system/users"},
            ],
        ),
    )


@router.get("/users/{user_id}", response_class=HTMLResponse)
def system_user_detail(
    user_id: str,
    request: Request,
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    group = db.get(Group, target.group_id) if target.group_id else None
    return templates.TemplateResponse(
        request=request,
        name="admin/system/user_detail.html",
        context=_ctx(
            user,
            target=target,
            group=group,
            breadcrumbs=[
                {"label": "System Admin", "url": "/admin/system/"},
                {"label": "Users", "url": "/admin/system/users"},
                {"label": target.email, "url": f"/admin/system/users/{user_id}"},
            ],
        ),
    )


@router.post("/users/invite", response_class=HTMLResponse)
def system_invite_user(
    request: Request,
    email: str = Form(...),
    display_name: str = Form(...),
    system_role: str = Form(...),
    group_id: str = Form(...),
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    valid_roles = {
        "system_admin",
        "internal_admin",
        "internal_user",
        "specialist",
        "external_admin",
        "external_user",
    }
    if system_role not in valid_roles:
        raise HTTPException(status_code=400, detail="Invalid role")

    existing = db.query(User).filter(User.email == email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    group = db.get(Group, group_id)
    if group is None:
        raise HTTPException(status_code=400, detail="Group not found")

    raw_code = generate_invite_code()
    now_utc = datetime.datetime.now(tz=datetime.timezone.utc)
    new_user = User(
        id=str(uuid.uuid4()),
        email=email,
        display_name=display_name,
        system_role=system_role,
        group_id=group_id,
        invite_code=hash_token(raw_code),
        invite_expires_at=now_utc + datetime.timedelta(days=7),
    )
    db.add(new_user)
    db.commit()

    invite_url = str(request.base_url).rstrip("/") + f"/register/{raw_code}"
    groups = db.query(Group).order_by(Group.name).all()
    users = db.query(User).order_by(User.email).all()
    return templates.TemplateResponse(
        request=request,
        name="admin/system/users.html",
        context=_ctx(
            user,
            users=users,
            groups=groups,
            invite_url=invite_url,
            breadcrumbs=[
                {"label": "System Admin", "url": "/admin/system/"},
                {"label": "Users", "url": "/admin/system/users"},
            ],
        ),
    )


@router.post("/users/{user_id}/deactivate", response_class=HTMLResponse)
def system_deactivate_user(
    user_id: str,
    request: Request,
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    target.is_active = False
    db.commit()
    return system_user_detail(user_id, request, user, db)


@router.post("/users/{user_id}/activate", response_class=HTMLResponse)
def system_activate_user(
    user_id: str,
    request: Request,
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    target.is_active = True
    db.commit()
    return system_user_detail(user_id, request, user, db)


@router.post("/users/{user_id}/reset-mfa")
def system_reset_mfa(
    user_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    admin: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Reset MFA for a user (admin action)."""
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404)
    target.mfa_secret = None
    target.mfa_enabled = False
    db.commit()
    background_tasks.add_task(
        write_audit_log,
        user_id=admin.id,
        action="admin.mfa_reset",
        resource_type="user",
        resource_id=user_id,
        ip_address=get_client_ip(request),
    )
    return RedirectResponse(url=f"/admin/system/users/{user_id}", status_code=303)


@router.post("/users/{user_id}/regenerate-invite", response_class=HTMLResponse)
def system_regenerate_invite(
    user_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    if not target.is_active:
        raise HTTPException(status_code=400, detail="Cannot regenerate invite for an inactive user")

    raw_code = generate_invite_code()
    now_utc = datetime.datetime.now(tz=datetime.timezone.utc)
    target.invite_code = hash_token(raw_code)
    target.invite_expires_at = now_utc + datetime.timedelta(days=7)
    target.password_changed_at = None
    db.commit()

    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="admin.invite_regenerated",
        resource_type="user",
        resource_id=user_id,
        ip_address=get_client_ip(request),
    )

    invite_url = str(request.base_url).rstrip("/") + f"/register/{raw_code}"
    group = db.get(Group, target.group_id) if target.group_id else None
    return templates.TemplateResponse(
        request=request,
        name="admin/system/user_detail.html",
        context=_ctx(
            user,
            target=target,
            group=group,
            invite_url=invite_url,
            breadcrumbs=[
                {"label": "System Admin", "url": "/admin/system/"},
                {"label": "Users", "url": "/admin/system/users"},
                {"label": target.email, "url": f"/admin/system/users/{user_id}"},
            ],
        ),
    )


@router.get("/groups", response_class=HTMLResponse)
def system_groups(
    request: Request,
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    groups = db.query(Group).order_by(Group.name).all()
    return templates.TemplateResponse(
        request=request,
        name="admin/system/groups.html",
        context=_ctx(
            user,
            groups=groups,
            breadcrumbs=[
                {"label": "System Admin", "url": "/admin/system/"},
                {"label": "Groups", "url": "/admin/system/groups"},
            ],
        ),
    )


@router.post("/groups", response_class=HTMLResponse)
def system_create_group(
    request: Request,
    name: str = Form(...),
    kind: str = Form(...),
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    if db.query(Group).filter(Group.name == name).first():
        raise HTTPException(status_code=400, detail="A group with this name already exists")
    group = Group(id=str(uuid.uuid4()), name=name, kind=kind)
    db.add(group)
    db.commit()
    return system_groups(request, user, db)


@router.get("/groups/{group_id}", response_class=HTMLResponse)
def system_group_detail(
    group_id: str,
    request: Request,
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    group = db.get(Group, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    members = db.query(User).filter(User.group_id == group_id).order_by(User.email).all()
    return templates.TemplateResponse(
        request=request,
        name="admin/system/group_detail.html",
        context=_ctx(
            user,
            group=group,
            members=members,
            breadcrumbs=[
                {"label": "System Admin", "url": "/admin/system/"},
                {"label": "Groups", "url": "/admin/system/groups"},
                {"label": group.name, "url": f"/admin/system/groups/{group_id}"},
            ],
        ),
    )


@router.post("/groups/{group_id}/deactivate", response_class=HTMLResponse)
def system_deactivate_group(
    group_id: str,
    request: Request,
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    group = db.get(Group, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    group.is_active = False
    db.commit()
    return system_group_detail(group_id, request, user, db)


@router.get("/matters", response_class=HTMLResponse)
def system_matters(
    request: Request,
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    matters = db.query(Matter).order_by(Matter.status, Matter.target_delivery_date).all()
    return templates.TemplateResponse(
        request=request,
        name="admin/system/matters.html",
        context=_ctx(
            user,
            matters=matters,
            breadcrumbs=[
                {"label": "System Admin", "url": "/admin/system/"},
                {"label": "Matters", "url": "/admin/system/matters"},
            ],
        ),
    )


def _build_audit_query(
    db: Session,
    action: str,
    user_filter: str,
    matter_id: str,
    date_from: str,
    date_to: str,
):
    query = db.query(AuditLog).order_by(AuditLog.created_at.desc())
    if action:
        query = query.filter(AuditLog.action.like(f"{action}%"))
    if user_filter:
        query = query.filter(AuditLog.user_id == user_filter)
    if matter_id:
        query = query.filter(AuditLog.matter_id == matter_id)
    if date_from:
        try:
            dt_from = datetime.datetime.strptime(date_from, "%Y-%m-%d")
            query = query.filter(AuditLog.created_at >= dt_from)
        except ValueError:
            pass
    if date_to:
        try:
            dt_to = datetime.datetime.strptime(date_to, "%Y-%m-%d") + datetime.timedelta(days=1)
            query = query.filter(AuditLog.created_at < dt_to)
        except ValueError:
            pass
    return query


@router.get("/audit", response_class=HTMLResponse)
def audit_log_viewer(
    request: Request,
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
    action: str = "",
    user_filter: str = "",
    matter_id: str = "",
    date_from: str = "",
    date_to: str = "",
    page: int = 1,
) -> HTMLResponse:
    """Filterable audit log viewer with pagination."""
    query = _build_audit_query(db, action, user_filter, matter_id, date_from, date_to)
    per_page = 50
    total = query.count()
    pages = (total + per_page - 1) // per_page
    logs = query.offset((page - 1) * per_page).limit(per_page).all()
    user_ids = {log.user_id for log in logs if log.user_id}
    users_map = (
        {u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()} if user_ids else {}
    )
    return templates.TemplateResponse(
        request=request,
        name="admin/system/audit.html",
        context=_ctx(
            user,
            logs=logs,
            users_map=users_map,
            page=page,
            pages=pages,
            total=total,
            filters={
                "action": action,
                "user_filter": user_filter,
                "matter_id": matter_id,
                "date_from": date_from,
                "date_to": date_to,
            },
            breadcrumbs=[
                {"label": "System Admin", "url": "/admin/system/"},
                {"label": "Audit Log", "url": "/admin/system/audit"},
            ],
        ),
    )


@router.get("/audit/export")
def export_audit_csv(
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
    action: str = "",
    user_filter: str = "",
    matter_id: str = "",
    date_from: str = "",
    date_to: str = "",
) -> StreamingResponse:
    """Export filtered audit logs as CSV."""
    query = _build_audit_query(db, action, user_filter, matter_id, date_from, date_to)
    logs = query.all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "id",
            "user_id",
            "action",
            "resource_type",
            "resource_id",
            "matter_id",
            "detail",
            "ip_address",
            "created_at",
        ]
    )
    for log in logs:
        writer.writerow(
            [
                log.id,
                log.user_id or "",
                log.action,
                log.resource_type,
                log.resource_id or "",
                log.matter_id or "",
                log.detail or "",
                log.ip_address,
                log.created_at.isoformat(),
            ]
        )
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit_log.csv"},
    )
