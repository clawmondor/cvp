# Phase 1: Core Auth Infrastructure — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add user authentication to the CVP app so that all existing endpoints require login, with JWT-based sessions, invite-code registration, and environment-aware security hardening.

**Architecture:** FastAPI dependency injection for auth. JWT access tokens in HTTP-only cookies (web) and Authorization header (API). Server-side refresh tokens in SQLite. bcrypt password hashing. Security headers middleware. CSRF double-submit cookie pattern. All existing endpoints gated behind `require_active_user` (no granular RBAC yet — that's Phase 2).

**Tech Stack:** PyJWT, bcrypt, cryptography (Fernet for future MFA), pydantic-settings, SQLAlchemy 2.x, Alembic, Jinja2, HTMX

**Spec:** `docs/superpowers/specs/2026-04-25-auth-rbac-design.md` (Sections 2, 4, 5, 6, 10, 11, 12)

---

## File Structure

### New files to create:
- `src/cvp/models_auth.py` — Group, User, RefreshToken ORM models
- `src/cvp/auth.py` — JWT creation/validation, password hashing, token refresh logic
- `src/cvp/dependencies.py` — FastAPI dependencies: `get_current_user`, `require_active_user`, `optional_user`
- `src/cvp/middleware.py` — Security headers middleware
- `src/cvp/routers/auth.py` — Login, logout, register, refresh endpoints
- `src/cvp/templates/splash.html` — Public landing page
- `src/cvp/templates/login.html` — Login form
- `src/cvp/templates/register.html` — Invite registration form
- `src/cvp/seed_auth.py` — Seed initial System Admin + Internal group
- `tests/test_auth.py` — Auth unit tests (JWT, passwords, tokens)
- `tests/test_auth_routes.py` — Auth route integration tests
- `tests/test_dependencies.py` — Dependency injection guard tests
- `tests/test_middleware.py` — Security headers tests
- `data/pwned_passwords_top100k.txt` — Breached password list (top 100k)

### Files to modify:
- `src/cvp/config.py` — Add auth-related settings
- `src/cvp/models.py` — Import and register auth models with Base
- `src/cvp/main.py` — Add middleware, mount auth router, move dashboard to `/dashboard`
- `src/cvp/templates/base.html` — Add user info, logout, admin links to nav
- `src/cvp/db.py` — No changes needed (session factory already exists)
- `src/cvp/routers/matters.py` — Add `require_active_user` dependency to all routes
- `src/cvp/routers/evidence.py` — Add `require_active_user` dependency to all routes
- `src/cvp/routers/items.py` — Add `require_active_user` dependency to all routes
- `src/cvp/routers/rooms.py` — Add `require_active_user` dependency to all routes
- `src/cvp/routers/vision.py` — Add `require_active_user` dependency to all routes
- `src/cvp/routers/serp.py` — Add `optional_user`/`require_active_user` to routes (crops stays public)
- `src/cvp/routers/crops.py` — Add `require_active_user` dependency to all routes
- `src/cvp/routers/exports.py` — Add `require_active_user` dependency to all routes
- `pyproject.toml` — Add PyJWT, bcrypt, cryptography dependencies

---

### Task 1: Add dependencies to pyproject.toml

**Files:**
- Modify: `pyproject.toml:6-19`

- [ ] **Step 1: Add auth packages**

Add `pyjwt`, `bcrypt`, and `cryptography` to the dependencies list in `pyproject.toml`:

```toml
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "jinja2>=3.1",
    "python-multipart>=0.0.9",
    "sqlalchemy>=2.0",
    "alembic>=1.13",
    "pydantic-settings>=2.0",
    "anthropic>=0.40",
    "weasyprint>=62",
    "pandas>=2.2",
    "pillow>=10.0",
    "httpx>=0.27",
    "pyjwt>=2.8",
    "bcrypt>=4.1",
    "cryptography>=42.0",
]
```

- [ ] **Step 2: Install**

Run: `uv sync`
Expected: All packages install successfully.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "deps: add pyjwt, bcrypt, cryptography for auth"
```

---

### Task 2: Add auth config settings

**Files:**
- Modify: `src/cvp/config.py`
- Test: `tests/test_auth.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_auth.py`:

```python
"""Tests for auth config, JWT, and password utilities."""

from cvp.config import Settings


def test_default_settings_have_auth_fields():
    """Auth settings exist with sensible defaults."""
    s = Settings(
        _env_file=None,
        jwt_secret="a" * 32,
    )
    assert s.environment == "production"
    assert s.jwt_secret == "a" * 32
    assert s.jwt_access_ttl_minutes == 60
    assert s.jwt_refresh_ttl_days == 7
    assert s.auto_login_user_id == ""
    assert s.cookie_secure is True
    assert s.cookie_domain == ""
    assert s.rate_limit_enabled is True


def test_dev_environment_settings():
    """Dev environment can disable cookie_secure and rate limiting."""
    s = Settings(
        _env_file=None,
        jwt_secret="b" * 32,
        environment="dev",
        cookie_secure=False,
        rate_limit_enabled=False,
    )
    assert s.environment == "dev"
    assert s.cookie_secure is False
    assert s.rate_limit_enabled is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_auth.py::test_default_settings_have_auth_fields -v`
Expected: FAIL — `Settings` doesn't have `jwt_secret` field yet.

- [ ] **Step 3: Add auth fields to config.py**

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    anthropic_api_key: str = ""
    vision_model: str = "claude-opus-4-6"
    vision_model_fallback: str = "claude-sonnet-4-6"
    port: int = 8000
    database_url: str = "sqlite:///./data/cvp.db"
    upload_dir: str = "./data/uploads"
    export_dir: str = "./data/exports"
    crop_dir: str = "./data/crops"
    serp_api_key: str = ""
    public_base_url: str = ""
    company_name: str = "Contents Valuation LLC"
    company_address: str = ""
    company_email: str = ""
    company_phone: str = ""

    # Auth settings
    environment: str = "production"
    jwt_secret: str = ""
    jwt_access_ttl_minutes: int = 60
    jwt_refresh_ttl_days: int = 7
    mfa_encryption_key: str = ""
    auto_login_user_id: str = ""
    cookie_secure: bool = True
    cookie_domain: str = ""
    rate_limit_enabled: bool = True


settings = Settings()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_auth.py -v`
Expected: Both tests PASS.

- [ ] **Step 5: Update .env with JWT_SECRET**

Add to your `.env` file (do NOT commit this):

```
JWT_SECRET=<generate with: python3 -c "import secrets; print(secrets.token_hex(32))">
ENVIRONMENT=dev
COOKIE_SECURE=false
RATE_LIMIT_ENABLED=false
```

- [ ] **Step 6: Commit**

```bash
git add src/cvp/config.py tests/test_auth.py
git commit -m "feat: add auth config settings (jwt, environment, cookies)"
```

---

### Task 3: Create Group and User ORM models

**Files:**
- Create: `src/cvp/models_auth.py`
- Modify: `src/cvp/models.py`
- Test: `tests/test_auth.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_auth.py`:

```python
from cvp.models_auth import Group, User, RefreshToken


def test_group_model_fields():
    g = Group(id="g1", name="Test Group", kind="internal")
    assert g.id == "g1"
    assert g.name == "Test Group"
    assert g.kind == "internal"
    assert g.is_active is True


def test_user_model_fields():
    u = User(
        id="u1",
        email="test@example.com",
        display_name="Test User",
        password_hash="hashed",
        system_role="internal_user",
        group_id="g1",
    )
    assert u.id == "u1"
    assert u.email == "test@example.com"
    assert u.system_role == "internal_user"
    assert u.is_active is True
    assert u.mfa_enabled is False
    assert u.mfa_secret is None


def test_refresh_token_model_fields():
    rt = RefreshToken(
        id="rt1",
        user_id="u1",
        token_hash="hash123",
    )
    assert rt.id == "rt1"
    assert rt.user_id == "u1"
    assert rt.revoked_at is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_auth.py::test_group_model_fields -v`
Expected: FAIL — `models_auth` module doesn't exist.

- [ ] **Step 3: Create models_auth.py**

Create `src/cvp/models_auth.py`:

```python
"""Auth-related ORM models: Group, User, RefreshToken."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from cvp.models import Base, _new_uuid


class Group(Base):
    """An organization — one internal, many external."""

    __tablename__ = "groups"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)  # "internal" | "external"
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    users: Mapped[list["User"]] = relationship("User", back_populates="group")


class User(Base):
    """An authenticated user with a system role."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    email: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String, nullable=False, default="")
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    system_role: Mapped[str] = mapped_column(String, nullable=False)
    group_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("groups.id"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    mfa_secret: Mapped[str | None] = mapped_column(String, nullable=True)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    invite_code: Mapped[str | None] = mapped_column(String, nullable=True)
    invite_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    group: Mapped["Group | None"] = relationship("Group", back_populates="users")


class RefreshToken(Base):
    """Server-side refresh token for JWT session management."""

    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    user: Mapped["User"] = relationship("User")
```

- [ ] **Step 4: Register auth models with Base**

Add this import at the bottom of `src/cvp/models.py` so Alembic sees the auth tables:

```python
import cvp.models_auth as _auth_models  # noqa: F401, E402 — register auth tables with Base
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_auth.py -v`
Expected: All tests PASS.

- [ ] **Step 6: Generate Alembic migration**

Run: `uv run alembic revision --autogenerate -m "add groups users refresh_tokens tables"`
Expected: New migration file created in `migrations/versions/`.

- [ ] **Step 7: Apply migration**

Run: `uv run alembic upgrade head`
Expected: Migration applies successfully.

- [ ] **Step 8: Commit**

```bash
git add src/cvp/models_auth.py src/cvp/models.py tests/test_auth.py migrations/versions/
git commit -m "feat: add Group, User, RefreshToken ORM models + migration"
```

---

### Task 4: Implement password hashing and JWT utilities

**Files:**
- Create: `src/cvp/auth.py`
- Test: `tests/test_auth.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_auth.py`:

```python
import time

from cvp.auth import (
    hash_password,
    verify_password,
    create_access_token,
    decode_access_token,
    create_refresh_token_value,
    hash_token,
    is_breached_password,
)


def test_hash_and_verify_password():
    hashed = hash_password("securepassword1")
    assert hashed != "securepassword1"
    assert verify_password("securepassword1", hashed) is True
    assert verify_password("wrongpassword", hashed) is False


def test_create_and_decode_access_token():
    token = create_access_token(
        user_id="u1",
        email="test@example.com",
        system_role="internal_user",
        group_id="g1",
        group_kind="internal",
        secret="testsecret123456789012345678901234",
        ttl_minutes=60,
    )
    payload = decode_access_token(token, secret="testsecret123456789012345678901234")
    assert payload["sub"] == "u1"
    assert payload["email"] == "test@example.com"
    assert payload["system_role"] == "internal_user"
    assert payload["group_id"] == "g1"
    assert payload["group_kind"] == "internal"


def test_decode_expired_token_raises():
    token = create_access_token(
        user_id="u1",
        email="test@example.com",
        system_role="internal_user",
        group_id="g1",
        group_kind="internal",
        secret="testsecret123456789012345678901234",
        ttl_minutes=-1,  # already expired
    )
    payload = decode_access_token(token, secret="testsecret123456789012345678901234")
    assert payload is None


def test_decode_invalid_token_returns_none():
    payload = decode_access_token("garbage.token.value", secret="testsecret123456789012345678901234")
    assert payload is None


def test_create_refresh_token_value():
    token = create_refresh_token_value()
    assert len(token) > 20  # url-safe token should be substantial


def test_hash_token():
    token = "my-refresh-token"
    h = hash_token(token)
    assert h != token
    assert hash_token(token) == h  # deterministic


def test_is_breached_password():
    # "password" should be in the top 100k list
    assert is_breached_password("password") is True
    # A random long string should not be
    assert is_breached_password("xK9$mP2vQ7wL4nR8jF5tY3hB6cD0aE1g") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_auth.py::test_hash_and_verify_password -v`
Expected: FAIL — `cvp.auth` module doesn't exist.

- [ ] **Step 3: Download breached password list**

Download the top 100k most common passwords. Create a simple text file:

```bash
curl -sL "https://raw.githubusercontent.com/danielmiessler/SecLists/master/Passwords/Common-Credentials/10-million-password-list-top-100000.txt" -o data/pwned_passwords_top100k.txt
```

If the download fails, create a minimal file with at least the obvious entries:

```bash
cat > data/pwned_passwords_top100k.txt << 'PWEOF'
password
123456
12345678
qwerty
abc123
monkey
1234567
letmein
trustno1
dragon
PWEOF
```

- [ ] **Step 4: Create auth.py**

Create `src/cvp/auth.py`:

```python
"""JWT creation/validation, password hashing, and token utilities."""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

import bcrypt
import jwt

# Load breached passwords into a set for O(1) lookup
_BREACHED_PASSWORDS: set[str] = set()
_BREACHED_FILE = Path(__file__).parent.parent.parent / "data" / "pwned_passwords_top100k.txt"
if _BREACHED_FILE.exists():
    _BREACHED_PASSWORDS = set(_BREACHED_FILE.read_text().strip().splitlines())


def hash_password(password: str) -> str:
    """Hash a password with bcrypt, cost factor 12."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, hashed: str) -> bool:
    """Verify a password against a bcrypt hash."""
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_access_token(
    *,
    user_id: str,
    email: str,
    system_role: str,
    group_id: str | None,
    group_kind: str | None,
    secret: str,
    ttl_minutes: int = 60,
) -> str:
    """Create a signed JWT access token."""
    now = datetime.now(tz=timezone.utc)
    payload = {
        "sub": user_id,
        "email": email,
        "system_role": system_role,
        "group_id": group_id,
        "group_kind": group_kind,
        "iat": now,
        "exp": now + timedelta(minutes=ttl_minutes),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_access_token(token: str, *, secret: str) -> dict | None:
    """Decode and validate a JWT access token. Returns payload dict or None."""
    try:
        return jwt.decode(token, secret, algorithms=["HS256"])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None


def create_refresh_token_value() -> str:
    """Generate a cryptographically secure refresh token string."""
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    """SHA-256 hash a token for storage. Never store raw tokens."""
    return hashlib.sha256(token.encode()).hexdigest()


def is_breached_password(password: str) -> bool:
    """Check if password appears in the top 100k breached passwords list."""
    return password.lower() in _BREACHED_PASSWORDS


def generate_invite_code() -> str:
    """Generate a random invite code (32 chars, URL-safe)."""
    return secrets.token_urlsafe(24)


def validate_password_strength(password: str) -> str | None:
    """Validate password meets requirements. Returns error message or None."""
    if len(password) < 12:
        return "Password must be at least 12 characters."
    if len(password) > 128:
        return "Password must be at most 128 characters."
    if is_breached_password(password):
        return "This password is too common. Please choose a different one."
    return None
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_auth.py -v`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/cvp/auth.py data/pwned_passwords_top100k.txt tests/test_auth.py
git commit -m "feat: auth utilities — JWT, bcrypt, breached-password check"
```

---

### Task 5: Create FastAPI auth dependencies

**Files:**
- Create: `src/cvp/dependencies.py`
- Test: `tests/test_dependencies.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_dependencies.py`:

```python
"""Tests for FastAPI auth dependencies."""

import pytest
from unittest.mock import MagicMock
from fastapi import HTTPException

from cvp.auth import create_access_token
from cvp.dependencies import CurrentUser, _extract_token, _decode_and_build_user


TEST_SECRET = "testsecret123456789012345678901234"


def _make_token(**overrides) -> str:
    defaults = {
        "user_id": "u1",
        "email": "test@example.com",
        "system_role": "internal_user",
        "group_id": "g1",
        "group_kind": "internal",
        "secret": TEST_SECRET,
        "ttl_minutes": 60,
    }
    defaults.update(overrides)
    return create_access_token(**defaults)


def test_current_user_model():
    u = CurrentUser(
        id="u1",
        email="test@example.com",
        system_role="internal_user",
        group_id="g1",
        group_kind="internal",
    )
    assert u.id == "u1"
    assert u.system_role == "internal_user"


def test_extract_token_from_auth_header():
    request = MagicMock()
    request.headers = {"authorization": "Bearer mytoken123"}
    request.cookies = {}
    token, source = _extract_token(request)
    assert token == "mytoken123"
    assert source == "header"


def test_extract_token_from_cookie():
    request = MagicMock()
    request.headers = {}
    request.cookies = {"cvp_access": "cookietoken456"}
    token, source = _extract_token(request)
    assert token == "cookietoken456"
    assert source == "cookie"


def test_extract_token_none_when_missing():
    request = MagicMock()
    request.headers = {}
    request.cookies = {}
    token, source = _extract_token(request)
    assert token is None
    assert source is None


def test_extract_token_header_takes_precedence():
    request = MagicMock()
    request.headers = {"authorization": "Bearer headertoken"}
    request.cookies = {"cvp_access": "cookietoken"}
    token, source = _extract_token(request)
    assert token == "headertoken"
    assert source == "header"


def test_decode_and_build_user_valid():
    token = _make_token()
    user = _decode_and_build_user(token, TEST_SECRET)
    assert user.id == "u1"
    assert user.email == "test@example.com"


def test_decode_and_build_user_expired():
    token = _make_token(ttl_minutes=-1)
    user = _decode_and_build_user(token, TEST_SECRET)
    assert user is None


def test_decode_and_build_user_bad_secret():
    token = _make_token()
    user = _decode_and_build_user(token, "wrong_secret_that_is_long_enough!!")
    assert user is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_dependencies.py::test_current_user_model -v`
Expected: FAIL — `cvp.dependencies` module doesn't exist.

- [ ] **Step 3: Create dependencies.py**

Create `src/cvp/dependencies.py`:

```python
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


def _decode_and_build_user(token: str, secret: str) -> CurrentUser | None:
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


async def optional_user(request: Request) -> CurrentUser | None:
    """Return the current user if authenticated, None otherwise.

    Used for public endpoints (like /crops/) that work without auth.
    """
    token, source = _extract_token(request)
    if token is None:
        return None
    return _decode_and_build_user(token, settings.jwt_secret)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_dependencies.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cvp/dependencies.py tests/test_dependencies.py
git commit -m "feat: FastAPI auth dependencies — get_current_user, require_active_user, optional_user"
```

---

### Task 6: Create security headers middleware

**Files:**
- Create: `src/cvp/middleware.py`
- Test: `tests/test_middleware.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_middleware.py`:

```python
"""Tests for security headers middleware."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from cvp.middleware import SecurityHeadersMiddleware


def _make_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware, environment="production")

    @app.get("/test")
    def test_endpoint():
        return {"ok": True}

    return app


def test_security_headers_present():
    client = TestClient(_make_app())
    resp = client.get("/test")
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "x-request-id" in resp.headers
    assert "content-security-policy" in resp.headers
    assert "permissions-policy" in resp.headers


def test_hsts_only_in_production():
    client = TestClient(_make_app())
    resp = client.get("/test")
    assert "strict-transport-security" in resp.headers

    # Dev environment should NOT have HSTS
    app_dev = FastAPI()
    app_dev.add_middleware(SecurityHeadersMiddleware, environment="dev")

    @app_dev.get("/test")
    def test_endpoint():
        return {"ok": True}

    client_dev = TestClient(app_dev)
    resp_dev = client_dev.get("/test")
    assert "strict-transport-security" not in resp_dev.headers
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_middleware.py -v`
Expected: FAIL — `cvp.middleware` doesn't exist.

- [ ] **Step 3: Create middleware.py**

Create `src/cvp/middleware.py`:

```python
"""Security middleware for HTTP headers."""

import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to every response."""

    def __init__(self, app, environment: str = "production") -> None:
        super().__init__(app)
        self.environment = environment

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["X-Request-ID"] = str(uuid.uuid4())
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' https://unpkg.com; "
            "style-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com; "
            "img-src 'self' data:; "
            "connect-src 'self'"
        )

        if self.environment in ("production", "preview"):
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )

        return response
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_middleware.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cvp/middleware.py tests/test_middleware.py
git commit -m "feat: security headers middleware"
```

---

### Task 7: Create auth router (login, logout, register, refresh)

**Files:**
- Create: `src/cvp/routers/auth.py`
- Create: `src/cvp/templates/splash.html`
- Create: `src/cvp/templates/login.html`
- Create: `src/cvp/templates/register.html`
- Test: `tests/test_auth_routes.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_auth_routes.py`:

```python
"""Integration tests for auth routes."""

