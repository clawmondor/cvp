#!/usr/bin/env python3
"""Fail if templates or static JS use a raw Tailwind color family instead of a design token.

Slice 2 closed the Tailwind palette to a fixed token set (primary*/neutral-*/success*/
error*/warning*/admin-*/surface/white/black). Any raw family utility (bg-indigo-600,
text-gray-500, bg-emerald-600, …) is drift. `neutral` is intentionally NOT forbidden —
it is our repurposed ramp name, the only neutral in the closed palette.
"""

from __future__ import annotations

import glob
import re
import sys

SCAN_GLOBS = ["src/claimos/templates/**/*.html", "src/claimos/static/*.js"]

# raw Tailwind color families we migrated away from (excludes `neutral`, now our token)
_FAMILIES = (
    "gray|slate|zinc|stone|red|orange|amber|yellow|lime|green|emerald|teal|"
    "cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose"
)
_PROPS = (
    "bg|text|border|ring|divide|from|to|via|outline|placeholder|fill|stroke|decoration|"
    "accent|shadow"
)
RAW_RE = re.compile(rf"(?:[a-z-]+:)*(?:{_PROPS})-(?:{_FAMILIES})-\d{{2,3}}(?![\w-])")


def find_raw_family_hits(text: str) -> list[str]:
    return RAW_RE.findall(text)


def main() -> int:
    hits: dict[str, int] = {}
    for pattern in SCAN_GLOBS:
        for fp in glob.glob(pattern, recursive=True):
            found = find_raw_family_hits(open(fp).read())
            if found:
                hits[fp] = len(found)
    if not hits:
        print("design token guard: clean ✓ (no raw Tailwind color families)")
        return 0
    print("design token DRIFT — raw Tailwind color families found:")
    for fp, n in sorted(hits.items()):
        print(f"  {n:4d}  {fp}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
