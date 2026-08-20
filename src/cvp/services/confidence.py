"""Extract vision confidence from the legacy notes string.

Vision historically encoded confidence into Item.notes as
`...|confidence:high`. This helper reads that value back out and is used by
the Alembic backfill migration; it's also available to any other code that
needs to read confidence out of a legacy notes blob.
"""

import re

_VALID = ("high", "medium", "low")
_PATTERN = re.compile(r"confidence:(\w+)")


def parse_confidence_from_notes(notes: str | None) -> str | None:
    if not notes:
        return None
    m = _PATTERN.search(notes)
    if not m:
        return None
    value = m.group(1).lower()
    return value if value in _VALID else None
