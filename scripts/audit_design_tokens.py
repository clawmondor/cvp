#!/usr/bin/env python3
"""Fail if any Jinja template uses a color/type utility not in DESIGN.md's tokens."""

from __future__ import annotations
import glob, re, sys, collections
import yaml

TEMPLATES = "src/claimos/templates/**/*.html"

# Minimal Tailwind v3 default palette for the families we use (hex -> lookup).
TW = {
    "indigo": {
        50: "#eef2ff",
        100: "#e0e7ff",
        200: "#c7d2fe",
        400: "#818cf8",
        500: "#6366f1",
        600: "#4f46e5",
        700: "#4338ca",
        800: "#3730a3",
        900: "#312e81",
    },
    "gray": {
        50: "#f9fafb",
        100: "#f3f4f6",
        200: "#e5e7eb",
        300: "#d1d5db",
        400: "#9ca3af",
        500: "#6b7280",
        600: "#4b5563",
        700: "#374151",
        800: "#1f2937",
        900: "#111827",
    },
    "green": {
        50: "#f0fdf4",
        100: "#dcfce7",
        200: "#bbf7d0",
        500: "#22c55e",
        600: "#16a34a",
        700: "#15803d",
        800: "#166534",
    },
    "red": {
        50: "#fef2f2",
        100: "#fee2e2",
        200: "#fecaca",
        400: "#f87171",
        500: "#ef4444",
        600: "#dc2626",
        700: "#b91c1c",
        800: "#991b1b",
    },
    "amber": {
        50: "#fffbeb",
        100: "#fef3c7",
        200: "#fde68a",
        300: "#fcd34d",
        500: "#f59e0b",
        600: "#d97706",
        700: "#b45309",
        800: "#92400e",
    },
    "slate": {
        300: "#cbd5e1",
        400: "#94a3b8",
        600: "#475569",
        700: "#334155",
        800: "#1e293b",
        900: "#0f172a",
    },
    "emerald": {50: "#ecfdf5", 300: "#6ee7b7", 500: "#10b981", 600: "#059669", 700: "#047857"},
    "yellow": {100: "#fef9c3", 800: "#854d0e"},
    "blue": {100: "#dbeafe", 600: "#2563eb", 800: "#1e40af"},
    "violet": {
        50: "#f5f3ff",
        100: "#ede9fe",
        200: "#ddd6fe",
        300: "#c4b5fd",
        400: "#a78bfa",
        500: "#8b5cf6",
        600: "#7c3aed",
        700: "#6d28d9",
        800: "#5b21b6",
    },
    "purple": {50: "#faf5ff"},
}
HEX2TW = {v.lower(): (fam, sh) for fam, d in TW.items() for sh, v in d.items()}

ALLOWED_TYPE = {
    "text-xs",
    "text-sm",
    "text-base",
    "text-lg",
    "text-xl",
    "text-2xl",
    "text-3xl",
    "text-4xl",
}


def allowed_colors() -> set[tuple[str, int]]:
    fm = open("DESIGN.md").read().split("---\n", 2)[1]
    data = yaml.safe_load(fm)
    out = set()
    for hexv in data["colors"].values():
        key = str(hexv).lower()
        if key in HEX2TW:
            out.add(HEX2TW[key])
    return out


def allowed_type() -> set[str]:
    fm = open("DESIGN.md").read().split("---\n", 2)[1]
    data = yaml.safe_load(fm)
    sizes = {
        int(str(v["fontSize"]).replace("px", ""))
        for v in data["typography"].values()
        if str(v.get("fontSize", "")).endswith("px")
    }
    px2tw = {
        12: "text-xs",
        14: "text-sm",
        16: "text-base",
        18: "text-lg",
        20: "text-xl",
        24: "text-2xl",
        30: "text-3xl",
        36: "text-4xl",
    }
    return {px2tw[s] for s in sizes if s in px2tw}


COLOR_RE = re.compile(
    r"(?:[a-z-]+:)*(?:bg|text|border|ring|divide|outline|from|to|via|fill|stroke|placeholder|decoration|accent)-(indigo|gray|slate|zinc|neutral|stone|red|rose|pink|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|violet|purple|fuchsia)-(\d{2,3})(?!\d)"
)
SIZE_RE = re.compile(r'(?:[a-z-]+:)*(text-(?:xs|sm|base|lg|xl|2xl|3xl|4xl|5xl|6xl))(?=[\s"\'])')


def main() -> int:
    color_ok, type_ok = allowed_colors(), allowed_type()
    bad_color = collections.Counter()
    bad_type = collections.Counter()
    files = collections.defaultdict(set)
    for fp in glob.glob(TEMPLATES, recursive=True):
        s = open(fp).read()
        short = fp.replace("src/claimos/templates/", "")
        for fam, sh in COLOR_RE.findall(s):
            if (fam, int(sh)) not in color_ok:
                k = f"{fam}-{sh}"
                bad_color[k] += 1
                files[k].add(short)
        for sz in SIZE_RE.findall(s):
            if sz not in type_ok:
                bad_type[sz] += 1
    if not bad_color and not bad_type:
        print("DESIGN.md token audit: clean ✓")
        return 0
    print("DESIGN.md token DRIFT detected:\n")
    for k, c in bad_color.most_common():
        print(f"  color  {c:4d}  {k:16s} {', '.join(sorted(files[k])[:4])}")
    for k, c in bad_type.most_common():
        print(f"  type   {c:4d}  {k}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
