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

import logging

from sqlalchemy.orm import Session

from cvp.services import runtime_config
from cvp.services.agent_model_slugs import ALLOWED_MODEL_SLUGS, DEFAULT_MODEL_SLUG

logger = logging.getLogger(__name__)

__all__ = [
    "ALLOWED_MODEL_SLUGS",
    "DEFAULT_MODEL_SLUG",
    "is_allowed",
    "resolve_model",
]


def is_allowed(slug: str) -> bool:
    return slug in ALLOWED_MODEL_SLUGS


def resolve_model(db: Session, requested: str | None) -> str:
    """Return the model slug to run, validating it against the allowlist.

    Raises ValueError if a caller-supplied override is not allowed. A
    *configured* default that is not allowed is not the caller's fault, so it
    falls back to `DEFAULT_MODEL_SLUG` with a warning rather than failing the
    launch — but it never reaches the Worker. `runtime_config` only applies the
    allowlist to a DB row; with no row it hands back the env default unchecked,
    so `AI_RECOMMENDATION_MODEL=<anything>` in the environment would otherwise
    walk straight past the guard that exists to bound spend, and the Worker
    validates nothing by design.
    """
    if requested:
        if not is_allowed(requested):
            raise ValueError(f"model {requested!r} is not allowed")
        return requested

    configured = runtime_config.get_str(db, "ai_recommendation_model")
    if not is_allowed(configured):
        logger.warning(
            "configured ai_recommendation_model %r is not on the allowlist; using %s",
            configured,
            DEFAULT_MODEL_SLUG,
        )
        return DEFAULT_MODEL_SLUG
    return configured
