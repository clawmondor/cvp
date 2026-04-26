# Phase 5: MFA + Password Hardening — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add optional TOTP-based two-factor authentication and a password change flow. MFA is opt-in for all users, with admin ability to reset MFA. Passwords are validated against the breached-password list (already implemented in Phase 1's `auth.py`) and users can change their own passwords from a profile page.

**Architecture:** TOTP secrets are encrypted at rest using Fernet (key in `.env`). MFA setup generates a QR code rendered inline. Login flow adds an intermediate MFA verification step between password validation and full session creation. Password change requires current password verification.

**Tech Stack:** pyotp (TOTP), qrcode (QR generation), cryptography (Fernet), FastAPI, Jinja2

**Spec:** `docs/superpowers/specs/2026-04-25-auth-rbac-design.md` (Sections 5, 10)

**Prerequisite:** Phase 1 must be complete. Phases 2-4 are independent.

---

## File Structure

### New files to create:
- `src/cvp/services/mfa.py` — TOTP secret generation, encryption, verification, QR code rendering
- `src/cvp/routers/profile.py` — User profile endpoints (password change, MFA setup)
- `src/cvp/templates/profile.html` — User profile page
- `src/cvp/templates/login_mfa.html` — MFA verification page (6-digit code input)
- `src/cvp/templates/_mfa_setup.html` — MFA setup partial (QR code + confirmation)
- `tests/test_mfa.py` — MFA service tests
- `tests/test_profile.py` — Profile route tests

### Files to modify:
- `pyproject.toml` — Add pyotp, qrcode dependencies
- `src/cvp/routers/auth.py` — Add MFA verification step to login flow
- `src/cvp/main.py` — Mount profile router
- `src/cvp/templates/base.html` — Add profile link to nav

---

### Task 1: Add MFA dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add packages**

Add to dependencies in `pyproject.toml`:

```toml
    "pyotp>=2.9",
    "qrcode[pil]>=7.4",
```

- [ ] **Step 2: Install**

Run: `uv sync`
Expected: Packages install successfully.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "deps: add pyotp and qrcode for MFA"
```

---

### Task 2: Create MFA service

**Files:**
- Create: `src/cvp/services/mfa.py`
- Test: `tests/test_mfa.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_mfa.py`:

```python
"""Tests for MFA service — TOTP generation, encryption, verification."""

import pyotp

from cvp.services.mfa import (
    generate_totp_secret,
    encrypt_secret,
    decrypt_secret,
    verify_totp_code,
    generate_provisioning_uri,
    generate_qr_code_data_uri,
)


# Use a fixed Fernet key for testing
TEST_FERNET_KEY = "dGVzdGtleXRoYXRpczMyYnl0ZXNsb25nMTIzNDU2Nzg="  # base64 of 32 bytes


def test_generate_totp_secret():
    secret = generate_totp_secret()
    assert len(secret) == 32  # base32 encoded, 32 chars
    # Should be valid base32
    pyotp.TOTP(secret)  # doesn't raise


def test_encrypt_decrypt_roundtrip():
    secret = "JBSWY3DPEHPK3PXP"
    encrypted = encrypt_secret(secret, TEST_FERNET_KEY)
    assert encrypted != secret
    decrypted = decrypt_secret(encrypted, TEST_FERNET_KEY)
    assert decrypted == secret


def test_verify_totp_code_valid():
    secret = generate_totp_secret()
    totp = pyotp.TOTP(secret)
    code = totp.now()
    assert verify_totp_code(secret, code) is True


def test_verify_totp_code_invalid():
    secret = generate_totp_secret()
    assert verify_totp_code(secret, "000000") is False


def test_generate_provisioning_uri():
    uri = generate_provisioning_uri("JBSWY3DPEHPK3PXP", "user@example.com")
    assert "otpauth://totp/" in uri
    assert "user@example.com" in uri
    assert "Contents+Valuation+Platform" in uri or "Contents%20Valuation%20Platform" in uri


