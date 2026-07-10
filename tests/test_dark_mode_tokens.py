import re
from pathlib import Path

THEME = Path("src/claimos/styles/theme.css")

# tokens that are intentionally mode-independent (single value)
SINGLE_VALUE = {"white", "black"}


def _theme_block() -> str:
    text = THEME.read_text()
    m = re.search(r"@theme\s*\{(.*?)\n\}", text, re.DOTALL)
    assert m, "no @theme block"
    return m.group(1)


def test_every_color_token_is_light_dark_except_single_value_and_admin():
    block = _theme_block()
    offenders = []
    for m in re.finditer(r"--color-([a-z0-9-]+):\s*([^;]+);", block):
        name, val = m.group(1), m.group(2).strip()
        if name in SINGLE_VALUE or name.startswith("admin-"):
            continue
        if not val.startswith("light-dark("):
            offenders.append(name)
    assert not offenders, f"color tokens missing a dark value: {offenders}"


def test_color_scheme_selectors_present():
    text = THEME.read_text()
    assert ":root      { color-scheme: light dark; }" in text or "color-scheme: light dark" in text
    assert "color-scheme: dark" in text
    assert "color-scheme: light;" in text
