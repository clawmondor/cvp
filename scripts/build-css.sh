#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIN="$ROOT/bin/tailwindcss"
if [[ ! -x "$BIN" ]]; then
  echo "tailwindcss binary missing; run scripts/fetch-tailwind.sh" >&2
  exit 1
fi
exec "$BIN" \
  -i "$ROOT/src/claimos/styles/theme.css" \
  -o "$ROOT/src/claimos/static/app.css" \
  "$@"
