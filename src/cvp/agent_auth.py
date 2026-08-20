"""Machine authentication for external AI agents via the X-API-Key header."""

import hmac
from datetime import datetime

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from cvp.db import get_db
from cvp.models_agent import AgentKey
from cvp.services.agent_keys import hash_key, parse_prefix


class AgentPrincipal(BaseModel):
    """Context for an authenticated external agent."""

    agent_key_id: str
    name: str


async def require_agent_key(request: Request, db: Session = Depends(get_db)) -> AgentPrincipal:
    """Validate the X-API-Key header. 401 on any failure."""
    raw = request.headers.get("x-api-key", "")
    if not raw:
        raise HTTPException(status_code=401, detail="Missing API key")

    prefix = parse_prefix(raw)
    if prefix is None:
        raise HTTPException(status_code=401, detail="Invalid API key")

    key = db.query(AgentKey).filter(AgentKey.key_prefix == prefix).first()
    if key is None or key.revoked_at is not None:
        raise HTTPException(status_code=401, detail="Invalid API key")

    if not hmac.compare_digest(key.key_hash, hash_key(raw)):
        raise HTTPException(status_code=401, detail="Invalid API key")

    key.last_used_at = datetime.utcnow()
    db.commit()
    return AgentPrincipal(agent_key_id=key.id, name=key.name)
