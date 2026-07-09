import subprocess
from pathlib import Path

APP_CSS = Path("src/claimos/static/app.css")
SELECTORS = [
    ".card",
    ".input",
    ".btn-primary",
    ".btn-secondary",
    ".badge-success",
    ".badge-error",
    ".badge-warning",
]


def test_component_classes_emit_in_app_css():
    # ensure a fresh build, then confirm every component selector is present
    subprocess.run(["uv", "run", "css"], check=True)
    css = APP_CSS.read_text()
    missing = [
        s for s in SELECTORS if s + "{" not in css and s + " {" not in css and s + "," not in css
    ]
    assert not missing, f"missing component selectors in app.css: {missing}"
