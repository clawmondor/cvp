"""`uv run css` — build the Tailwind stylesheet via the standalone binary."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_BASE = Path(__file__).resolve().parent  # src/claimos
_ROOT = _BASE.parent.parent  # repo root
BIN = _ROOT / "bin" / "tailwindcss"
INPUT = _BASE / "styles" / "theme.css"
OUTPUT = _BASE / "static" / "app.css"


def build_command(watch: bool, minify: bool) -> list[str]:
    cmd = [str(BIN), "-i", str(INPUT), "-o", str(OUTPUT)]
    if watch:
        cmd.append("--watch")
    if minify:
        cmd.append("--minify")
    return cmd


def main() -> None:
    args = sys.argv[1:]
    if not BIN.exists():
        print(
            f"tailwindcss binary not found at {BIN}; run scripts/fetch-tailwind.sh",
            file=sys.stderr,
        )
        raise SystemExit(1)
    raise SystemExit(subprocess.call(build_command("--watch" in args, "--minify" in args)))
