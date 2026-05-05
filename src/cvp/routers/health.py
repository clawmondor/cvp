from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from cvp.db import get_db

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz(session: Session = Depends(get_db)) -> dict[str, str]:
    try:
        session.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="db unhealthy") from exc
    return {"status": "ok"}
