"""FastAPI auth dependencies for JWT validation and user context."""

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel

from claimos.auth import decode_access_token
from claimos.config import settings


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


async def _validate_csrf(request: Request, source: str | None) -> None:
    """Validate CSRF double-submit cookie for cookie-based auth.

    Accepts the token from either the X-CSRF-Token header (HTMX requests)
    or a hidden _csrf form field (plain HTML form POSTs).
    Only required for mutating methods when auth came from a cookie.
    """
    if source != "cookie":
        return
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return

    csrf_cookie = request.cookies.get("cvp_csrf", "")
    if not csrf_cookie:
        raise HTTPException(status_code=403, detail="CSRF validation failed")

    # HTMX path: token arrives as a request header
    csrf_header = request.headers.get("x-csrf-token", "")
    if csrf_header and csrf_cookie == csrf_header:
        return

    # Plain form POST path: token arrives as a hidden body field
    content_type = request.headers.get("content-type", "")
    if "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
        form = await request.form()
        csrf_form = str(form.get("_csrf", ""))
        if csrf_form and csrf_cookie == csrf_form:
            return

    raise HTTPException(status_code=403, detail="CSRF validation failed")


def _dev_auto_login_user() -> "CurrentUser | None":
    """In dev with AUTO_LOGIN_USER_ID set, resolve that user from the DB.

    Returns None outside dev, when unconfigured, or when the user is missing.
    """
    if settings.environment == "dev" and settings.auto_login_user_id:
        from claimos.db import SessionLocal
        from claimos.models_auth import User

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
    return None


async def get_current_user(request: Request) -> CurrentUser:
    """Extract and validate JWT from request. Raises 401 if invalid.

    In dev environment with AUTO_LOGIN_USER_ID set, bypasses JWT validation
    and returns the configured user directly from the database.
    """
    dev_user = _dev_auto_login_user()
    if dev_user is not None:
        return dev_user

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
    await _validate_csrf(request, source)

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

    Honors dev auto-login (same as get_current_user). Used for public
    endpoints (like / and /crops/) that work with or without auth.
    """
    dev_user = _dev_auto_login_user()
    if dev_user is not None:
        return dev_user

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

from claimos.db import get_db  # noqa: E402
from claimos.models import Claim  # noqa: E402
from claimos.models_access import ClaimAccess  # noqa: E402
from claimos.models_feedback import Feedback  # noqa: E402

ROLE_HIERARCHY: dict[str, int] = {
    "viewer": 0,
    "editor": 1,
    "contributor": 2,
    "manager": 3,
}


def _check_claim_access(
    db: Session,
    user: CurrentUser,
    claim_id: str,
    minimum_role: str,
) -> bool:
    """Check if user has at least minimum_role on a claim.

    Returns True if access is granted, False otherwise.
    """
    # System admins have implicit manager on everything
    if user.system_role == "system_admin":
        return True

    # Check if user's group owns the claim
    claim = db.get(Claim, claim_id)
    if claim is None:
        return False

    if claim.owner_group_id == user.group_id:
        # Admins get implicit manager on their group's claims
        if user.system_role in ("internal_admin", "external_admin"):
            return True

    # Check explicit claim_access grant
    access = (
        db.query(ClaimAccess)
        .filter(
            ClaimAccess.user_id == user.id,
            ClaimAccess.claim_id == claim_id,
        )
        .first()
    )
    if access is None:
        return False

    return ROLE_HIERARCHY.get(access.role, -1) >= ROLE_HIERARCHY.get(minimum_role, 999)


def require_claim_role(minimum_role: str):
    """Factory that returns a FastAPI dependency requiring a minimum claim role.

    Usage: Depends(require_claim_role("editor"))
    """

    async def dependency(
        request: Request,
        user: CurrentUser = Depends(require_active_user),
        db: Session = Depends(get_db),
    ) -> CurrentUser:
        # Extract claim_id from path params
        claim_id = request.path_params.get("claim_id")

        if claim_id is None:
            # Look up claim via related resource
            item_id = request.path_params.get("item_id")
            if item_id:
                from claimos.models import Item

                item = db.get(Item, item_id)
                if item:
                    claim_id = item.claim_id

            room_id = request.path_params.get("room_id")
            if room_id and not claim_id:
                from claimos.models import Room

                room = db.get(Room, room_id)
                if room:
                    claim_id = room.claim_id

            crop_id = request.path_params.get("crop_id")
            if crop_id and not claim_id:
                from claimos.models import Item, ItemCrop

                crop = db.get(ItemCrop, crop_id)
                if crop:
                    item = db.get(Item, crop.item_id)
                    if item:
                        claim_id = item.claim_id

            file_id = request.path_params.get("file_id")
            if file_id and not claim_id:
                from claimos.models import EvidenceFile

                ef = db.get(EvidenceFile, file_id)
                if ef:
                    claim_id = ef.claim_id

        if claim_id is None:
            raise HTTPException(status_code=404, detail="Resource not found")

        from claimos.services.access_cache import check_claim_access_cached

        if not check_claim_access_cached(db, user, claim_id, minimum_role):
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


def _check_feedback_access(user: CurrentUser, feedback: Feedback) -> bool:
    """Author of the feedback OR a system_admin may read/write/delete it."""
    if user.system_role == "system_admin":
        return True
    return user.id == feedback.author_user_id
