from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from cvp.db import SessionLocal
from cvp.models import Matter

BASE_DIR = Path(__file__).parent

app = FastAPI(title="Contents Valuation Prototype")

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    db = SessionLocal()
    try:
        matters = db.query(Matter).order_by(Matter.status, Matter.target_delivery_date).all()
    finally:
        db.close()
    return templates.TemplateResponse(
        request=request, name="dashboard.html", context={"matters": matters}
    )


def run_dev() -> None:
    import uvicorn

    uvicorn.run("cvp.main:app", host="127.0.0.1", port=8000, reload=True)
