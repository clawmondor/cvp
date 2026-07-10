from fastapi.testclient import TestClient

from claimos.main import app


def _client_with_theme(theme: str | None) -> TestClient:
    # Per-request `cookies=` kwarg on TestClient.get() is deprecated and does not
    # reliably reach the request in this httpx version; set cookies on the client
    # instance instead, per the httpx/starlette deprecation guidance.
    client = TestClient(app)
    if theme is not None:
        client.cookies.set("theme", theme)
    return client


def test_dark_cookie_sets_html_dark_class():
    client = _client_with_theme("dark")
    r = client.get("/")
    assert r.status_code == 200
    assert (
        'class="h-full bg-neutral-50 dark"' in r.text
        or ' dark"' in r.text.split("<html", 1)[1][:80]
    )


def test_light_cookie_sets_html_light_class():
    client = _client_with_theme("light")
    r = client.get("/")
    assert " light" in r.text.split("<html", 1)[1][:80]


def test_no_cookie_no_theme_class():
    client = _client_with_theme(None)
    r = client.get("/")
    head = r.text.split("<html", 1)[1][:80]
    assert " dark" not in head and " light" not in head


def test_report_preview_template_forces_light():
    # static guarantee: the report preview shell is always light, independent of cookie
    from pathlib import Path

    html = Path("src/claimos/templates/report/preview.html").read_text()
    assert '<html lang="en" class="light">' in html
