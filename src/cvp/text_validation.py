"""Reusable plain-text validator for free-form user input.

Rejects HTML markup, entity-encoded payloads, dangerous URL schemes embedded
in text, and most control characters. Intended for any free-form text field
where the storage and rendering layers treat the value as plain text (no
markdown, no link auto-detection, no `| safe`).
"""

import re

from fastapi import HTTPException

_HTML_ENTITY_RE = re.compile(r"&#?\w+;")
_FORBIDDEN_SUBSTRINGS = ("javascript:", "data:")

# C0 control characters are 0x00..0x1F. We allow \t (0x09), \n (0x0A), \r (0x0D).
_ALLOWED_CONTROL = {"\t", "\n", "\r"}


def _has_disallowed_control(value: str) -> bool:
    for ch in value:
        code = ord(ch)
        if code < 0x20 and ch not in _ALLOWED_CONTROL:
            return True
        if code == 0x7F:  # DEL
            return True
    return False


def assert_plain_text(value: str, *, field_name: str = "input") -> None:
    """Raise HTTPException(400) if `value` contains HTML, entities, dangerous schemes, or controls."""
    if "<" in value or ">" in value:
        _reject(field_name)
    if _HTML_ENTITY_RE.search(value):
        _reject(field_name)
    lowered = value.lower()
    for needle in _FORBIDDEN_SUBSTRINGS:
        if needle in lowered:
            _reject(field_name)
    if _has_disallowed_control(value):
        _reject(field_name)


def _reject(field_name: str) -> None:
    raise HTTPException(
        status_code=400,
        detail=f"{field_name} may not contain HTML or special markup. Please use plain text.",
    )
