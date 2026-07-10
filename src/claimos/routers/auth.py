"""Authentication endpoints: login, logout, register, refresh."""

import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from claimos.auth import (
    create_access_token,
    create_refresh_token_value,
    hash_password,
    hash_token,
    validate_password_strength,
    verify_password,
)
from claimos.config import settings
from claimos.db import get_db
from claimos.dependencies import CurrentUser, optional_user
from claimos.models_auth import RefreshToken, User
from claimos.services.audit import get_client_ip, write_audit_log
from claimos.services.mfa import decrypt_secret, verify_totp_code
from claimos.templating import templates

router = APIRouter()

_mfa_attempts: dict[str, int] = {}


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


@router.get("/", response_class=HTMLResponse, response_model=None)
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


@router.post("/api/auth/login", response_model=None)
def login(
    request: Request,
    background_tasks: BackgroundTasks,
    email: str = Form(...),
    password: str = Form(...),
    next: str = Form(""),
    db: Session = Depends(get_db),
) -> RedirectResponse | HTMLResponse:
    """Validate credentials and set auth cookies."""
    email = email.strip().lower()
    user = db.query(User).filter(User.email == email).first()

    if user is None or not verify_password(password, user.password_hash):
        background_tasks.add_task(
            write_audit_log,
            user_id=None,
            action="auth.login_failed",
            detail={"email": email, "user_agent": request.headers.get("user-agent", "")},
            ip_address=get_client_ip(request),
        )
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": "Invalid email or password.", "next_url": next},
            status_code=401,
        )

    if not user.is_active:
        background_tasks.add_task(
            write_audit_log,
            user_id=None,
            action="auth.login_failed",
            detail={"email": email, "user_agent": request.headers.get("user-agent", "")},
            ip_address=get_client_ip(request),
        )
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "error": "Account is deactivated. Contact your administrator.",
                "next_url": next,
            },
            status_code=401,
        )

    # MFA check — if enabled, issue short-lived MFA token and redirect to verification step
    if user.mfa_enabled and user.mfa_secret:
        mfa_token = jwt.encode(
            {
                "sub": user.id,
                "purpose": "mfa_verification",
                "exp": datetime.now(tz=timezone.utc) + timedelta(minutes=5),
            },
            settings.jwt_secret,
            algorithm="HS256",
        )
        return templates.TemplateResponse(
            request=request,
            name="login_mfa.html",
            context={"mfa_token": mfa_token, "next_url": next},
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
        expires_at=datetime.now(tz=timezone.utc) + timedelta(days=settings.jwt_refresh_ttl_days),
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

    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="auth.login",
        detail={"user_agent": request.headers.get("user-agent", "")},
        ip_address=get_client_ip(request),
    )
    return response


@router.post("/api/auth/logout")
def logout(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: CurrentUser | None = Depends(optional_user),
) -> RedirectResponse:
    """Revoke refresh token and clear cookies."""
    refresh_cookie = request.cookies.get("cvp_refresh")
    if refresh_cookie:
        token_hash = hash_token(refresh_cookie)
        rt = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()
        if rt:
            rt.revoked_at = datetime.now(tz=timezone.utc)
            db.commit()

    background_tasks.add_task(
        write_audit_log,
        user_id=user.id if user else None,
        action="auth.logout",
        ip_address=get_client_ip(request),
    )
    response = RedirectResponse(url="/", status_code=303)
    _clear_auth_cookies(response)
    return response


@router.post("/api/auth/refresh")
def refresh_token(
    request: Request,
    background_tasks: BackgroundTasks,
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
        expires_at=datetime.now(tz=timezone.utc) + timedelta(days=settings.jwt_refresh_ttl_days),
    )
    db.add(new_rt)
    db.commit()

    next_url = request.headers.get("referer", "/dashboard")
    response = RedirectResponse(url=next_url, status_code=303)
    csrf_token = secrets.token_urlsafe(24)
    _set_auth_cookies(response, access_token, raw_refresh, csrf_token)

    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="auth.token_refresh",
        ip_address=get_client_ip(request),
    )
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

    invite_expired = user.invite_expires_at and (
        user.invite_expires_at.replace(tzinfo=timezone.utc) < datetime.now(tz=timezone.utc)
    )
    if invite_expired:
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


