import hashlib
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload

from cvp.config import settings
from cvp.db import get_db
from cvp.dependencies import CurrentUser, require_active_user
from cvp.middleware import SecurityHeadersMiddleware
from cvp.models import Matter
from cvp.models_access import MatterAccess
from cvp.routers import (
    agent,
    auth,
    comments,
    crops,
    evidence,
    export_templates,
    exports,
    feedback,
    health,
    item_groups,
    items,
    matters,
    profile,
    rooms,
    serp,
    sharing,
    vision,
)
from cvp.routers.admin import feedback as admin_feedback
from cvp.routers.admin import internal as admin_internal
from cvp.routers.admin import org as admin_org
from cvp.routers.admin import runtime_config as admin_runtime_config
from cvp.routers.admin import system as admin_system
from cvp.routers.admin import vision_models as admin_vision_models
from cvp.services import vision_worker

BASE_DIR = Path(__file__).parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    vision_worker.recover_stale_jobs()
    vision_worker.start_worker()
    yield


app = FastAPI(title="Contents Valuation Platform", lifespan=lifespan)

# Security headers middleware
app.add_middleware(SecurityHeadersMiddleware, environment=settings.environment)

_STATIC_DIR = BASE_DIR / "static"
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


def _compute_asset_versions() -> dict[str, str]:
    """Short content hash per static JS file, for cache-busting ?v= query strings.

    Templates reference these via ``request.app.state.asset_versions``. When a file's
    content changes, its hash changes, so browsers and Cloudflare fetch the new URL
    instead of serving a stale cached copy.
    """
    versions: dict[str, str] = {}
    for path in _STATIC_DIR.glob("*.js"):
        versions[path.name] = hashlib.md5(path.read_bytes()).hexdigest()[:8]
    return versions


# Computed once at startup; dev autoreload restarts the process on file changes.
app.state.asset_versions = _compute_asset_versions()

_crop_dir = Path(settings.crop_dir).resolve()
_crop_dir.mkdir(parents=True, exist_ok=True)
app.mount("/crops", StaticFiles(directory=_crop_dir), name="crops")

# Health router (public — no auth required, used by Railway healthcheck)
app.include_router(health.router)

# Auth router (public routes — splash, login, register)
app.include_router(auth.router)

# Protected routers
app.include_router(matters.router)
app.include_router(evidence.router)
app.include_router(rooms.router)
app.include_router(item_groups.router)
app.include_router(items.router)
app.include_router(vision.router)
app.include_router(agent.router)
app.include_router(serp.router)
app.include_router(crops.router)
app.include_router(exports.router)
app.include_router(export_templates.router)
app.include_router(sharing.router)
app.include_router(comments.router)
app.include_router(feedback.router, dependencies=[Depends(require_active_user)])
app.include_router(profile.router)
app.include_router(admin_system.router)
app.include_router(admin_internal.router)
app.include_router(admin_org.router)
app.include_router(admin_vision_models.router)
app.include_router(admin_runtime_config.router)
app.include_router(admin_feedback.router, dependencies=[Depends(require_active_user)])

templates = Jinja2Templates(directory=BASE_DIR / "templates")


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    request: Request,
    user: CurrentUser = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    if user.system_role == "system_admin":
        all_matters = (
            db.query(Matter)
            .options(selectinload(Matter.items))
            .order_by(Matter.status, Matter.target_delivery_date)
            .all()
        )
    else:
        all_matters = (
            db.query(Matter)
            .options(selectinload(Matter.items))
            .filter(
                or_(
                    Matter.owner_group_id == user.group_id,
                    Matter.id.in_(
                        db.query(MatterAccess.matter_id).filter(MatterAccess.user_id == user.id)
                    ),
                )
            )
            .order_by(Matter.status, Matter.target_delivery_date)
            .all()
        )
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"matters": all_matters, "user": user},
    )


def run_dev() -> None:
    import uvicorn

    uvicorn.run("cvp.main:app", host="127.0.0.1", port=settings.port, reload=True)