def test_generate_qr_code_data_uri():
    uri = generate_provisioning_uri("JBSWY3DPEHPK3PXP", "user@example.com")
    data_uri = generate_qr_code_data_uri(uri)
    assert data_uri.startswith("data:image/png;base64,")
    assert len(data_uri) > 100  # should be a real image
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_mfa.py -v`
Expected: FAIL — `cvp.services.mfa` doesn't exist.

- [ ] **Step 3: Create MFA service**

Create `src/cvp/services/mfa.py`:

```python
"""TOTP MFA service — secret generation, encryption, verification, QR codes."""

import base64
import io

import pyotp
import qrcode
from cryptography.fernet import Fernet


def generate_totp_secret() -> str:
    """Generate a new random TOTP secret (base32 encoded, 32 chars)."""
    return pyotp.random_base32()


def encrypt_secret(secret: str, fernet_key: str) -> str:
    """Encrypt a TOTP secret for storage using Fernet symmetric encryption."""
    f = Fernet(fernet_key.encode() if isinstance(fernet_key, str) else fernet_key)
    return f.encrypt(secret.encode()).decode()


def decrypt_secret(encrypted: str, fernet_key: str) -> str:
    """Decrypt a stored TOTP secret."""
    f = Fernet(fernet_key.encode() if isinstance(fernet_key, str) else fernet_key)
    return f.decrypt(encrypted.encode()).decode()


def verify_totp_code(secret: str, code: str) -> bool:
    """Verify a 6-digit TOTP code against a secret.

    Allows a 30-second window in each direction for clock drift.
    """
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)


def generate_provisioning_uri(secret: str, email: str) -> str:
    """Generate an otpauth:// URI for authenticator app setup."""
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=email, issuer_name="Contents Valuation Platform")


def generate_qr_code_data_uri(provisioning_uri: str) -> str:
    """Generate a base64-encoded PNG QR code as a data URI for inline display."""
    qr = qrcode.QRCode(version=1, box_size=6, border=4)
    qr.add_data(provisioning_uri)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/png;base64,{b64}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_mfa.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cvp/services/mfa.py tests/test_mfa.py
git commit -m "feat: MFA service — TOTP generation, encryption, verification, QR codes"
```

---

### Task 3: Add MFA verification to login flow

**Files:**
- Modify: `src/cvp/routers/auth.py`
- Create: `src/cvp/templates/login_mfa.html`

- [ ] **Step 1: Create MFA verification template**

Create `src/cvp/templates/login_mfa.html`:

```html
<!doctype html>
<html lang="en" class="h-full bg-gray-50">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Two-Factor Authentication — CVP</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="h-full">
  <div class="flex min-h-full flex-col justify-center py-12 sm:px-6 lg:px-8">
    <div class="sm:mx-auto sm:w-full sm:max-w-md">
      <h2 class="mt-6 text-center text-2xl font-bold tracking-tight text-gray-900">
        Two-factor authentication
      </h2>
      <p class="mt-2 text-center text-sm text-gray-600">
        Enter the 6-digit code from your authenticator app
      </p>
    </div>
    <div class="mt-8 sm:mx-auto sm:w-full sm:max-w-md">
      <div class="bg-white py-8 px-4 shadow sm:rounded-lg sm:px-10">
        {% if error %}
        <div class="mb-4 rounded-md bg-red-50 p-4">
          <p class="text-sm text-red-700">{{ error }}</p>
        </div>
        {% endif %}
        <form method="POST" action="/api/auth/mfa/verify" class="space-y-6">
          <input type="hidden" name="mfa_token" value="{{ mfa_token }}" />
          <input type="hidden" name="next" value="{{ next_url or '' }}" />
          <div>
            <label for="code" class="block text-sm font-medium text-gray-700">Authentication code</label>
            <input id="code" name="code" type="text" inputmode="numeric" pattern="[0-9]{6}"
                   maxlength="6" required autofocus autocomplete="one-time-code"
                   class="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-center text-2xl tracking-widest shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-indigo-500" />
          </div>
          <div>
            <button type="submit"
                    class="flex w-full justify-center rounded-md bg-indigo-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-indigo-500">
              Verify
            </button>
          </div>
        </form>
        <p class="mt-4 text-center text-xs text-gray-500">
          Having trouble? Contact your administrator.
        </p>
      </div>
    </div>
  </div>
