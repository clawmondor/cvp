"""The container runner, imported off sys.path the way the image lays it out.

The image drops runner.py, search.py, and agent_client.py side by side in
/app, so there is no package to import. Tests therefore have to extend
sys.path — but scoped to the test, via a fixture: mutating it at import time
leaked three very generic names (`runner`, `search`, `agent_client`) as
globally importable for the rest of the session.
"""

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "cloudflare" / "images" / "shared"
AGENT_CLIENT_DIR = ROOT / "skills" / "airecommendations" / "scripts"
CONTAINER_MODULES = ("runner", "search", "agent_client")


@pytest.fixture
def runner(monkeypatch):
    """Import runner (and, transitively, search and agent_client) for one test."""
    monkeypatch.syspath_prepend(str(AGENT_CLIENT_DIR))
    monkeypatch.syspath_prepend(str(SHARED))
    for name in CONTAINER_MODULES:
        sys.modules.pop(name, None)
    module = importlib.import_module("runner")
    yield module
    for name in CONTAINER_MODULES:
        sys.modules.pop(name, None)


@pytest.fixture
def cfg(runner, monkeypatch):
    for k, v in {
        "RUN_ID": "run-1",
        "MATTER_ID": "m-1",
        "ITEM_ID": "item-1",
        "MODEL_SLUG": "anthropic/claude-haiku-4.5",
        "CVP_BASE_URL": "https://cvp.example",
        "CVP_AGENT_KEY": "agk_live_x_y",
        "OPENROUTER_API_KEY": "or-key",
        "BROWSER_RUN_ACCOUNT_ID": "acct",
        "BROWSER_RUN_TOKEN": "tok",
        "AGENT_IMPL": "custom-python",
        "IMAGE_TAG": "a1b2c3d",
    }.items():
        monkeypatch.setenv(k, v)
    return runner.Config.from_env()


def test_config_reads_env(runner, cfg):
    assert cfg.run_id == "run-1"
    assert cfg.image_tag == "a1b2c3d"
    assert cfg.agent_impl == "custom-python"


def test_successful_run_submits_and_reports(runner, cfg, monkeypatch):
    progress: list[dict] = []
    submitted: list[dict] = []

    monkeypatch.setattr(runner, "_post_progress_raw", lambda c, b: progress.append(b))
    monkeypatch.setattr(
        runner, "_fetch_item", lambda c: {"description": "chair", "brand": "S", "model": None}
    )
    monkeypatch.setattr(runner, "_submit_recommendation", lambda c, b: submitted.append(b))
    monkeypatch.setattr(
        runner.search,
        "search_for_item",
        lambda **kw: (
            runner.search.SearchResult(
                "Chair", 129.99, "Shop", "https://s.example/c", "exact", "why"
            ),
            9835,
            False,
        ),
    )

    assert runner.run(cfg) == 0

    assert submitted == [
        {
            "proposed_retail_unit_cents": 12999,
            "proposed_shipping_cents": 0,
            "source_url": "https://s.example/c",
            "source_retailer": "Shop",
            "match_type": "exact",
            "product_title": "Chair",
            "rationale": "why",
        }
    ]
    assert progress[-1]["status"] == "succeeded"
    assert progress[-1]["cost_micro_usd"] == 9835
    assert progress[-1]["image_tag"] == "a1b2c3d"
    assert progress[-1]["browser_run_used"] is False
    assert [p["status"] for p in progress[:-1]] == ["running", "searching", "submitting"]


def test_no_match_reports_failed_and_submits_nothing(runner, cfg, monkeypatch):
    progress: list[dict] = []
    submitted: list[dict] = []
    monkeypatch.setattr(runner, "_post_progress_raw", lambda c, b: progress.append(b))
    monkeypatch.setattr(
        runner, "_fetch_item", lambda c: {"description": "chair", "brand": None, "model": None}
    )
    monkeypatch.setattr(runner, "_submit_recommendation", lambda c, b: submitted.append(b))
    monkeypatch.setattr(runner.search, "search_for_item", lambda **kw: (None, 1000, False))

    assert runner.run(cfg) == 1
    assert submitted == []
    assert progress[-1]["status"] == "failed"
    assert "no match" in progress[-1]["error"].lower()


def test_exception_still_reports_terminal_status(runner, cfg, monkeypatch):
    """The container must always post a terminal status, in a finally."""
    progress: list[dict] = []
    monkeypatch.setattr(runner, "_post_progress_raw", lambda c, b: progress.append(b))
    monkeypatch.setattr(
        runner, "_fetch_item", lambda c: {"description": "chair", "brand": None, "model": None}
    )

    def _boom(**kw):
        raise RuntimeError("openrouter exploded")

    monkeypatch.setattr(runner.search, "search_for_item", _boom)

    assert runner.run(cfg) == 1
    assert progress[-1]["status"] == "failed"
    assert "openrouter exploded" in progress[-1]["error"]
    # Cost is unknown, not zero — reporting 0 would read as a free run and
    # silently understate the A/B cost comparison.
    assert "cost_micro_usd" not in progress[-1]


def test_unsourced_result_is_never_submitted(runner, cfg, monkeypatch):
    """Defence in depth: the runner validates even if search returns junk."""
    progress: list[dict] = []
    submitted: list[dict] = []
    monkeypatch.setattr(runner, "_post_progress_raw", lambda c, b: progress.append(b))
    monkeypatch.setattr(
        runner, "_fetch_item", lambda c: {"description": "chair", "brand": None, "model": None}
    )
    monkeypatch.setattr(runner, "_submit_recommendation", lambda c, b: submitted.append(b))
    monkeypatch.setattr(
        runner.search,
        "search_for_item",
        lambda **kw: (runner.search.SearchResult("C", 10.0, "", "", "exact", ""), 500, False),
    )

    assert runner.run(cfg) == 1
    assert submitted == []
    assert progress[-1]["status"] == "failed"


def test_submit_passes_the_run_id_for_ab_attribution(runner, cfg, monkeypatch):
    """The reference client must carry agent_run_id through, or the recommendation
    lands with a NULL FK and the A/B join in the design spec (5.3) sees nothing."""
    captured: dict = {}

    class _Client:
        def __init__(self, base_url, api_key=None):
            captured["base_url"] = base_url
            captured["api_key"] = api_key

        def submit_recommendation(self, item_id, **kwargs):
            captured["item_id"] = item_id
            captured.update(kwargs)
            return {"id": "rec-1", "status": "pending", "item_id": item_id}

    monkeypatch.setattr(runner, "AiRecommendationsClient", _Client)

    runner._submit_recommendation(
        cfg,
        {
            "proposed_retail_unit_cents": 12999,
            "proposed_shipping_cents": 0,
            "source_url": "https://s.example/c",
            "source_retailer": "Shop",
            "match_type": "exact",
            "product_title": "Chair",
            "rationale": "why",
        },
    )

    assert captured["agent_run_id"] == "run-1"
    assert captured["item_id"] == "item-1"
