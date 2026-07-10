"""Tests for the sidebar app shell and its nav partial."""

import types

from claimos.templating import templates


def _render_sidebar(path: str, claim=None) -> str:
    tmpl = templates.env.get_template("_app_sidebar.html")
    request = types.SimpleNamespace(url=types.SimpleNamespace(path=path))
    return tmpl.render(request=request, claim=claim)


def test_sidebar_global_group_always_present():
    html = _render_sidebar("/dashboard")
    assert 'href="/"' in html  # Dashboard
    assert 'href="/dashboard"' in html  # Claims
    assert "Claims" in html


def test_sidebar_hides_claim_group_without_claim():
    html = _render_sidebar("/dashboard")
    assert "Rooms & Groups" not in html
    assert "Evidence" not in html


def test_sidebar_shows_claim_group_with_claim():
    claim = types.SimpleNamespace(id="m1")
    html = _render_sidebar("/claims/m1", claim=claim)
    assert "Claim Detail" in html
    assert 'href="/claims/m1#rooms"' in html
    assert 'href="/claims/m1#evidence"' in html
    assert 'href="/claims/m1#items"' in html
    assert 'href="/claims/m1#preview"' in html
    assert 'href="/claims/m1#export"' in html


def test_sidebar_active_state_on_dashboard():
    html = _render_sidebar("/")
    # The Dashboard link (href="/") carries the active tokens.
    assert "bg-primary-subtle" in html