@router.post("/api/auth/register", response_model=None)
def register(
    request: Request,
    background_tasks: BackgroundTasks,
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

    invite_expired = user.invite_expires_at and (
        user.invite_expires_at.replace(tzinfo=timezone.utc) < datetime.now(tz=timezone.utc)
    )
    if invite_expired:
        return templates.TemplateResponse(
            request=request,
            name="register.html",
            context={"invalid": True, "invite_code": "", "email": ""},
        )

    # Prevent re-use of invite code by already-registered user
    if user.password_changed_at is not None:
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

    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="auth.register",
        ip_address=get_client_ip(request),
    )
    return RedirectResponse(url="/login?message=Account+created.+Please+sign+in.", status_code=303)


@router.post("/api/auth/mfa/verify", response_model=None)
def mfa_verify(
    request: Request,
    background_tasks: BackgroundTasks,
    mfa_token: str = Form(...),
    code: str = Form(...),
    next: str = Form(""),
    db: Session = Depends(get_db),
) -> RedirectResponse | HTMLResponse:
    """Verify TOTP code after successful password authentication."""
    try:
        payload = jwt.decode(mfa_token, settings.jwt_secret, algorithms=["HS256"])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": "MFA session expired. Please sign in again.", "next_url": next},
            status_code=401,
        )

    if payload.get("purpose") != "mfa_verification":
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": "Invalid MFA session.", "next_url": next},
            status_code=401,
        )

    user = db.get(User, payload["sub"])
    if user is None or not user.is_active or not user.mfa_secret:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": "Account error. Contact your administrator.", "next_url": next},
            status_code=401,
        )

    # Check lockout before trying the code
    attempt_key = user.id
    if _mfa_attempts.get(attempt_key, 0) >= 3:
        _mfa_attempts.pop(attempt_key, None)
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "error": "Too many failed MFA attempts. Please sign in again.",
                "next_url": next,
            },
            status_code=401,
        )

    decrypted_secret = decrypt_secret(user.mfa_secret, settings.mfa_encryption_key)
    if not verify_totp_code(decrypted_secret, code.strip()):
        background_tasks.add_task(
            write_audit_log,
            user_id=user.id,
            action="auth.mfa_failed",
            detail={"attempt": True},
            ip_address=get_client_ip(request),
        )
        _mfa_attempts[attempt_key] = _mfa_attempts.get(attempt_key, 0) + 1
        if _mfa_attempts.get(attempt_key, 0) >= 3:
            _mfa_attempts.pop(attempt_key, None)
            return templates.TemplateResponse(
                request=request,
                name="login.html",
                context={
                    "error": "Too many failed MFA attempts. Please sign in again.",
                    "next_url": next,
                },
                status_code=401,
            )
        return templates.TemplateResponse(
            request=request,
            name="login_mfa.html",
            context={"mfa_token": mfa_token, "next_url": next, "error": "Invalid code. Try again."},
            status_code=401,
        )

    # MFA passed — clear attempt counter and create full session
    _mfa_attempts.pop(user.id, None)
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
        expires_at=datetime.now(tz=timezone.utc) + timedelta(days=settings.jwt_refresh_ttl_days),
    )
    db.add(refresh_record)
    user.last_login_at = datetime.now(tz=timezone.utc)
    db.commit()

    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="auth.login",
        detail={"mfa": True, "user_agent": request.headers.get("user-agent", "")},
        ip_address=get_client_ip(request),
    )

    redirect_url = next if (next and next.startswith("/")) else "/dashboard"
    csrf_token = secrets.token_urlsafe(24)
    response = RedirectResponse(url=redirect_url, status_code=303)
    _set_auth_cookies(response, access_token, raw_refresh, csrf_token)
    return response
