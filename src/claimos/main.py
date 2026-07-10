from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload

from claimos.config import settings
from claimos.db import get_db
from claimos.dependencies import CurrentUser, require_active_user
from claimos.middleware import SecurityHeadersMiddleware
from claimos.models import Claim
from claimos.models_access import ClaimAccess
from claimos.routers import (
    auth,
    claims,
    comments,
    crops,
    evidence,
    exports,
    feedback,
    health,
    item_groups,
    items,
    profile,
    rooms,
    serp,
    sharing,
    vision,
)
from claimos.routers.admin import feedback as admin_feedback
from claimos.routers.admin import internal as admin_internal
from claimos.routers.admin import org as admin_org
from claimos.routers.admin import runtime_config as admin_runtime_config
from claimos.routers.admin import system as admin_system
from claimos.routers.admin import vision_models as admin_vision_models
from claimos.services import vision_worker
from claimos.theming import theme_class_for

BASE_DIR = Path(__file__).parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    vision_worker.recover_stale_jobs()
    vision_worker.start_worker()
    yield


app = FastAPI(title="ClaimOS", lifespan=lifespan)

# Security headers middleware
app.add_middleware(SecurityHeadersMiddleware, environment=settings.environment)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

_crop_dir = Path(settings.crop_dir).resolve()
_crop_dir.mkdir(parents=True, exist_ok=True)
app.mount("/crops", StaticFiles(directory=_crop_dir), name="crops")

# Health router (public — no auth required, used by Railway healthcheck)
app.include_router(health.router)

# Auth router (public routes — splash, login, register)
app.include_router(auth.router)

# Protected routers
app.include_router(claims.router)
app.include_router(evidence.router)
app.include_router(rooms.router)
app.include_router(item_groups.router)
app.include_router(items.router)
app.include_router(vision.router)
app.include_router(serp.router)
app.include_router(crops.router)
app.include_router(exports.router)
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
templates.env.globals["theme_class"] = theme_class_for


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    request: Request,
    user: CurrentUser = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    if user.system_role == "system_admin":
        all_claims = (
            db.query(Claim)
            .options(selectinload(Claim.items))
            .order_by(Claim.status, Claim.target_delivery_date)
            .all()
        )
    else:
        all_claims = (
            db.query(Claim)
            .options(selectinload(Claim.items))
            .filter(
                or_(
                    Claim.owner_group_id == user.group_id,
                    Claim.id.in_(
                        db.query(ClaimAccess.claim_id).filter(ClaimAccess.user_id == user.id)
                    ),
                )
            )
            .order_by(Claim.status, Claim.target_delivery_date)
            .all()
        )
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"claims": all_claims, "user": user},
    )


def run_dev() -> None:
    import uvicorn

    uvicorn.run("claimos.main:app", host="127.0.0.1", port=settings.port, reload=True)