</body>
</html>
```

- [ ] **Step 2: Update login endpoint for MFA**

In `src/cvp/routers/auth.py`, modify the `login` function. After successful password validation, check if `user.mfa_enabled` is True:

```python
import jwt as pyjwt
from cvp.services.mfa import decrypt_secret, verify_totp_code

# In the login function, after password verification succeeds:

if user.mfa_enabled and user.mfa_secret:
    # Create a short-lived MFA token (5 minutes) that proves password was validated
    mfa_token = pyjwt.encode(
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

# If MFA not enabled, proceed with normal token creation...
```

- [ ] **Step 3: Add MFA verify endpoint**

Add to `src/cvp/routers/auth.py`:

```python
@router.post("/api/auth/mfa/verify")
def mfa_verify(
    request: Request,
    mfa_token: str = Form(...),
    code: str = Form(...),
    next: str = Form(""),
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db),
) -> RedirectResponse | HTMLResponse:
    """Verify TOTP code after successful password authentication."""
    # Decode the MFA token
    try:
        payload = pyjwt.decode(mfa_token, settings.jwt_secret, algorithms=["HS256"])
    except (pyjwt.ExpiredSignatureError, pyjwt.InvalidTokenError):
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

    # Verify TOTP code
    decrypted_secret = decrypt_secret(user.mfa_secret, settings.mfa_encryption_key)
    if not verify_totp_code(decrypted_secret, code.strip()):
        # Audit log the failure
        if background_tasks:
            from cvp.services.audit import write_audit_log, get_client_ip
            background_tasks.add_task(
                write_audit_log,
                user_id=user.id,
                action="auth.mfa_failed",
                detail={"attempt": True},
                ip_address=get_client_ip(request),
            )
        return templates.TemplateResponse(
            request=request,
            name="login_mfa.html",
            context={"mfa_token": mfa_token, "next_url": next, "error": "Invalid code. Try again."},
            status_code=401,
        )

    # MFA passed — create full session (same as normal login success)
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

    redirect_url = next if next else "/dashboard"
    response = RedirectResponse(url=redirect_url, status_code=303)
    _set_auth_cookies(response, access_token, raw_refresh, hash_token(access_token)[:32])
    return response
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest -v`

- [ ] **Step 5: Commit**

```bash
git add src/cvp/routers/auth.py src/cvp/templates/login_mfa.html
git commit -m "feat: MFA verification step in login flow"
```

---

### Task 4: Create profile router with MFA setup and password change

**Files:**
- Create: `src/cvp/routers/profile.py`
- Create: `src/cvp/templates/profile.html`
- Create: `src/cvp/templates/_mfa_setup.html`
- Test: `tests/test_profile.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_profile.py`:

```python
"""Tests for user profile endpoints."""

import pytest
from fastapi.testclient import TestClient

from cvp.dependencies import require_active_user, CurrentUser


@pytest.fixture
def auth_client():
    from cvp.main import app

    async def mock_user():
        return CurrentUser(
            id="u1", email="test@test.com", system_role="internal_user",
            group_id="ig", group_kind="internal",
        )

    app.dependency_overrides[require_active_user] = mock_user
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_profile_page_accessible(auth_client):
    resp = auth_client.get("/profile")
    assert resp.status_code == 200
    assert "Password" in resp.text
