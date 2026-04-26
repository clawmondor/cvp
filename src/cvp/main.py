from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import selectinload

from cvp.config import settings
from cvp.db import SessionLocal
from cvp.dependencies import CurrentUser, require_active_user
from cvp.middleware import SecurityHeadersMiddleware
from cvp.models import Matter
from cvp.routers import auth, crops, evidence, exports, items, matters, rooms, serp, vision

BASE_DIR = Path(__file__).parent

app = FastAPI(title="Contents Valuation Platform")

# Security headers middleware
app.add_middleware(SecurityHeadersMiddleware, environment=settings.environment)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

# Auth router (public routes — splash, login, register)
app.include_router(auth.router)

# Protected routers
app.include_router(matters.router)
app.include_router(evidence.router)
app.include_router(rooms.router)
app.include_router(items.router)
app.include_router(vision.router)
app.include_router(serp.router)
app.include_router(crops.router)
app.include_router(exports.router)

templates = Jinja2Templates(directory=BASE_DIR / "templates")


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    request: Request,
    user: CurrentUser = Depends(require_active_user),
) -> HTMLResponse:
    db = SessionLocal()
    try:
        all_matters = (
            db.query(Matter)
            .options(selectinload(Matter.items))
            .order_by(Matter.status, Matter.target_delivery_date)
            .all()
        )
    finally:
        db.close()
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"matters": all_matters, "user": user},
    )


def run_dev() -> None:
    import uvicorn

    uvicorn.run("cvp.main:app", host="127.0.0.1", port=settings.port, reload=True)
