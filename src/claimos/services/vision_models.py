"""Constants and helpers for the vision-model catalog.

These are intentionally code-defined (not DB-stored) — adding a recommended
slug or a new auto-adapter is an engineering decision, not an admin one.
"""

from __future__ import annotations

RECOMMENDED_SLUGS: set[str] = {
    "anthropic/claude-opus-4",
    "anthropic/claude-sonnet-4",
    "google/gemini-2.5-pro",
}

# Order claims: first matching prefix wins.
ADAPTER_SUGGESTIONS: list[tuple[str, str]] = [
    ("anthropic/", "pixel_passthrough"),
    ("google/gemini-", "gemini_normalized_1000"),
]


def suggest_adapter(slug: str) -> str:
    for prefix, adapter in ADAPTER_SUGGESTIONS:
        if slug.startswith(prefix):
            return adapter
    return "none"


def is_recommended(slug: str) -> bool:
    return slug in RECOMMENDED_SLUGS
