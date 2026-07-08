"""Tests for the matter-access TTL cache."""

import pytest

from claimos.dependencies import CurrentUser
from claimos.services import access_cache


@pytest.fixture(autouse=True)
def clear_cache():
    access_cache._cache.clear()
    yield
    access_cache._cache.clear()


def _user(user_id: str = "u1", role: str = "internal_user") -> CurrentUser:
    return CurrentUser(
        id=user_id,
        email=f"{user_id}@test.com",
        system_role=role,
        group_id=None,
        group_kind="internal",
    )


def test_first_call_misses_then_caches(monkeypatch):
    calls = []

    def fake_check(db, user, matter_id, minimum_role):
        calls.append((user.id, matter_id, minimum_role))
        return True

    monkeypatch.setattr(access_cache, "_check_matter_access", fake_check)
    assert access_cache.check_matter_access_cached(None, _user(), "m1", "viewer") is True
    assert access_cache.check_matter_access_cached(None, _user(), "m1", "viewer") is True
    # Second call hit the cache; underlying check ran only once.
    assert len(calls) == 1


def test_different_keys_do_not_share_entries(monkeypatch):
    monkeypatch.setattr(access_cache, "_check_matter_access", lambda *a, **k: True)
    access_cache.check_matter_access_cached(None, _user("a"), "m1", "viewer")
    access_cache.check_matter_access_cached(None, _user("b"), "m1", "viewer")
    access_cache.check_matter_access_cached(None, _user("a"), "m2", "viewer")
    access_cache.check_matter_access_cached(None, _user("a"), "m1", "manager")
    assert len(access_cache._cache) == 4


def test_system_admin_bypasses_cache(monkeypatch):
    calls = []

    def fake_check(db, user, matter_id, minimum_role):
        calls.append(user.id)
        return True

    monkeypatch.setattr(access_cache, "_check_matter_access", fake_check)
    admin = _user("admin", role="system_admin")
    access_cache.check_matter_access_cached(None, admin, "m1", "viewer")
    access_cache.check_matter_access_cached(None, admin, "m1", "viewer")
    # Admin short-circuit returns True without hitting cache or underlying check.
    assert calls == []
    assert access_cache._cache == {}


def test_ttl_expiry_triggers_recheck(monkeypatch):
    calls = []
    monkeypatch.setattr(
        access_cache,
        "_check_matter_access",
        lambda *a, **k: calls.append("x") or True,
    )
    access_cache.check_matter_access_cached(None, _user(), "m1", "viewer")
    assert len(calls) == 1

    # Fast-forward past TTL
    entry_time = access_cache._cache[("u1", "m1", "viewer")][0]
    monkeypatch.setattr(access_cache, "_now", lambda: entry_time + access_cache._TTL_SECONDS + 1)

    access_cache.check_matter_access_cached(None, _user(), "m1", "viewer")
    assert len(calls) == 2


def test_invalidate_matter_clears_only_matching_entries(monkeypatch):
    monkeypatch.setattr(access_cache, "_check_matter_access", lambda *a, **k: True)
    access_cache.check_matter_access_cached(None, _user("a"), "m1", "viewer")
    access_cache.check_matter_access_cached(None, _user("b"), "m1", "viewer")
    access_cache.check_matter_access_cached(None, _user("a"), "m2", "viewer")
    access_cache.invalidate_matter("m1")
    keys = set(access_cache._cache.keys())
    assert keys == {("a", "m2", "viewer")}


def test_invalidate_user_clears_only_matching_entries(monkeypatch):
    monkeypatch.setattr(access_cache, "_check_matter_access", lambda *a, **k: True)
    access_cache.check_matter_access_cached(None, _user("a"), "m1", "viewer")
    access_cache.check_matter_access_cached(None, _user("b"), "m1", "viewer")
    access_cache.check_matter_access_cached(None, _user("a"), "m2", "viewer")
    access_cache.invalidate_user("a")
    keys = set(access_cache._cache.keys())
    assert keys == {("b", "m1", "viewer")}


def test_eviction_when_cache_exceeds_max_size(monkeypatch):
    monkeypatch.setattr(access_cache, "_check_matter_access", lambda *a, **k: True)
    # Make eviction window small enough to be observable in a test.
    monkeypatch.setattr(access_cache, "_MAX_ENTRIES", 8)
    monkeypatch.setattr(access_cache, "_EVICT_BATCH", 3)

    base = 1_000_000.0
    for i in range(8):
        monkeypatch.setattr(access_cache, "_now", lambda i=i: base + i)
        access_cache.check_matter_access_cached(None, _user(f"u{i}"), "m", "viewer")
    assert len(access_cache._cache) == 8

    # 9th insert should trigger eviction of the 3 oldest.
    monkeypatch.setattr(access_cache, "_now", lambda: base + 100)
    access_cache.check_matter_access_cached(None, _user("u9"), "m", "viewer")
    assert len(access_cache._cache) == 6
    surviving_users = {k[0] for k in access_cache._cache}
    # Oldest three (u0, u1, u2) evicted; u3..u8 + u9 remain.
    assert "u0" not in surviving_users
    assert "u1" not in surviving_users
    assert "u2" not in surviving_users
    assert "u9" in surviving_users
