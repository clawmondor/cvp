import sys
from pathlib import Path

import pytest

SHARED = Path(__file__).resolve().parents[1] / "cloudflare" / "images" / "shared"
AGENT_CLIENT_DIR = Path(__file__).resolve().parents[1] / "skills" / "airecommendations" / "scripts"
sys.path.insert(0, str(SHARED))
sys.path.insert(0, str(AGENT_CLIENT_DIR))

import runner  # noqa: E402
import search  # noqa: E402


@pytest.fixture
def cfg(monkeypatch):
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


def test_config_reads_env(cfg):
    assert cfg.run_id == "run-1"
    assert cfg.image_tag == "a1b2c3d"
    assert cfg.agent_impl == "custom-python"


def test_successful_run_submits_and_reports(cfg, monkeypatch):
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
            search.SearchResult("Chair", 129.99, "Shop", "https://s.example/c", "exact", "why"),
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


def test_no_match_reports_failed_and_submits_nothing(cfg, monkeypatch):
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


def test_exception_still_reports_terminal_status(cfg, monkeypatch):
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


def test_unsourced_result_is_never_submitted(cfg, monkeypatch):
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
        lambda **kw: (search.SearchResult("C", 10.0, "", "", "exact", ""), 500, False),
    )

    assert runner.run(cfg) == 1
    assert submitted == []
    assert progress[-1]["status"] == "failed"
