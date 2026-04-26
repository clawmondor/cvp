"""JWT creation/validation, password hashing, and token utilities."""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

import bcrypt
import jwt

# Load breached passwords into a set for O(1) lookup
_BREACHED_PASSWORDS: set[str] = set()
_BREACHED_FILE = Path(__file__).parent / "data" / "pwned_passwords_top100k.txt"
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
