"""Container entrypoint: run one pricing agent for one item, then exit.

The agent proposes and this runner disposes. The model returns a structured
match; this module validates it against the skill's invariants and performs the
submission itself. That keeps the audit-trail rules in code rather than in
prose the model may ignore, and means CVP_AGENT_KEY never has to be reachable
from a model-driven tool surface.

Submission goes through the project's existing reference client
(``agent_client.AiRecommendationsClient``), not a hand-rolled HTTP call. The
Dockerfile places ``agent_client.py`` next to this file in /app so it is used
from source rather than duplicated.

Invariant: a terminal status is always posted, even on crash.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from dataclasses import dataclass

import httpx
import search
from agent_client import AiRecommendationsClient

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("runner")

_TIMEOUT_SECONDS = 30.0


@dataclass
class Config:
    run_id: str
    matter_id: str
    item_id: str
    model_slug: str
    cvp_base_url: str
    cvp_agent_key: str
    openrouter_api_key: str
    browser_account_id: str
    browser_token: str
    agent_impl: str
    image_tag: str

    @classmethod
    def from_env(cls) -> "Config":
        def need(name: str) -> str:
            value = os.environ.get(name, "")
            if not value:
                raise SystemExit(f"missing required env var {name}")
            return value

        return cls(
            run_id=need("RUN_ID"),
            matter_id=os.environ.get("MATTER_ID", ""),
            item_id=need("ITEM_ID"),
            model_slug=need("MODEL_SLUG"),
            cvp_base_url=need("CVP_BASE_URL").rstrip("/"),
            cvp_agent_key=need("CVP_AGENT_KEY"),
            openrouter_api_key=need("OPENROUTER_API_KEY"),
            browser_account_id=os.environ.get("BROWSER_RUN_ACCOUNT_ID", ""),
            browser_token=os.environ.get("BROWSER_RUN_TOKEN", ""),
            # Baked into the image, not injected, so telemetry describes what
            # actually ran rather than what the Worker believed it launched.
            agent_impl=os.environ.get("AGENT_IMPL", "custom-python"),
            image_tag=os.environ.get("IMAGE_TAG", "unknown"),
        )


def _headers(cfg: Config) -> dict[str, str]:
    return {"X-API-Key": cfg.cvp_agent_key, "Content-Type": "application/json"}


def _post_progress_raw(cfg: Config, body: dict) -> None:
    with httpx.Client(timeout=_TIMEOUT_SECONDS) as client:
        client.post(
            f"{cfg.cvp_base_url}/api/agent/runs/{cfg.run_id}/progress",
            headers=_headers(cfg),
            json=body,
        )


def post_progress(cfg: Config, status: str, **fields) -> None:
    """Best-effort progress report. Never raises — losing a progress ping must
    not kill a run that is otherwise fine; the CVP sweeper is the backstop."""
    body = {"status": status, **fields}
    try:
        _post_progress_raw(cfg, body)
    except Exception:  # noqa: BLE001
        logger.warning("progress post failed for status=%s", status, exc_info=True)


def _fetch_item(cfg: Config) -> dict:
    with httpx.Client(timeout=_TIMEOUT_SECONDS) as client:
        response = client.get(
            f"{cfg.cvp_base_url}/api/agent/items/{cfg.item_id}", headers=_headers(cfg)
        )
    response.raise_for_status()
    return response.json()


def _submit_recommendation(cfg: Config, body: dict) -> None:
    """Submit via the project's reference client (ruling R2) — never a raw
    HTTP POST. Keeps this runner in lockstep with the one client every other
    agent surface uses, instead of re-deriving request shape by hand."""
    client = AiRecommendationsClient(cfg.cvp_base_url, api_key=cfg.cvp_agent_key)
    client.submit_recommendation(
        cfg.item_id,
        retail_unit_cents=body["proposed_retail_unit_cents"],
        shipping_cents=body["proposed_shipping_cents"],
        source_url=body["source_url"],
        source_retailer=body["source_retailer"],
        match_type=body["match_type"],
        product_title=body["product_title"],
        rationale=body["rationale"],
        # Attribution for the A/B join in spec 5.3 — without it
        # ai_recommendations.agent_run_id is never written and the accept-rate
        # and exact-rate metrics are unrecoverable after the fact.
        agent_run_id=cfg.run_id,
    )


def run(cfg: Config) -> int:
    """Execute one run. Returns a process exit code."""
    started = time.monotonic()
    cost_micro = 0
    used_browser = False
    error: str | None = None

    try:
        post_progress(cfg, "running", message="Starting…")
        item = _fetch_item(cfg)

        post_progress(cfg, "searching", message="Looking for retail matches…")
        result, cost_micro, used_browser = search.search_for_item(
            description=item.get("description") or "",
            brand=item.get("brand"),
            model=item.get("model"),
            model_slug=cfg.model_slug,
            openrouter_key=cfg.openrouter_api_key,
            browser_account_id=cfg.browser_account_id,
            browser_token=cfg.browser_token,
        )

        if result is None:
            error = "No match found for this item."
        elif not result.source_url.strip() or not result.retailer.strip():
            # Every RCV must have a source; refuse to submit an unsourced price.
            error = "Match was missing a source URL or retailer."
        else:
            post_progress(cfg, "submitting", message="Submitting recommendation…")
            _submit_recommendation(
                cfg,
                {
                    "proposed_retail_unit_cents": search.dollars_to_cents(result.price_usd),
                    "proposed_shipping_cents": 0,
                    "source_url": result.source_url,
                    "source_retailer": result.retailer,
                    "match_type": result.match_type,
                    "product_title": result.product_title,
                    "rationale": result.rationale,
                },
            )
    except Exception as exc:  # noqa: BLE001
        logger.exception("run failed")
        error = str(exc)

    latency_ms = int((time.monotonic() - started) * 1000)
    telemetry = {
        "agent_impl": cfg.agent_impl,
        "image_tag": cfg.image_tag,
        "model_slug": cfg.model_slug,
        "cost_micro_usd": cost_micro,
        "latency_ms": latency_ms,
        "browser_run_used": used_browser,
    }

    if error is None:
        post_progress(cfg, "succeeded", **telemetry)
        return 0
    post_progress(cfg, "failed", error=error, **telemetry)
    return 1


if __name__ == "__main__":
    sys.exit(run(Config.from_env()))
