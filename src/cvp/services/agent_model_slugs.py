"""Constants-only module: the OpenRouter model allowlist for recommendation agents.

Split out of `agent_models.py` so that `runtime_config.py` can import the
allowlist without creating a circular import (`agent_models` needs
`runtime_config` for `resolve_model`, and `runtime_config` needs the
allowlist for `_ALLOWED_STR`). This module must import nothing from `cvp`.
"""

ALLOWED_MODEL_SLUGS: tuple[str, ...] = (
    "anthropic/claude-haiku-4.5",
    "anthropic/claude-sonnet-4.6",
    "anthropic/claude-opus-4.6",
)

DEFAULT_MODEL_SLUG: str = "anthropic/claude-haiku-4.5"
