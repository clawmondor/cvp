import re
from pathlib import Path

THEME = Path("src/claimos/styles/theme.css")

EXPECTED = {
    "primary-subtle": "#eef2ff",
    "primary-tint": "#e0e7ff",
    "primary-tint-strong": "#c7d2fe",
    "primary-light": "#6366f1",
    "primary": "#4f46e5",
    "primary-strong": "#4338ca",
    "neutral-50": "#f9fafb",
    "neutral-100": "#f3f4f6",
    "neutral-200": "#e5e7eb",
    "neutral-300": "#d1d5db",
    "neutral-400": "#9ca3af",
    "neutral-500": "#6b7280",
    "neutral-600": "#4b5563",
    "neutral-700": "#374151",
    "neutral-900": "#111827",
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
    "admin-300": "#cbd5e1",
    "admin-400": "#94a3b8",
    "admin-600": "#475569",
    "admin-700": "#334155",
    "admin-800": "#1e293b",
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
