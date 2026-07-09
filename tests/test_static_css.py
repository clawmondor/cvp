from fastapi.testclient import TestClient

from claimos.main import app

client = TestClient(app)


def test_splash_links_selfhosted_css_not_cdn():
    r = client.get("/")
    assert r.status_code == 200
    assert "/static/app.css" in r.text
    assert "cdn.tailwindcss.com" not in r.text


def test_csp_drops_cdn_keeps_style_unsafe_inline():
    r = client.get("/")
    csp = r.headers["content-security-policy"]
    assert "cdn.tailwindcss.com" not in csp
    # dynamic style="" attributes (e.g. progress bars) still need this:
    assert "style-src 'self' 'unsafe-inline'" in csp
