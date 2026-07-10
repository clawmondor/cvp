import re
from pathlib import Path

THEME = Path("src/claimos/styles/theme.css")

EXPECTED = {
    "primary-subtle": "#eff6ff",
    "primary-tint": "#dbeafe",
    "primary-tint-strong": "#bfdbfe",
    "primary-light": "#3b82f6",
    "primary": "#2563eb",
    "primary-strong": "#1d4ed8",
    "neutral-50": "#f8fafc",
    "neutral-100": "#f1f5f9",
    "neutral-200": "#e2e8f0",
    "neutral-300": "#cbd5e1",
    "neutral-400": "#94a3b8",
    "neutral-500": "#64748b",
    "neutral-600": "#475569",
    "neutral-700": "#334155",
    "neutral-900": "#0f172a",
    "success-surface": "#f0fdf4",
    "success-surface-strong": "#dcfce7",
    "success-border": "#bbf7d0",
    "success-emphasis": "#16a34a",
    "success": "#15803d",
    "success-strong": "#166534",
    "error-surface": "#fef2f2",
    "error-surface-strong": "#fee2e2",
    "error-border": "#fecaca",
    "error": "#dc2626",
    "error-strong": "#b91c1c",
    "error-strongest": "#991b1b",
    "warning-surface": "#fffbeb",
    "warning-surface-strong": "#fef3c7",
    "warning-border": "#fde68a",
    "warning-emphasis": "#d97706",
    "warning": "#b45309",
    "warning-strong": "#92400e",
    "admin-300": "#b8c0cc",
    "admin-400": "#8b94a3",
    "admin-600": "#2b3340",
    "admin-700": "#161c26",
    "admin-800": "#0b0f18",
    "surface": "#ffffff",
    "white": "#ffffff",
    "black": "#000000",
}


def _tokens():
    text = THEME.read_text()
    out = {}
    for m in re.finditer(r"--color-([a-z0-9-]+):\s*([^;]+);", text):
        name, val = m.group(1), m.group(2).strip()
        ld = re.match(r"light-dark\(\s*(#[0-9a-fA-F]{6})\s*,", val)
        if ld:
            out[name] = ld.group(1).lower()
        elif re.match(r"#[0-9a-fA-F]{6}$", val):
            out[name] = val.lower()
    return out


def test_every_expected_token_present_with_correct_hex():
    toks = _tokens()
    for name, hex_ in EXPECTED.items():
        assert toks.get(name) == hex_, f"{name}: expected {hex_}, got {toks.get(name)}"


def test_font_and_radius_scales_defined():
    text = THEME.read_text()
    assert "--font-sans:" in text
    for r in ("--radius-sm:", "--radius-md:", "--radius-lg:"):
        assert r in text