```

- [ ] **Step 2: Create profile template**

Create `src/cvp/templates/profile.html`:

```html
{% extends "base.html" %}
{% block title %}Profile{% endblock %}
{% block content %}
<div class="max-w-2xl mx-auto space-y-8">
  <h1 class="text-2xl font-bold text-gray-900">Your Profile</h1>

  <!-- User info -->
  <div class="bg-white shadow sm:rounded-lg p-6">
    <h2 class="text-lg font-medium text-gray-900 mb-4">Account Information</h2>
    <dl class="space-y-3">
      <div class="flex">
        <dt class="w-32 text-sm font-medium text-gray-500">Email</dt>
        <dd class="text-sm text-gray-900">{{ profile_user.email }}</dd>
      </div>
      <div class="flex">
        <dt class="w-32 text-sm font-medium text-gray-500">Name</dt>
        <dd class="text-sm text-gray-900">{{ profile_user.display_name }}</dd>
      </div>
      <div class="flex">
        <dt class="w-32 text-sm font-medium text-gray-500">Role</dt>
        <dd class="text-sm text-gray-900">{{ profile_user.system_role | replace('_', ' ') | title }}</dd>
      </div>
    </dl>
  </div>

  <!-- Password change -->
  <div class="bg-white shadow sm:rounded-lg p-6">
    <h2 class="text-lg font-medium text-gray-900 mb-4">Change Password</h2>
    {% if pw_error %}
    <div class="mb-4 rounded-md bg-red-50 p-4">
      <p class="text-sm text-red-700">{{ pw_error }}</p>
    </div>
    {% endif %}
    {% if pw_success %}
    <div class="mb-4 rounded-md bg-green-50 p-4">
      <p class="text-sm text-green-700">{{ pw_success }}</p>
    </div>
    {% endif %}
    <form method="POST" action="/profile/password" class="space-y-4">
      <div>
        <label for="current_password" class="block text-sm font-medium text-gray-700">Current password</label>
        <input id="current_password" name="current_password" type="password" required
               class="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 shadow-sm focus:border-indigo-500 focus:outline-none sm:text-sm" />
      </div>
      <div>
        <label for="new_password" class="block text-sm font-medium text-gray-700">New password</label>
        <input id="new_password" name="new_password" type="password" required minlength="12"
               class="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 shadow-sm focus:border-indigo-500 focus:outline-none sm:text-sm" />
        <p class="mt-1 text-xs text-gray-500">Minimum 12 characters</p>
      </div>
      <div>
        <label for="new_password_confirm" class="block text-sm font-medium text-gray-700">Confirm new password</label>
        <input id="new_password_confirm" name="new_password_confirm" type="password" required minlength="12"
               class="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 shadow-sm focus:border-indigo-500 focus:outline-none sm:text-sm" />
      </div>
      <button type="submit"
              class="rounded-md bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-indigo-500">
        Update Password
      </button>
    </form>
  </div>

  <!-- MFA -->
  <div class="bg-white shadow sm:rounded-lg p-6">
    <h2 class="text-lg font-medium text-gray-900 mb-4">Two-Factor Authentication</h2>
    {% if profile_user.mfa_enabled %}
    <div class="flex items-center justify-between">
      <div>
        <p class="text-sm text-green-700 font-medium">MFA is enabled</p>
        <p class="text-xs text-gray-500 mt-1">Your account is protected with an authenticator app.</p>
      </div>
      <form method="POST" action="/profile/mfa/disable">
        <button type="submit"
                class="rounded-md bg-red-600 px-3 py-1.5 text-sm font-semibold text-white shadow-sm hover:bg-red-500">
          Disable MFA
        </button>
      </form>
    </div>
    {% else %}
    <div id="mfa-setup">
      <p class="text-sm text-gray-600 mb-4">
        Add an extra layer of security by enabling two-factor authentication with an authenticator app.
      </p>
      <button hx-post="/profile/mfa/setup"
              hx-target="#mfa-setup"
              hx-swap="innerHTML"
              class="rounded-md bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-indigo-500">
        Set up MFA
      </button>
    </div>
    {% endif %}
    {% if mfa_error %}
    <div class="mt-4 rounded-md bg-red-50 p-4">
      <p class="text-sm text-red-700">{{ mfa_error }}</p>
    </div>
    {% endif %}
  </div>
