"""TTL cache for the matter-access decision used by `require_matter_role`.

Browsers fan out 50+ concurrent thumbnail requests on a single matter page
load. Each one runs `_check_matter_access`, which does two DB queries. The
cache makes a burst of N thumbnail requests cost 1 DB check + (N-1) cache
hits, preventing the SQLAlchemy `QueuePool timeout` we saw after PR #17.

Cache key is (user_id, matter_id, minimum_role); value is bool. TTL is 60 s.
System admins short-circuit before the cache so admin grants never end up
cached or shared with non-admins.

Worst-case staleness after a role change is `_TTL_SECONDS`. Wiring of
`invalidate_matter` / `invalidate_user` into MatterAccess and user-role
mutation paths is tracked as a follow-up in the spec's Backlog.
"""

import time
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from cvp import dependencies as _deps

if TYPE_CHECKING:
    from cvp.dependencies import CurrentUser

_TTL_SECONDS: float = 60.0
_MAX_ENTRIES: int = 1024
_EVICT_BATCH: int = 256

# key -> (loaded_at, allowed)
_cache: dict[tuple[str, str, str], tuple[float, bool]] = {}


def _now() -> float:
    """Wall clock — split out so tests can monkeypatch."""
    return time.time()


def _check_matter_access(
    db: Session,
    user: "CurrentUser",
    matter_id: str,
    minimum_role: str,
) -> bool:
    """Indirection through `cvp.dependencies` so that tests which monkeypatch
    `cvp.dependencies._check_matter_access` are honored here too. Tests that
    want to stub the cache's view of access can also monkeypatch this name
    directly (`access_cache._check_matter_access`).
    """
    return _deps._check_matter_access(db, user, matter_id, minimum_role)


def _evict_oldest() -> None:
    """Drop the `_EVICT_BATCH` oldest entries in one sweep."""
    items = sorted(_cache.items(), key=lambda kv: kv[1][0])
    for key, _ in items[:_EVICT_BATCH]:
        _cache.pop(key, None)


def check_matter_access_cached(
    db: Session,
    user: "CurrentUser",
    matter_id: str,
    minimum_role: str,
) -> bool:
    """Cached wrapper around `_check_matter_access`. System admins skip the cache."""
    if user.system_role == "system_admin":
        return True

    key = (user.id, matter_id, minimum_role)
    entry = _cache.get(key)
    if entry is not None:
        loaded_at, allowed = entry
        if (_now() - loaded_at) < _TTL_SECONDS:
            return allowed

    allowed = _check_matter_access(db, user, matter_id, minimum_role)
    _cache[key] = (_now(), allowed)
    if len(_cache) > _MAX_ENTRIES:
        _evict_oldest()
    return allowed


def invalidate_matter(matter_id: str) -> None:
    """Drop every cache entry for `matter_id` (call when access on a matter changes)."""
    for key in list(_cache.keys()):
        if key[1] == matter_id:
            _cache.pop(key, None)


def invalidate_user(user_id: str) -> None:
    """Drop every cache entry for `user_id` (call when the user's role changes)."""
    for key in list(_cache.keys()):
        if key[0] == user_id:
            _cache.pop(key, None)