import pytest
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from cvp.models import Base
from cvp.models_auth import Group, User, RefreshToken
from cvp.auth import hash_password, hash_token, create_refresh_token_value


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def seeded_db(db_session):
    """Seed a test DB with a group and user."""
    group = Group(id="g1", name="Test Internal", kind="internal")
    db_session.add(group)
    user = User(
        id="u1",
        email="admin@test.com",
        display_name="Admin",
        password_hash=hash_password("correcthorse12"),
        system_role="system_admin",
        group_id="g1",
    )
    db_session.add(user)
    db_session.commit()
    return db_session


@pytest.fixture
def client(seeded_db):
    from cvp.main import app
    from cvp.db import get_db

    def override_get_db():
        try:
            yield seeded_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_splash_page(client):
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 200
    assert "Sign In" in resp.text


def test_login_page(client):
    resp = client.get("/login")
    assert resp.status_code == 200
    assert "email" in resp.text.lower()


def test_login_success(client):
    resp = client.post(
        "/api/auth/login",
        data={"email": "admin@test.com", "password": "correcthorse12"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "cvp_access" in resp.cookies
    assert "cvp_refresh" in resp.cookies
    assert "cvp_csrf" in resp.cookies


def test_login_wrong_password(client):
    resp = client.post(
        "/api/auth/login",
        data={"email": "admin@test.com", "password": "wrongpassword1"},
    )
    assert resp.status_code == 401


def test_login_nonexistent_user(client):
    resp = client.post(
        "/api/auth/login",
        data={"email": "nobody@test.com", "password": "doesntmatter1"},
    )
    assert resp.status_code == 401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_auth_routes.py::test_splash_page -v`
Expected: FAIL — auth router not mounted yet.

- [ ] **Step 3: Create splash.html template**

Create `src/cvp/templates/splash.html`:

```html
<!doctype html>
<html lang="en" class="h-full bg-gray-50">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Contents Valuation Platform</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="h-full">
  <div class="flex min-h-full flex-col justify-center py-12 sm:px-6 lg:px-8">
    <div class="sm:mx-auto sm:w-full sm:max-w-md text-center">
      <h1 class="text-3xl font-bold tracking-tight text-gray-900">
        Contents Valuation Platform
      </h1>
      <p class="mt-2 text-sm text-gray-600">
        Expert documentation and valuation services
      </p>
      <div class="mt-8">
        <a href="/login"
           class="rounded-md bg-indigo-600 px-6 py-3 text-sm font-semibold text-white shadow-sm hover:bg-indigo-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600">
          Sign In
        </a>
      </div>
    </div>
  </div>
</body>
</html>
```

- [ ] **Step 4: Create login.html template**

Create `src/cvp/templates/login.html`:

```html
<!doctype html>
<html lang="en" class="h-full bg-gray-50">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Sign In — CVP</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="h-full">
  <div class="flex min-h-full flex-col justify-center py-12 sm:px-6 lg:px-8">
    <div class="sm:mx-auto sm:w-full sm:max-w-md">
      <h2 class="mt-6 text-center text-2xl font-bold tracking-tight text-gray-900">
        Sign in to your account
      </h2>
    </div>
    <div class="mt-8 sm:mx-auto sm:w-full sm:max-w-md">
      <div class="bg-white py-8 px-4 shadow sm:rounded-lg sm:px-10">
        {% if error %}
        <div class="mb-4 rounded-md bg-red-50 p-4">
          <p class="text-sm text-red-700">{{ error }}</p>
        </div>
        {% endif %}
        {% if message %}
        <div class="mb-4 rounded-md bg-green-50 p-4">
          <p class="text-sm text-green-700">{{ message }}</p>
        </div>
        {% endif %}
        <form method="POST" action="/api/auth/login" class="space-y-6">
          <input type="hidden" name="next" value="{{ next_url or '' }}" />
          <div>
            <label for="email" class="block text-sm font-medium text-gray-700">Email address</label>
            <input id="email" name="email" type="email" autocomplete="email" required
                   class="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-indigo-500 sm:text-sm" />
          </div>
          <div>
            <label for="password" class="block text-sm font-medium text-gray-700">Password</label>
            <input id="password" name="password" type="password" autocomplete="current-password" required
                   class="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-indigo-500 sm:text-sm" />
          </div>
          <div>
            <button type="submit"
                    class="flex w-full justify-center rounded-md bg-indigo-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-indigo-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600">
              Sign in
            </button>
          </div>
        </form>
      </div>
    </div>
  </div>
</body>
</html>
```

- [ ] **Step 5: Create register.html template**

Create `src/cvp/templates/register.html`:

```html
<!doctype html>
<html lang="en" class="h-full bg-gray-50">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Create Account — CVP</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="h-full">
  <div class="flex min-h-full flex-col justify-center py-12 sm:px-6 lg:px-8">
    <div class="sm:mx-auto sm:w-full sm:max-w-md">
      <h2 class="mt-6 text-center text-2xl font-bold tracking-tight text-gray-900">
        Create your account
      </h2>
    </div>
    <div class="mt-8 sm:mx-auto sm:w-full sm:max-w-md">
      <div class="bg-white py-8 px-4 shadow sm:rounded-lg sm:px-10">
        {% if error %}
        <div class="mb-4 rounded-md bg-red-50 p-4">
          <p class="text-sm text-red-700">{{ error }}</p>
        </div>
        {% endif %}
        {% if invalid %}
        <div class="text-center">
          <p class="text-sm text-gray-600">This invite link is no longer valid.</p>
          <p class="mt-2 text-sm text-gray-500">Contact your administrator for a new invite.</p>
        </div>
        {% else %}
        <form method="POST" action="/api/auth/register" class="space-y-6">
          <input type="hidden" name="invite_code" value="{{ invite_code }}" />
          <div>
            <label class="block text-sm font-medium text-gray-700">Email</label>
            <p class="mt-1 text-sm text-gray-900">{{ email }}</p>
          </div>
          <div>
            <label for="display_name" class="block text-sm font-medium text-gray-700">Display name</label>
            <input id="display_name" name="display_name" type="text" required
                   class="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-indigo-500 sm:text-sm" />
          </div>
          <div>
            <label for="password" class="block text-sm font-medium text-gray-700">Password</label>
            <input id="password" name="password" type="password" required minlength="12"
                   class="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-indigo-500 sm:text-sm" />
            <p class="mt-1 text-xs text-gray-500">Minimum 12 characters</p>
          </div>
          <div>
            <label for="password_confirm" class="block text-sm font-medium text-gray-700">Confirm password</label>
            <input id="password_confirm" name="password_confirm" type="password" required minlength="12"
                   class="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-indigo-500 sm:text-sm" />
          </div>
          <div>
            <button type="submit"
                    class="flex w-full justify-center rounded-md bg-indigo-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-indigo-500">
              Create Account
            </button>
          </div>
        </form>
        {% endif %}
      </div>
    </div>
  </div>
</body>
</html>
```

- [ ] **Step 6: Create auth router**

Create `src/cvp/routers/auth.py`:

```python
"""Authentication endpoints: login, logout, register, refresh."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from cvp.auth import (
    create_access_token,
    create_refresh_token_value,
    generate_invite_code,
    hash_password,
    hash_token,
    validate_password_strength,
    verify_password,
)
from cvp.config import settings
from cvp.db import get_db
from cvp.dependencies import CurrentUser, get_current_user
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
def login_page(request: Request, next: str = "", error: str = "", message: str = "") -> HTMLResponse:
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
            context={"error": "Account is deactivated. Contact your administrator.", "next_url": next},
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
        expires_at=datetime.now(tz=timezone.utc) + timedelta(days=settings.jwt_refresh_ttl_days),
    )
    db.add(refresh_record)

    # Update last_login_at
    user.last_login_at = datetime.now(tz=timezone.utc)
    db.commit()

    # Build response with cookies
    redirect_url = next if next else "/dashboard"
    response = RedirectResponse(url=redirect_url, status_code=303)
    _set_auth_cookies(response, access_token, raw_refresh, hash_token(access_token)[:32])

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
) -> RedirectResponse | HTMLResponse:
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

    # Redirect back to where they were
    next_url = request.headers.get("referer", "/dashboard")
    response = RedirectResponse(url=next_url, status_code=303)
    _set_auth_cookies(response, access_token, raw_refresh, hash_token(access_token)[:32])
    return response


@router.get("/register/{invite_code}", response_class=HTMLResponse)
def register_page(request: Request, invite_code: str, db: Session = Depends(get_db)) -> HTMLResponse:
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

    # Set password and clear invite
    user.display_name = display_name.strip()
    user.password_hash = hash_password(password)
    user.invite_code = None
    user.invite_expires_at = None
    user.password_changed_at = datetime.now(tz=timezone.utc)
    db.commit()

    return RedirectResponse(url="/login?message=Account+created.+Please+sign+in.", status_code=303)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/test_auth_routes.py -v`
Expected: Tests likely still fail because `main.py` hasn't mounted the auth router yet. That's Task 8.

- [ ] **Step 8: Commit (auth router + templates)**

```bash
git add src/cvp/routers/auth.py src/cvp/templates/splash.html src/cvp/templates/login.html src/cvp/templates/register.html tests/test_auth_routes.py
git commit -m "feat: auth router — login, logout, register, refresh endpoints + templates"
```

---

### Task 8: Wire auth into main.py and update base.html

**Files:**
- Modify: `src/cvp/main.py`
- Modify: `src/cvp/templates/base.html`

- [ ] **Step 1: Update main.py**

Replace `src/cvp/main.py` with:

```python
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import selectinload

from cvp.config import settings
from cvp.db import SessionLocal
from cvp.dependencies import CurrentUser, require_active_user
from cvp.middleware import SecurityHeadersMiddleware
from cvp.models import Matter
from cvp.routers import auth, crops, evidence, exports, items, matters, rooms, serp, vision

BASE_DIR = Path(__file__).parent

app = FastAPI(title="Contents Valuation Platform")

# Security headers middleware
app.add_middleware(SecurityHeadersMiddleware, environment=settings.environment)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

# Auth router (public routes — splash, login, register)
app.include_router(auth.router)

# Protected routers
app.include_router(matters.router)
app.include_router(evidence.router)
app.include_router(rooms.router)
app.include_router(items.router)
app.include_router(vision.router)
app.include_router(serp.router)
app.include_router(crops.router)
app.include_router(exports.router)

templates = Jinja2Templates(directory=BASE_DIR / "templates")


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    request: Request,
    user: CurrentUser = Depends(require_active_user),
) -> HTMLResponse:
    db = SessionLocal()
    try:
        all_matters = (
            db.query(Matter)
            .options(selectinload(Matter.items))
            .order_by(Matter.status, Matter.target_delivery_date)
            .all()
        )
    finally:
        db.close()
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"matters": all_matters, "user": user},
    )


def run_dev() -> None:
    import uvicorn

    uvicorn.run("cvp.main:app", host="127.0.0.1", port=settings.port, reload=True)
```

Note: The old `GET /` dashboard route is replaced by:
- `GET /` in `auth.router` (splash page)
- `GET /dashboard` here (authenticated matter list)

- [ ] **Step 2: Update base.html with user nav**

Replace `src/cvp/templates/base.html`:

```html
<!doctype html>
<html lang="en" class="h-full bg-gray-50">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{% block title %}CVP{% endblock %} — Contents Valuation Platform</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://unpkg.com/htmx.org@1.9.12"></script>
  <script src="/static/app.js" defer></script>
  <script>
    // CSRF: read cvp_csrf cookie and set it as X-CSRF-Token header on all HTMX requests
    document.addEventListener('DOMContentLoaded', function() {
      var csrf = document.cookie.split('; ').find(c => c.startsWith('cvp_csrf='));
      if (csrf) {
        document.body.setAttribute('hx-headers', JSON.stringify({'X-CSRF-Token': csrf.split('=')[1]}));
      }
    });
  </script>
</head>
<body class="h-full">
  <nav class="bg-white border-b border-gray-200">
    <div class="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
      <div class="flex h-14 items-center justify-between">
        <a href="/dashboard" class="text-base font-semibold text-gray-900">Contents Valuation Platform</a>
        <div class="flex items-center gap-4">
          <a href="/matters/new"
             class="rounded-md bg-indigo-600 px-3 py-1.5 text-sm font-semibold text-white shadow-sm hover:bg-indigo-500">
            New matter
          </a>
          {% if user %}
          <span class="text-sm text-gray-600">{{ user.display_name or user.email }}</span>
          <form method="POST" action="/api/auth/logout" class="inline">
            <button type="submit" class="text-sm text-gray-500 hover:text-gray-700">Sign out</button>
          </form>
          {% endif %}
        </div>
      </div>
    </div>
  </nav>
  <main class="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-8">
    {% block content %}{% endblock %}
  </main>
</body>
</html>
```

- [ ] **Step 3: Run all tests**

Run: `uv run pytest -v`
Expected: All existing tests still pass. Auth route tests pass.

- [ ] **Step 4: Commit**

```bash
git add src/cvp/main.py src/cvp/templates/base.html
git commit -m "feat: wire auth middleware + router into app, move dashboard to /dashboard"
```

---

### Task 9: Add require_active_user to all existing routers

**Files:**
- Modify: `src/cvp/routers/matters.py`
- Modify: `src/cvp/routers/evidence.py`
- Modify: `src/cvp/routers/items.py`
- Modify: `src/cvp/routers/rooms.py`
- Modify: `src/cvp/routers/vision.py`
- Modify: `src/cvp/routers/serp.py`
- Modify: `src/cvp/routers/crops.py`
- Modify: `src/cvp/routers/exports.py`

This is the critical step that makes the app require authentication. Every route handler must accept a `user: CurrentUser = Depends(require_active_user)` parameter. The `/crops/{path}` endpoint uses `optional_user` instead (public access for Google Lens).

- [ ] **Step 1: Update matters.py**

Add imports at top:

```python
from fastapi import APIRouter, Depends, Form, Request
from cvp.dependencies import CurrentUser, require_active_user
```

Add `user: CurrentUser = Depends(require_active_user)` as a parameter to every route function:

- `new_matter_form(request, user = Depends(require_active_user))`
- `create_matter(request, user = Depends(require_active_user), ...)`
- `matter_detail(request, matter_id, user = Depends(require_active_user))`
- `update_matter(matter_id, user = Depends(require_active_user), ...)`
- `update_matter_status(matter_id, user = Depends(require_active_user), ...)`
- `matter_preview(request, matter_id, user = Depends(require_active_user))`

Pass `user` to template context in `matter_detail` and `matter_preview` so `base.html` can render it.

- [ ] **Step 2: Update evidence.py**

Add imports:

```python
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from cvp.dependencies import CurrentUser, require_active_user
```

Add `user: CurrentUser = Depends(require_active_user)` to:

- `upload_evidence(matter_id, files, user = Depends(require_active_user))`
- `delete_evidence(file_id, user = Depends(require_active_user))`
- `serve_file(stored_path, user = Depends(require_active_user))`

- [ ] **Step 3: Update items.py**

Add imports:

```python
from fastapi import APIRouter, Depends, Form, HTTPException
from cvp.dependencies import CurrentUser, require_active_user
```

Add `user: CurrentUser = Depends(require_active_user)` to all 7 route functions.

- [ ] **Step 4: Update rooms.py**

Add imports and `user` param to all 3 route functions.

- [ ] **Step 5: Update vision.py**

Add imports and `user` param to both route functions.

- [ ] **Step 6: Update serp.py**

Add imports. For `serve_crop`, use `optional_user` instead (public):

```python
from cvp.dependencies import CurrentUser, optional_user, require_active_user
```

- `serve_crop(crop_path, user = Depends(optional_user))` — stays public
- `serp_panel(item_id, user = Depends(require_active_user))`
- `run_google_lens(item_id, crop_id, user = Depends(require_active_user), ...)`
- `serp_apply(item_id, user = Depends(require_active_user), ...)`

- [ ] **Step 7: Update crops.py**

Add imports and `user` param to all 4 route functions.

- [ ] **Step 8: Update exports.py**

Add imports and `user` param to all 3 route functions.

- [ ] **Step 9: Run all tests**

Run: `uv run pytest -v`
Expected: Some existing tests may need updates to provide auth context. Fix test fixtures to inject a test user or override the dependency:

```python
from cvp.dependencies import require_active_user, CurrentUser

def _override_user():
    return CurrentUser(
        id="test-user",
        email="test@test.com",
        system_role="system_admin",
        group_id="g1",
        group_kind="internal",
    )

app.dependency_overrides[require_active_user] = _override_user
```

- [ ] **Step 10: Commit**

```bash
git add src/cvp/routers/
git commit -m "feat: add require_active_user guard to all existing routes"
```

---

### Task 10: Create auth seed script

**Files:**
- Create: `src/cvp/seed_auth.py`
- Modify: `pyproject.toml` (add script entry)

- [ ] **Step 1: Create seed_auth.py**

Create `src/cvp/seed_auth.py`:

```python
"""Seed initial System Admin user and Internal group.

Entry point: uv run seed-auth
Idempotent: safe to run multiple times.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from cvp.auth import generate_invite_code, hash_password, hash_token
from cvp.db import SessionLocal
from cvp.models_auth import Group, User


def seed_auth(db: Session) -> None:
    """Create the Internal group and first System Admin if they don't exist."""
    # Create Internal group
    internal_group = db.query(Group).filter(Group.kind == "internal").first()
    if internal_group is None:
        internal_group = Group(
            name="Contents Valuation LLC",
            kind="internal",
        )
        db.add(internal_group)
        db.flush()
        print(f"Created Internal group: {internal_group.name} (id: {internal_group.id})")
    else:
        print(f"Internal group already exists: {internal_group.name}")

    # Create System Admin user with invite code
    admin = db.query(User).filter(User.system_role == "system_admin").first()
    if admin is None:
        raw_invite = generate_invite_code()
        admin = User(
            email="admin@contentsvaluation.com",
            display_name="System Admin",
            password_hash="__invite_pending__",  # Not a valid bcrypt hash
            system_role="system_admin",
            group_id=internal_group.id,
            invite_code=hash_token(raw_invite),
            invite_expires_at=datetime.now(tz=timezone.utc) + timedelta(days=7),
        )
        db.add(admin)
        db.flush()
        print(f"Created System Admin: {admin.email}")
        print(f"Invite URL: /register/{raw_invite}")
        print("(This invite expires in 7 days)")
    else:
        print(f"System Admin already exists: {admin.email}")

    db.commit()


def main() -> None:
    db = SessionLocal()
    try:
        seed_auth(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Add script entry to pyproject.toml**

Add to `[project.scripts]`:

```toml
[project.scripts]
dev = "cvp.main:run_dev"
seed = "cvp.seed:main"
seed-auth = "cvp.seed_auth:main"
```

- [ ] **Step 3: Run seed-auth**

Run: `uv run seed-auth`
Expected: Outputs the Internal group ID and a System Admin invite URL.

- [ ] **Step 4: Commit**

```bash
git add src/cvp/seed_auth.py pyproject.toml
git commit -m "feat: seed-auth script — initial System Admin + Internal group"
```

---

### Task 11: Add HTMX CSRF configuration to app.js

**Files:**
- Modify: `src/cvp/static/app.js`

- [ ] **Step 1: Update app.js**

The CSRF header setup is already in `base.html` (Task 8). Verify that the `hx-headers` attribute is being set on `document.body` before any HTMX requests fire. If HTMX is loaded before the DOM script runs, the `hx-headers` attribute will be picked up automatically.

No changes needed to `app.js` unless testing reveals CSRF issues with HTMX requests. The inline script in `base.html` handles it.

- [ ] **Step 2: Manual test**

Start the dev server: `uv run dev`

1. Visit `http://localhost:8000/` — should see splash page
2. Click "Sign In" — should see login form
3. Run `uv run seed-auth` if not done already, note the invite URL
4. Visit the invite URL — should see registration form
5. Register with a password (12+ chars)
6. Log in — should redirect to `/dashboard`
7. Verify "Sign out" link is in the nav
8. Click "Sign out" — should redirect to splash

- [ ] **Step 3: Commit any fixes**

```bash
git add -A
git commit -m "fix: CSRF and auth flow polish from manual testing"
```

---

### Task 12: Run full test suite and fix regressions

**Files:**
- All test files

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest -v`
Expected: Identify any tests broken by the auth changes.

- [ ] **Step 2: Fix broken tests**

For each failing test, add the dependency override:

```python
from cvp.dependencies import require_active_user, CurrentUser

@pytest.fixture(autouse=True)
def override_auth(monkeypatch):
    """Bypass auth for existing tests."""
    async def mock_user():
        return CurrentUser(
            id="test-user",
            email="test@test.com",
            system_role="system_admin",
            group_id="g1",
            group_kind="internal",
        )

    from cvp.main import app
    app.dependency_overrides[require_active_user] = mock_user
    yield
    app.dependency_overrides.clear()
```

- [ ] **Step 3: Run ruff**

Run: `uv run ruff check . && uv run ruff format .`
Expected: Clean.

- [ ] **Step 4: Run full test suite again**

Run: `uv run pytest -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/
git commit -m "test: fix existing tests for auth dependency injection"
```

---

### Task 13: Dev auto-login for local development

**Files:**
- Modify: `src/cvp/dependencies.py`

- [ ] **Step 1: Add auto-login logic**

In `src/cvp/dependencies.py`, update `get_current_user` to check for dev auto-login:

```python
async def get_current_user(request: Request) -> CurrentUser:
    """Extract and validate JWT from request. Raises 401 if invalid."""
    # Dev auto-login: skip JWT validation entirely
    if settings.environment == "dev" and settings.auto_login_user_id:
        from sqlalchemy.orm import Session
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

    _validate_csrf(request, source)
    return user
```

- [ ] **Step 2: Set auto-login in .env for dev**

After running `seed-auth` and registering, set `AUTO_LOGIN_USER_ID` in `.env` to the admin user's UUID.

- [ ] **Step 3: Commit**

```bash
git add src/cvp/dependencies.py
git commit -m "feat: dev auto-login bypasses JWT when AUTO_LOGIN_USER_ID is set"
```

---

### Task 14: Final verification

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests PASS.

- [ ] **Step 2: Run linter**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: Clean.

- [ ] **Step 3: Manual smoke test**

1. Start server: `uv run dev`
2. Unset `AUTO_LOGIN_USER_ID` temporarily
3. Visit `http://localhost:8000/` — splash page
4. Try to visit `/dashboard` — redirected to `/login`
5. Try to visit `/matters/new` — redirected to `/login` (or 401)
6. Visit `/crops/...` for an existing crop — should still work (public)
7. Log in with seeded admin — should reach dashboard
8. Navigate through matters, items, evidence — all work
9. Sign out — back to splash

- [ ] **Step 4: Commit any final fixes**

```bash
git add -A
git commit -m "chore: phase 1 complete — core auth infrastructure"
```