</div>
{% endblock %}
```

- [ ] **Step 3: Create MFA setup partial**

Create `src/cvp/templates/_mfa_setup.html`:

```html
<div class="space-y-4">
  <p class="text-sm text-gray-600">
    Scan this QR code with your authenticator app (Google Authenticator, Authy, etc.):
  </p>
  <div class="flex justify-center">
    <img src="{{ qr_data_uri }}" alt="MFA QR Code" class="border rounded-lg" />
  </div>
  <p class="text-xs text-gray-500 text-center">
    Can't scan? Enter this code manually: <code class="font-mono bg-gray-100 px-2 py-1 rounded">{{ raw_secret }}</code>
  </p>
  <form method="POST" action="/profile/mfa/confirm" class="space-y-3">
    <input type="hidden" name="secret" value="{{ encrypted_secret }}" />
    <div>
      <label for="mfa_code" class="block text-sm font-medium text-gray-700">Enter the 6-digit code to confirm</label>
      <input id="mfa_code" name="code" type="text" inputmode="numeric" pattern="[0-9]{6}"
             maxlength="6" required autofocus
             class="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-center text-xl tracking-widest shadow-sm focus:border-indigo-500 focus:outline-none" />
    </div>
    <button type="submit"
            class="w-full rounded-md bg-green-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-green-500">
      Confirm and Enable MFA
    </button>
  </form>
</div>
```

- [ ] **Step 4: Create profile router**

Create `src/cvp/routers/profile.py`:

```python
"""User profile endpoints — password change, MFA setup."""

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
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


@router.get("/profile", response_class=HTMLResponse)
def profile_page(
    request: Request,
    user: CurrentUser = Depends(require_active_user),
    db: Session = Depends(get_db),
    pw_error: str = "",
    pw_success: str = "",
    mfa_error: str = "",
) -> HTMLResponse:
    """Render the user profile page."""
    profile_user = db.get(User, user.id)
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


@router.post("/profile/password")
def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    new_password_confirm: str = Form(...),
    user: CurrentUser = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Change the user's password."""
    profile_user = db.get(User, user.id)

    if not verify_password(current_password, profile_user.password_hash):
        return profile_page(request, user, db, pw_error="Current password is incorrect.")

    if new_password != new_password_confirm:
        return profile_page(request, user, db, pw_error="New passwords do not match.")

    pw_error = validate_password_strength(new_password)
    if pw_error:
        return profile_page(request, user, db, pw_error=pw_error)

    profile_user.password_hash = hash_password(new_password)
    profile_user.password_changed_at = datetime.now(tz=timezone.utc)
    db.commit()

    return profile_page(request, user, db, pw_success="Password updated successfully.")


@router.post("/profile/mfa/setup", response_class=HTMLResponse)
def mfa_setup(
    request: Request,
    user: CurrentUser = Depends(require_active_user),
) -> HTMLResponse:
    """Generate a new TOTP secret and display QR code for setup."""
    raw_secret = generate_totp_secret()
    encrypted_secret = encrypt_secret(raw_secret, settings.mfa_encryption_key)
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
    """Confirm MFA setup by verifying a TOTP code, then enable MFA."""
    raw_secret = decrypt_secret(secret, settings.mfa_encryption_key)

    if not verify_totp_code(raw_secret, code.strip()):
        return profile_page(request, user, db, mfa_error="Invalid code. Please try again.")

    profile_user = db.get(User, user.id)
    profile_user.mfa_secret = secret  # Store the encrypted version
    profile_user.mfa_enabled = True
    db.commit()

    return profile_page(request, user, db)


