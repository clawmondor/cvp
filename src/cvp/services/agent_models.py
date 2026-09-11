"""Which OpenRouter models the recommendation agents may use.

Code-defined, not admin-editable, following the same reasoning as
`vision_models.py`: choosing which models are allowed to spend money is an
engineering decision. Validation happens here, in CVP, and never in the
Cloudflare Worker — the Worker holds the OpenRouter key, and an unvalidated
slug is a direct path to spending against a capped key on any of the
catalog's several hundred models.

Every slug below was verified against the live OpenRouter catalog as
supporting both tool use and the web-search plugin.

The allowlist and default slug live in `agent_model_slugs.py` (a
constants-only module with no `cvp` imports) and are re-exported here to
avoid a circular import with `runtime_config`, which also needs the
allowlist.
"""

from sqlalchemy.orm import Session

from cvp.services import runtime_config
from cvp.services.agent_model_slugs import ALLOWED_MODEL_SLUGS, DEFAULT_MODEL_SLUG

__all__ = [
    "ALLOWED_MODEL_SLUGS",
    "DEFAULT_MODEL_SLUG",
    "is_allowed",
    "resolve_model",
]


def is_allowed(slug: str) -> bool:
    return slug in ALLOWED_MODEL_SLUGS


def resolve_model(db: Session, requested: str | None) -> str:
    """Return the model slug to run, validating any caller-supplied override.

    Raises ValueError if the override is not on the allowlist.
    """
    if requested:
        if not is_allowed(requested):
            raise ValueError(f"model {requested!r} is not allowed")
        return requested
    return runtime_config.get_str(db, "ai_recommendation_model")
