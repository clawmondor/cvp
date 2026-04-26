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

    In dev environment with AUTO_LOGIN_USER_ID set, bypasses JWT validation
    and returns the configured user directly from the database.
    """
    # Dev auto-login: skip JWT validation entirely
    if settings.environment == "dev" and settings.auto_login_user_id:
        from cvp.db import SessionLocal
        from cvp.models_auth import User

        db = SessionLocal()
        try:
            user = db.get(User, settings.auto_login_user_id)
            if user:
                return CurrentUser(
                    id=user.id,
                    email=user.email,
                    system_role=user.system_role,
                    group_id=user.group_id,
                    group_kind=user.group.kind if user.group else None,
                )
        finally:
            db.close()

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


from sqlalchemy.orm import Session  # noqa: E402

from cvp.db import get_db  # noqa: E402
from cvp.models import Matter  # noqa: E402
from cvp.models_access import MatterAccess  # noqa: E402

ROLE_HIERARCHY: dict[str, int] = {
    "viewer": 0,
    "editor": 1,
    "contributor": 2,
    "manager": 3,
}


def _check_matter_access(
    db: Session,
    user: CurrentUser,
    matter_id: str,
    minimum_role: str,
) -> bool:
    """Check if user has at least minimum_role on a matter.

    Returns True if access is granted, False otherwise.
    """
    # System admins have implicit manager on everything
    if user.system_role == "system_admin":
        return True

    # Check if user's group owns the matter
    matter = db.get(Matter, matter_id)
    if matter is None:
        return False

    if matter.owner_group_id == user.group_id:
        # Admins get implicit manager on their group's matters
        if user.system_role in ("internal_admin", "external_admin"):
            return True

    # Check explicit matter_access grant
    access = (
        db.query(MatterAccess)
        .filter(
            MatterAccess.user_id == user.id,
            MatterAccess.matter_id == matter_id,
        )
        .first()
    )
    if access is None:
        return False

    return ROLE_HIERARCHY.get(access.role, -1) >= ROLE_HIERARCHY.get(minimum_role, 999)


def require_matter_role(minimum_role: str):
    """Factory that returns a FastAPI dependency requiring a minimum matter role.

    Usage: Depends(require_matter_role("editor"))
    """

    async def dependency(
        request: Request,
        user: CurrentUser = Depends(require_active_user),
        db: Session = Depends(get_db),
    ) -> CurrentUser:
        # Extract matter_id from path params
        matter_id = request.path_params.get("matter_id")

        if matter_id is None:
            # Look up matter via related resource
            item_id = request.path_params.get("item_id")
            if item_id:
                from cvp.models import Item

                item = db.get(Item, item_id)
                if item:
                    matter_id = item.matter_id

            room_id = request.path_params.get("room_id")
            if room_id and not matter_id:
                from cvp.models import Room

                room = db.get(Room, room_id)
                if room:
                    matter_id = room.matter_id

            crop_id = request.path_params.get("crop_id")
            if crop_id and not matter_id:
                from cvp.models import Item, ItemCrop

                crop = db.get(ItemCrop, crop_id)
                if crop:
                    item = db.get(Item, crop.item_id)
                    if item:
                        matter_id = item.matter_id

            file_id = request.path_params.get("file_id")
            if file_id and not matter_id:
                from cvp.models import EvidenceFile

                ef = db.get(EvidenceFile, file_id)
                if ef:
                    matter_id = ef.matter_id

        if matter_id is None:
            raise HTTPException(status_code=404, detail="Resource not found")

        if not _check_matter_access(db, user, matter_id, minimum_role):
            raise HTTPException(status_code=403, detail="Insufficient permissions")

        return user

    return dependency


async def require_group_admin(
    user: CurrentUser = Depends(require_active_user),
) -> CurrentUser:
    """Require the user to be an admin (system, internal, or external)."""
    if user.system_role not in ("system_admin", "internal_admin", "external_admin"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return user
