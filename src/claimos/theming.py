"""Server-side light/dark theme selection from the `theme` cookie."""

from __future__ import annotations

from starlette.requests import Request

_VALID = {"dark", "light"}


def theme_class_for(request: Request) -> str:
    """Return the <html> class for the request's theme cookie.

    "dark"/"light" force that mode; anything else (incl. absent) yields "" so the
    CSS `color-scheme: light dark` follows the OS.
    """
    choice = request.cookies.get("theme", "")
    return choice if choice in _VALID else ""
