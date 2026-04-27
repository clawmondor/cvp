"""User profile endpoints — password change, MFA setup."""

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from cvp.auth import hash_password, validate_password_strength, verify_password
from cvp.config import settings
from cvp.db import get_db
from cvp.dependencies import CurrentUser, require_active_user
from cvp.models_auth import User
from cvp.services.mfa import (
    decrypt_secret,
    encrypt_secret,
    generate_provisioning_uri,
    generate_qr_code_data_uri,
    generate_totp_secret,
    verify_totp_code,
)

BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")

router = APIRouter()


def _profile_response(
    request: Request,
    user: CurrentUser,
    profile_user: User,
    pw_error: str = "",
    pw_success: str = "",
    mfa_error: str = "",
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="profile.html",
        context={
            "user": user,
            "profile_user": profile_user,
            "pw_error": pw_error,
            "pw_success": pw_success,
            "mfa_error": mfa_error,
        },
    )


@router.get("/profile", response_class=HTMLResponse)
def profile_page(
    request: Request,
    user: CurrentUser = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    profile_user = db.get(User, user.id) or User(
        id=user.id,
        email=user.email,
        system_role=user.system_role,
        display_name="",
    )
    return _profile_response(request, user, profile_user)


@router.post("/profile/password")
def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    new_password_confirm: str = Form(...),
    user: CurrentUser = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    profile_user = db.get(User, user.id) or User(
        id=user.id,
        email=user.email,
        system_role=user.system_role,
        display_name="",
    )

    if not profile_user.password_hash or not verify_password(
        current_password, profile_user.password_hash
    ):
        return _profile_response(
            request, user, profile_user, pw_error="Current password is incorrect."
        )

    if new_password != new_password_confirm:
        return _profile_response(
            request, user, profile_user, pw_error="New passwords do not match."
        )

    pw_error = validate_password_strength(new_password)
    if pw_error:
        return _profile_response(request, user, profile_user, pw_error=pw_error)

    profile_user.password_hash = hash_password(new_password)
    profile_user.password_changed_at = datetime.now(tz=timezone.utc)
    db.commit()

    return _profile_response(
        request, user, profile_user, pw_success="Password updated successfully."
    )


@router.post("/profile/mfa/setup", response_class=HTMLResponse)
def mfa_setup(
    request: Request,
    user: CurrentUser = Depends(require_active_user),
) -> HTMLResponse:
    raw_secret = generate_totp_secret()
    if settings.mfa_encryption_key:
        encrypted_secret = encrypt_secret(raw_secret, settings.mfa_encryption_key)
    else:
        encrypted_secret = raw_secret
    uri = generate_provisioning_uri(raw_secret, user.email)
    qr_data_uri = generate_qr_code_data_uri(uri)

    return HTMLResponse(
        templates.get_template("_mfa_setup.html").render(
            qr_data_uri=qr_data_uri,
            raw_secret=raw_secret,
            encrypted_secret=encrypted_secret,
        )
    )


@router.post("/profile/mfa/confirm")
def mfa_confirm(
    request: Request,
    secret: str = Form(...),
    code: str = Form(...),
    user: CurrentUser = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    if settings.mfa_encryption_key:
        raw_secret = decrypt_secret(secret, settings.mfa_encryption_key)
    else:
        raw_secret = secret

    profile_user = db.get(User, user.id) or User(
        id=user.id,
        email=user.email,
        system_role=user.system_role,
        display_name="",
    )

    if not verify_totp_code(raw_secret, code.strip()):
        return _profile_response(
            request, user, profile_user, mfa_error="Invalid code. Please try again."
        )

    profile_user.mfa_secret = secret  # Store the encrypted version
    profile_user.mfa_enabled = True
    db.commit()

    return _profile_response(request, user, profile_user)


@router.post("/profile/mfa/disable")
def mfa_disable(
    request: Request,
    user: CurrentUser = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    profile_user = db.get(User, user.id) or User(
        id=user.id,
        email=user.email,
        system_role=user.system_role,
        display_name="",
    )
    profile_user.mfa_secret = None
    profile_user.mfa_enabled = False
    db.commit()

    return _profile_response(request, user, profile_user)