@router.post("/profile/mfa/disable")
def mfa_disable(
    request: Request,
    user: CurrentUser = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Disable MFA for the current user."""
    profile_user = db.get(User, user.id)
    profile_user.mfa_secret = None
    profile_user.mfa_enabled = False
    db.commit()

    return profile_page(request, user, db)
```

- [ ] **Step 5: Mount profile router in main.py**

```python
from cvp.routers import profile
app.include_router(profile.router)
```

- [ ] **Step 6: Add profile link to base.html**

In `src/cvp/templates/base.html`, add a "Profile" link next to the user's name:

```html
{% if user %}
<a href="/profile" class="text-sm text-gray-500 hover:text-gray-700">{{ user.display_name or user.email }}</a>
{% endif %}
```

- [ ] **Step 7: Run tests**

Run: `uv run pytest tests/test_profile.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/cvp/routers/profile.py src/cvp/templates/profile.html src/cvp/templates/_mfa_setup.html src/cvp/templates/login_mfa.html src/cvp/main.py src/cvp/templates/base.html tests/test_profile.py
git commit -m "feat: user profile — password change + MFA setup/disable"
```

---

### Task 5: Add MFA reset to admin panels

**Files:**
- Modify: `src/cvp/routers/admin/system.py`

- [ ] **Step 1: Add MFA reset endpoint**

The System Admin panel already has a `POST /admin/system/users/{user_id}/reset-mfa` route (from Phase 3). Implement it:

```python
@router.post("/admin/system/users/{user_id}/reset-mfa")
def reset_mfa(
    user_id: str,
    admin: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Reset MFA for a user (admin action)."""
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404)
    target.mfa_secret = None
    target.mfa_enabled = False
    db.commit()

    # Audit log
    # background_tasks.add_task(write_audit_log, ...)

    return RedirectResponse(url=f"/admin/system/users/{user_id}", status_code=303)
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest -v`

- [ ] **Step 3: Commit**

```bash
git add src/cvp/routers/admin/system.py
git commit -m "feat: admin MFA reset for users"
```

---

### Task 6: Rate limiting on MFA verification

**Files:**
- Modify: `src/cvp/routers/auth.py`

- [ ] **Step 1: Add MFA rate limiting**

Track MFA attempts per user session. After 3 failed attempts within 15 minutes, invalidate the MFA token (user must re-enter password):

```python
# In mfa_verify endpoint, before checking the code:
# Use a simple in-memory dict for dev, audit_logs query for production

# Track failed attempts via a counter in the MFA token itself:
# Re-encode the mfa_token with an incremented attempt count
# If attempts >= 3, reject and redirect to login

# Alternatively, track in a module-level dict (simpler):
_mfa_attempts: dict[str, int] = {}  # user_id -> count

# In mfa_verify, on failure:
_mfa_attempts[user.id] = _mfa_attempts.get(user.id, 0) + 1
if _mfa_attempts.get(user.id, 0) >= 3:
    _mfa_attempts.pop(user.id, None)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"error": "Too many failed MFA attempts. Please sign in again.", "next_url": next},
        status_code=401,
    )

# On success, clear the counter:
_mfa_attempts.pop(user.id, None)
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest -v`

- [ ] **Step 3: Commit**

```bash
git add src/cvp/routers/auth.py
git commit -m "feat: rate limiting on MFA verification (3 attempts)"
```

---

### Task 7: Generate MFA_ENCRYPTION_KEY config

- [ ] **Step 1: Add to .env**

Generate a Fernet key and add to `.env`:

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Add to `.env`:
```
MFA_ENCRYPTION_KEY=<generated key>
```

- [ ] **Step 2: Validate config loads**

Run: `uv run python -c "from cvp.config import settings; print('MFA key loaded:', bool(settings.mfa_encryption_key))"`
Expected: `MFA key loaded: True`

---

### Task 8: Final verification

- [ ] **Step 1: Run full test suite and linter**

```bash
uv run pytest -v
uv run ruff check . && uv run ruff format --check .
```

- [ ] **Step 2: Manual smoke test**

1. Visit `/profile` — see account info, password form, MFA section
2. Change password with wrong current password — error
3. Change password with weak password — error
4. Change password with valid password — success
5. Click "Set up MFA" — see QR code
6. Scan with authenticator app, enter code — MFA enabled
7. Log out, log back in — see MFA verification page
8. Enter correct code — reach dashboard
9. Enter wrong code 3 times — redirected to login
10. As System Admin, reset MFA for a user — verify it works
11. Disable MFA from profile — verify it works

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "chore: phase 5 complete — MFA + password hardening"
```
