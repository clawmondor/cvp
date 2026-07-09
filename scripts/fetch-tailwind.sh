#!/usr/bin/env bash
set -euo pipefail
TAILWIND_VERSION="v4.3.2"   # confirm/bump to latest v4 stable; must be a v4.x tag
DEST="bin/tailwindcss"

os="$(uname -s)"; arch="$(uname -m)"
case "$os-$arch" in
  Darwin-arm64)  asset="tailwindcss-macos-arm64" ;;
  Darwin-x86_64) asset="tailwindcss-macos-x64" ;;
  Linux-x86_64)  asset="tailwindcss-linux-x64" ;;
  Linux-aarch64) asset="tailwindcss-linux-arm64" ;;
  *) echo "unsupported platform: $os-$arch" >&2; exit 1 ;;
esac

mkdir -p bin
url="https://github.com/tailwindlabs/tailwindcss/releases/download/${TAILWIND_VERSION}/${asset}"
echo "Fetching $url"
curl -fsSL "$url" -o "$DEST"
chmod +x "$DEST"
"$DEST" --help >/dev/null && echo "tailwindcss ${TAILWIND_VERSION} ready at $DEST"
