"""FastAPI auth dependencies for JWT validation and user context."""

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel

from cvp.auth import decode_access_token
from cvp.config import settings


class CurrentUser(BaseModel):
    """Lightweight user context extracted from JWT — no DB hit."""

    id: str
    email: str
    system_role: str
    group_id: str | None
    group_kind: str | None


def _extract_token(request: Request) -> tuple[str | None, str | None]:
    """Extract JWT from Authorization header or cookie.

    Returns (token, source) where source is 'header', 'cookie', or None.
    Header takes precedence over cookie.
    """
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:], "header"

    cookie_token = request.cookies.get("cvp_access")
    if cookie_token:
        return cookie_token, "cookie"

    return None, None


def _decode_and_build_user(token: str, secret: str) -> "CurrentUser | None":
    """Decode a JWT and build a CurrentUser. Returns None if invalid."""
    payload = decode_access_token(token, secret=secret)
    if payload is None:
        return None
    return CurrentUser(
        id=payload["sub"],
        email=payload["email"],
        system_role=payload["system_role"],
        group_id=payload.get("group_id"),
        group_kind=payload.get("group_kind"),
    )


def _validate_csrf(request: Request, source: str | None) -> None:
    """Validate CSRF double-submit cookie for cookie-based auth.

    Only required for mutating methods (POST, PATCH, PUT, DELETE)
    when auth came from a cookie (not Authorization header).
    """
    if source != "cookie":
        return
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return

    csrf_cookie = request.cookies.get("cvp_csrf", "")
    csrf_header = request.headers.get("x-csrf-token", "")

    if not csrf_cookie or not csrf_header or csrf_cookie != csrf_header:
        raise HTTPException(status_code=403, detail="CSRF validation failed")


async def get_current_user(request: Request) -> CurrentUser:
    """Extract and validate JWT from request. Raises 401 if invalid.

    This is the base dependency — all other auth deps build on it.
    """
    token, source = _extract_token(request)
    if token is None:
        # For HTMX requests, return redirect header
        if request.headers.get("hx-request"):
            raise HTTPException(
                status_code=401,
                headers={"HX-Redirect": "/login"},
            )
        raise HTTPException(status_code=401, detail="Not authenticated")

    user = _decode_and_build_user(token, settings.jwt_secret)
    if user is None:
        if request.headers.get("hx-request"):
            raise HTTPException(
                status_code=401,
                headers={"HX-Redirect": "/login"},
            )
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    # CSRF validation for cookie-based auth on mutating requests
    _validate_csrf(request, source)

    return user


async def require_active_user(
    user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """Require an active, authenticated user. Builds on get_current_user.

    In Phase 2 this will also check user.is_active against the DB.
    For now it just passes through the JWT-validated user.
    """
    return user


async def optional_user(request: Request) -> "CurrentUser | None":
    """Return the current user if authenticated, None otherwise.

    Used for public endpoints (like /crops/) that work without auth.
    """
    token, source = _extract_token(request)
    if token is None:
        return None
    return _decode_and_build_user(token, settings.jwt_secret)


async def require_system_admin(
    user: CurrentUser = Depends(require_active_user),
) -> CurrentUser:
    """Require system_role == 'system_admin'. Used by System Admin panel."""
    if user.system_role != "system_admin":
        raise HTTPException(status_code=403, detail="System admin access required")
    return user
