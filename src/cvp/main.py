from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import selectinload

from cvp.db import SessionLocal
from cvp.models import Matter
from cvp.routers import evidence, items, matters, rooms, vision

BASE_DIR = Path(__file__).parent

app = FastAPI(title="Contents Valuation Prototype")

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.include_router(matters.router)
app.include_router(evidence.router)
app.include_router(rooms.router)
app.include_router(items.router)
app.include_router(vision.router)
templates = Jinja2Templates(directory=BASE_DIR / "templates")


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    db = SessionLocal()
    try:
        matters = (
            db.query(Matter)
            .options(selectinload(Matter.items))
            .order_by(Matter.status, Matter.target_delivery_date)
            .all()
        )
    finally:
        db.close()
    return templates.TemplateResponse(
        request=request, name="dashboard.html", context={"matters": matters}
    )


def run_dev() -> None:
    import uvicorn

    from cvp.config import settings

    uvicorn.run("cvp.main:app", host="127.0.0.1", port=settings.port, reload=True)
