"""Runtime-configurable settings backed by the `app_setting` DB table.

Defaults come from `claimos.config.Settings` (env vars / .env). A row in
`app_setting` with the matching key, when present, supersedes the env default.

Reads are cached in-process for a short TTL to avoid hammering the DB on every
request. Writes via `set_value` invalidate the cache immediately so admin edits
take effect on the next request.
"""

import json
import time
from typing import Any

from sqlalchemy.orm import Session

from claimos.config import settings
from claimos.models_app_setting import AppSetting

_TTL_SECONDS: float = 30.0
_cache: dict[str, tuple[float, Any]] = {}  # key -> (loaded_at, value)


# Bounds enforced on read: any DB value outside the range is ignored, falling
# back to the env default. Admin UI also enforces these on write.
_BOUNDS: dict[str, tuple[int, int]] = {
    "evidence_upload_concurrency": (1, 16),
    "evidence_upload_max_file_mb": (1, 100),
    "evidence_upload_max_batch_count": (1, 5000),
}


def _now() -> float:
    """Wall clock — split out so tests can monkeypatch."""
    return time.time()


def _env_default(key: str) -> Any:
    return getattr(settings, key)


def _load_from_db(db: Session, key: str) -> Any:
    row = db.query(AppSetting).filter_by(key=key).first()
    if row is None:
        return _env_default(key)
    try:
        value = json.loads(row.value_json)
    except (json.JSONDecodeError, TypeError):
        return _env_default(key)
    bounds = _BOUNDS.get(key)
    if bounds and isinstance(value, int):
        lo, hi = bounds
        if value < lo or value > hi:
            return _env_default(key)
    return value


def get_int(db: Session, key: str) -> int:
    """Return the current int value for `key`, using the DB override if present."""
    cached = _cache.get(key)
    if cached is not None:
        loaded_at, value = cached
        if (_now() - loaded_at) < _TTL_SECONDS:
            return int(value)
    value = _load_from_db(db, key)
    _cache[key] = (_now(), value)
    return int(value)


def set_value(db: Session, key: str, value: Any, *, updated_by_user_id: str | None) -> None:
    """Write a value to `app_setting`, invalidating the in-process cache."""
    bounds = _BOUNDS.get(key)
    if bounds and isinstance(value, int):
        lo, hi = bounds
        if value < lo or value > hi:
            raise ValueError(f"{key}={value} out of bounds {bounds}")
    row = db.query(AppSetting).filter_by(key=key).first()
    if row is None:
        row = AppSetting(
            key=key, value_json=json.dumps(value), updated_by_user_id=updated_by_user_id
        )
        db.add(row)
    else:
        row.value_json = json.dumps(value)
        row.updated_by_user_id = updated_by_user_id
    db.commit()
    _cache.pop(key, None)
