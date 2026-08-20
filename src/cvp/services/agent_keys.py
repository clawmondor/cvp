"""Generation, hashing, and prefix parsing for external agent API keys.

Full key format: ``agk_live_<prefix>_<secret>``. Only ``key_prefix`` and the
SHA-256 ``key_hash`` are persisted; the full key is shown once at creation.
"""

import hashlib
import secrets

_KEY_NAMESPACE = "agk_live"


def generate_key() -> tuple[str, str, str]:
    """Return (full_key, key_prefix, key_hash)."""
    prefix = secrets.token_hex(4)  # 8 hex chars, non-secret lookup key
    secret = secrets.token_urlsafe(24)
    full_key = f"{_KEY_NAMESPACE}_{prefix}_{secret}"
    return full_key, prefix, hash_key(full_key)


def hash_key(full_key: str) -> str:
    return hashlib.sha256(full_key.encode("utf-8")).hexdigest()


def parse_prefix(full_key: str) -> str | None:
    parts = full_key.split("_")
    # ["agk", "live", "<prefix>", "<secret>"]
    if len(parts) < 4 or parts[0] != "agk" or parts[1] != "live":
        return None
    return parts[2]
