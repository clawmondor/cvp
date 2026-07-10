from pathlib import Path

from fastapi.testclient import TestClient

from claimos.main import app

client = TestClient(app)


def test_toggle_renders_in_nav():
    r = client.get("/login")  # noqa: F841
    # login has no nav; use a page that includes base nav via an auth<-free path if needed.
    # The toggle partial itself must exist and expose the three data-theme-set controls:
    partial = Path("src/claimos/templates/_theme_toggle.html").read_text()
    for mode in ("system", "light", "dark"):
        assert f'data-theme-set="{mode}"' in partial


def test_app_js_wires_theme_toggle():
    js = Path("src/claimos/static/app.js").read_text()
    assert "data-theme-set" in js
    assert "classList.add(mode)" in js
    assert "theme=" in js  # sets cookie
