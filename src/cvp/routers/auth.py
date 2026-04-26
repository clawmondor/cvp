"""Authentication endpoints: login, logout, register, refresh."""

import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from cvp.auth import (
    create_access_token,
    create_refresh_token_value,
    hash_password,
    hash_token,
    validate_password_strength,
    verify_password,
)
from cvp.config import settings
from cvp.db import get_db
from cvp.models_auth import RefreshToken, User

BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")

router = APIRouter()


def _set_auth_cookies(
    response: Response,
    access_token: str,
    refresh_token: str,
    csrf_token: str,
) -> None:
    """Set JWT access, refresh, and CSRF cookies on a response."""
    response.set_cookie(
        "cvp_access",
        access_token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.jwt_access_ttl_minutes * 60,
        path="/",
        domain=settings.cookie_domain or None,
    )
    response.set_cookie(
        "cvp_refresh",
        refresh_token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        max_age=settings.jwt_refresh_ttl_days * 86400,
        path="/api/auth/refresh",
        domain=settings.cookie_domain or None,
    )
    response.set_cookie(
        "cvp_csrf",
        csrf_token,
        httponly=False,  # JS must read this
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.jwt_access_ttl_minutes * 60,
        path="/",
        domain=settings.cookie_domain or None,
    )


def _clear_auth_cookies(response: Response) -> None:
    """Clear all auth cookies."""
    response.delete_cookie("cvp_access", path="/")
    response.delete_cookie("cvp_refresh", path="/api/auth/refresh")
    response.delete_cookie("cvp_csrf", path="/")


@router.get("/", response_class=HTMLResponse)
def splash(request: Request) -> HTMLResponse | RedirectResponse:
    """Public splash page. In dev with auto_login, redirects to dashboard."""
    if settings.environment == "dev" and settings.auto_login_user_id:
        return RedirectResponse(url="/dashboard", status_code=303)
    return templates.TemplateResponse(request=request, name="splash.html")


@router.get("/login", response_class=HTMLResponse)
def login_page(
    request: Request, next: str = "", error: str = "", message: str = ""
) -> HTMLResponse:
    """Render the login form."""
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"next_url": next, "error": error, "message": message},
    )


@router.post("/api/auth/login")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next: str = Form(""),
    db: Session = Depends(get_db),
) -> RedirectResponse | HTMLResponse:
    """Validate credentials and set auth cookies."""
    email = email.strip().lower()
    user = db.query(User).filter(User.email == email).first()

    if user is None or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": "Invalid email or password.", "next_url": next},
            status_code=401,
        )

    if not user.is_active:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "error": "Account is deactivated. Contact your administrator.",
                "next_url": next,
            },
            status_code=401,
        )

    # Create tokens
    access_token = create_access_token(
        user_id=user.id,
        email=user.email,
        system_role=user.system_role,
        group_id=user.group_id,
        group_kind=user.group.kind if user.group else None,
        secret=settings.jwt_secret,
        ttl_minutes=settings.jwt_access_ttl_minutes,
    )

    raw_refresh = create_refresh_token_value()
    refresh_record = RefreshToken(
        user_id=user.id,
        token_hash=hash_token(raw_refresh),
        expires_at=datetime.now(tz=timezone.utc)
        + timedelta(days=settings.jwt_refresh_ttl_days),
    )
    db.add(refresh_record)

    # Update last_login_at
    user.last_login_at = datetime.now(tz=timezone.utc)
    db.commit()

    # Build response with cookies
    redirect_url = next if next else "/dashboard"
    response = RedirectResponse(url=redirect_url, status_code=303)
    csrf_token = secrets.token_urlsafe(24)
    _set_auth_cookies(response, access_token, raw_refresh, csrf_token)

    return response


