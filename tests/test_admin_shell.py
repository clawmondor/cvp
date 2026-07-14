"""Tests for the role-aware admin nav partial and its gating in the app sidebar."""

import types

from claimos.templating import templates


def _user(role):
    return types.SimpleNamespace(system_role=role)


def _render_admin(role, path, group=None, unread_count=0) -> str:
    tmpl = templates.env.get_template("_admin_sidebar.html")
    request = types.SimpleNamespace(url=types.SimpleNamespace(path=path))
    return tmpl.render(request=request, user=_user(role), group=group, unread_count=unread_count)


def _render_app_sidebar(path, user=None, group=None) -> str:
    tmpl = templates.env.get_template("_app_sidebar.html")
    request = types.SimpleNamespace(url=types.SimpleNamespace(path=path))
    return tmpl.render(request=request, user=user, group=group, claim=None)


def test_admin_nav_system_role_links():
    html = _render_admin("system_admin", "/admin/system/")
    for href in (
        "/admin/system/users",
        "/admin/system/groups",
        "/admin/system/claims",
        "/admin/system/feedback",
        "/admin/system/audit",
        "/admin/vision-models",
        "/admin/system/runtime-config",
    ):
        assert f'href="{href}"' in html
    assert "/admin/internal/" not in html


def test_admin_nav_internal_role_links():
    html = _render_admin("internal_admin", "/admin/internal/")
    assert 'href="/admin/internal/users"' in html
    assert 'href="/admin/internal/claims"' in html
    assert 'href="/admin/internal/groups"' in html
    assert "/admin/system/" not in html


def test_admin_nav_org_role_carries_group_id():
    group = types.SimpleNamespace(id="g1")
    html = _render_admin("external_admin", "/admin/org/users", group=group)
    assert 'href="/admin/org/users?group_id=g1"' in html
    assert 'href="/admin/org/claims?group_id=g1"' in html
    assert 'href="/admin/org/profile?group_id=g1"' in html


def test_admin_nav_active_state():
    html = _render_admin("system_admin", "/admin/system/users")
    # The Users link is active; find its anchor and confirm the active token.
    import re

    anchors = re.findall(r'<a\s+href="[^"]*".*?</a>', html, re.DOTALL)
    users = next(a for a in anchors if 'href="/admin/system/users"' in a)
    assert "bg-primary-subtle" in users


def test_admin_nav_feedback_badge():
    html = _render_admin("system_admin", "/admin/system/", unread_count=4)
    assert ">4<" in html


def test_app_sidebar_shows_admin_group_under_admin_path():
    html = _render_app_sidebar("/admin/system/", user=_user("system_admin"))
    assert "Admin" in html
    assert 'href="/admin/system/audit"' in html


def test_app_sidebar_hides_admin_group_off_admin_path():
    html = _render_app_sidebar("/dashboard", user=_user("system_admin"))
    assert 'href="/admin/system/audit"' not in html