@router.post("/api/auth/logout")
def logout(
    request: Request,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Revoke refresh token and clear cookies."""
    refresh_cookie = request.cookies.get("cvp_refresh")
    if refresh_cookie:
        token_hash = hash_token(refresh_cookie)
        rt = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()
        if rt:
            rt.revoked_at = datetime.now(tz=timezone.utc)
            db.commit()

    response = RedirectResponse(url="/", status_code=303)
    _clear_auth_cookies(response)
    return response


@router.post("/api/auth/refresh")
def refresh_token(
    request: Request,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Refresh an access token using the refresh cookie."""
    refresh_cookie = request.cookies.get("cvp_refresh")
    if not refresh_cookie:
        return RedirectResponse(url="/login", status_code=303)

    token_hash = hash_token(refresh_cookie)
    rt = (
        db.query(RefreshToken)
        .filter(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked_at.is_(None),
        )
        .first()
    )

    if rt is None:
        response = RedirectResponse(url="/login", status_code=303)
        _clear_auth_cookies(response)
        return response

    if rt.expires_at and rt.expires_at < datetime.now(tz=timezone.utc):
        rt.revoked_at = datetime.now(tz=timezone.utc)
        db.commit()
        response = RedirectResponse(url="/login", status_code=303)
        _clear_auth_cookies(response)
        return response

    user = db.get(User, rt.user_id)
    if user is None or not user.is_active:
        rt.revoked_at = datetime.now(tz=timezone.utc)
        db.commit()
        response = RedirectResponse(url="/login", status_code=303)
        _clear_auth_cookies(response)
        return response

    # Issue new access token
    access_token = create_access_token(
        user_id=user.id,
        email=user.email,
        system_role=user.system_role,
        group_id=user.group_id,
        group_kind=user.group.kind if user.group else None,
        secret=settings.jwt_secret,
        ttl_minutes=settings.jwt_access_ttl_minutes,
    )

    # Rotate refresh token
    rt.revoked_at = datetime.now(tz=timezone.utc)
    raw_refresh = create_refresh_token_value()
    new_rt = RefreshToken(
        user_id=user.id,
        token_hash=hash_token(raw_refresh),
        expires_at=datetime.now(tz=timezone.utc)
        + timedelta(days=settings.jwt_refresh_ttl_days),
    )
    db.add(new_rt)
    db.commit()

    next_url = request.headers.get("referer", "/dashboard")
    response = RedirectResponse(url=next_url, status_code=303)
    csrf_token = secrets.token_urlsafe(24)
    _set_auth_cookies(response, access_token, raw_refresh, csrf_token)
    return response


@router.get("/register/{invite_code}", response_class=HTMLResponse)
def register_page(
    request: Request, invite_code: str, db: Session = Depends(get_db)
) -> HTMLResponse:
    """Render the registration form for an invite code."""
    code_hash = hash_token(invite_code)
    user = db.query(User).filter(User.invite_code == code_hash).first()

    if user is None:
        return templates.TemplateResponse(
            request=request,
            name="register.html",
            context={"invalid": True, "invite_code": "", "email": ""},
        )

    if user.invite_expires_at and user.invite_expires_at < datetime.now(tz=timezone.utc):
        return templates.TemplateResponse(
            request=request,
            name="register.html",
            context={"invalid": True, "invite_code": "", "email": ""},
        )

    return templates.TemplateResponse(
        request=request,
        name="register.html",
        context={"invalid": False, "invite_code": invite_code, "email": user.email},
    )


@router.post("/api/auth/register")
def register(
    request: Request,
    invite_code: str = Form(...),
    display_name: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    db: Session = Depends(get_db),
) -> RedirectResponse | HTMLResponse:
    """Redeem an invite code and set a password."""
    code_hash = hash_token(invite_code)
    user = db.query(User).filter(User.invite_code == code_hash).first()

    if user is None:
        return templates.TemplateResponse(
            request=request,
            name="register.html",
            context={"invalid": True, "invite_code": "", "email": ""},
        )

    if user.invite_expires_at and user.invite_expires_at < datetime.now(tz=timezone.utc):
        return templates.TemplateResponse(
            request=request,
            name="register.html",
            context={"invalid": True, "invite_code": "", "email": ""},
        )

    if password != password_confirm:
        return templates.TemplateResponse(
            request=request,
            name="register.html",
            context={
                "invalid": False,
                "invite_code": invite_code,
                "email": user.email,
                "error": "Passwords do not match.",
            },
        )

    pw_error = validate_password_strength(password)
    if pw_error:
        return templates.TemplateResponse(
            request=request,
            name="register.html",
            context={
                "invalid": False,
                "invite_code": invite_code,
                "email": user.email,
                "error": pw_error,
            },
        )

    user.display_name = display_name.strip()
    user.password_hash = hash_password(password)
    user.invite_code = None
    user.invite_expires_at = None
    user.password_changed_at = datetime.now(tz=timezone.utc)
    db.commit()

    return RedirectResponse(
        url="/login?message=Account+created.+Please+sign+in.", status_code=303
    )
