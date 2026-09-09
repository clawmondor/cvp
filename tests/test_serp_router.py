"""Integration tests for the SERP router's Firecrawl endpoint."""

import json
import re
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import cvp.dependencies as deps
from cvp.config import settings
from cvp.db import get_db
from cvp.dependencies import CurrentUser, require_active_user
from cvp.models import Base, Category, EvidenceFile, Item, ItemCrop, Matter, SerpSearch


@pytest.fixture(scope="module")
def db_engine(tmp_path_factory):
    base = tmp_path_factory.mktemp("serp_router")
    engine = create_engine(f"sqlite:///{base}/test.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    db.add(Category(id=1, name="Furniture", useful_life_years=10, acv_floor_pct=0.20))
    db.add(Matter(id="m1", policyholder_name="Test"))
    db.add(
        EvidenceFile(
            id="ef1",
            matter_id="m1",
            filename="p.jpg",
            stored_path="ef1/p.jpg",
            kind="image",
            scanned=True,
        )
    )
    db.add(
        Item(
            id="item1",
            matter_id="m1",
            category_id=1,
            line_number=1,
            description="oak dining chair",
            brand="Stickley",
        )
    )
    db.add(Item(id="item2", matter_id="m1", category_id=1, line_number=2, description="lamp"))
    db.add(
        ItemCrop(
            id="crop1",
            item_id="item1",
            evidence_file_id="ef1",
            bbox_left=0,
            bbox_upper=0,
            bbox_right=10,
            bbox_lower=10,
            crop_path="ef1/crop1.jpg",
        )
    )
    db.commit()
    db.close()
    return engine


@pytest.fixture(scope="module")
def client(db_engine):
    import cvp.routers.serp as serp_mod

    Session = sessionmaker(bind=db_engine)
    app = FastAPI()
    app.include_router(serp_mod.router)

    async def mock_user() -> CurrentUser:
        return CurrentUser(
            id="test-user",
            email="t@t.com",
            system_role="system_admin",
            group_id="g1",
            group_kind="internal",
        )

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[require_active_user] = mock_user
    app.dependency_overrides[get_db] = override_get_db

    with (
        patch.object(serp_mod, "SessionLocal", Session),
        patch.object(deps, "_check_matter_access", return_value=True),
    ):
        with TestClient(app) as c:
            yield c, Session


_PAYLOAD = {
    "success": True,
    "creditsUsed": 5,
    "data": {
        "web": [
            {
                "url": "https://shop.example/p/1",
                "title": "Result",
                "json": {
                    "product_title": "Stickley Oak Dining Chair",
                    "price": 129.99,
                    "currency": "USD",
                    "retailer": "Shop Example",
                    "is_product_page": True,
                },
            }
        ]
    },
}


def test_firecrawl_search_renders_results_and_persists(client):
    c, Session = client
    with patch(
        "cvp.routers.serp.call_firecrawl",
        return_value=("https://api.firecrawl.dev/v2/search", {"query": "q"}, _PAYLOAD, 200),
    ):
        resp = c.post(
            "/api/items/item1/crops/crop1/serp/firecrawl",
            data={"query": "Stickley oak chair"},
        )

    assert resp.status_code == 200
    assert "Stickley Oak Dining Chair" in resp.text
    assert "129.99" in resp.text

    db = Session()
    row = (
        db.query(SerpSearch)
        .filter_by(service="firecrawl")
        .order_by(SerpSearch.ran_at.desc())
        .first()
    )
    assert row.item_crop_id == "crop1"
    assert row.status_code == 200
    db.close()


def test_firecrawl_search_rejects_crop_from_another_item(client):
    c, _ = client
    with patch("cvp.routers.serp.call_firecrawl", return_value=("u", {}, _PAYLOAD, 200)):
        resp = c.post("/api/items/item2/crops/crop1/serp/firecrawl", data={"query": "lamp"})
    assert resp.status_code == 403


def test_firecrawl_search_404s_on_unknown_crop(client):
    c, _ = client
    with patch("cvp.routers.serp.call_firecrawl", return_value=("u", {}, _PAYLOAD, 200)):
        resp = c.post("/api/items/item1/crops/nope/serp/firecrawl", data={"query": "x"})
    assert resp.status_code == 404


def test_firecrawl_search_defaults_query_from_item_fields(client):
    c, _ = client
    with patch(
        "cvp.routers.serp.call_firecrawl",
        return_value=("u", {}, _PAYLOAD, 200),
    ) as spy:
        c.post("/api/items/item1/crops/crop1/serp/firecrawl", data={"query": ""})
    spy.assert_called_once_with("Stickley oak dining chair")


def test_firecrawl_search_surfaces_error_without_500(client):
    c, _ = client
    with patch(
        "cvp.routers.serp.call_firecrawl",
        return_value=("u", {}, {"error": "Firecrawl is not configured."}, 0),
    ):
        resp = c.post("/api/items/item1/crops/crop1/serp/firecrawl", data={"query": "x"})
    assert resp.status_code == 200
    # Surfaced in the panel body, not only buried inside the raw-response details.
    assert re.search(r"data-serp-error[^>]*>\s*Firecrawl is not configured\s*<", resp.text)
    assert "No results found." not in resp.text


def test_serp_apply_honors_submitted_match_type(client):
    c, Session = client
    resp = c.post(
        "/api/items/item1/serp-apply",
        data={
            "source_url": "https://shop.example/p/1",
            "source_retailer": "Shop Example",
            "rcv_unit_cents": "12999",
            "match_type": "nearest_comparable",
        },
    )
    assert resp.status_code == 200

    db = Session()
    item = db.get(Item, "item1")
    assert item.match_type == "nearest_comparable"
    assert item.source_url == "https://shop.example/p/1"
    assert item.source_captured_at is not None
    db.close()


def test_serp_apply_rejects_invalid_match_type(client):
    c, _ = client
    resp = c.post(
        "/api/items/item1/serp-apply",
        data={
            "source_url": "https://shop.example/p/2",
            "source_retailer": "Shop Example",
            "rcv_unit_cents": "100",
            "match_type": "brand",
        },
    )
    assert resp.status_code == 422


def test_panel_keeps_lens_available_after_a_web_search(client):
    """A firecrawl row must not disable the Lens button or hijack the Lens pane."""
    c, Session = client
    db = Session()
    db.add(
        SerpSearch(
            id="ss-panel-fc",
            item_crop_id="crop1",
            service="firecrawl",
            request_url="https://api.firecrawl.dev/v2/search",
            request_params="{}",
            response_json=json.dumps(_PAYLOAD),
            status_code=200,
        )
    )
    db.commit()
    db.close()

    resp = c.get("/api/items/item1/serp-panel")
    assert resp.status_code == 200
    html = resp.text

    # (a) every tab target has a matching pane id
    targets = re.findall(r'data-serp-tab-target="([^"]+)"', html)
    assert targets
    for target in targets:
        assert f'id="serp-pane-{target}"' in html

    # (b) the Lens button is not disabled — Lens was never run for this crop
    lens_buttons = re.findall(r"<button[^>]*data-lens-btn[^>]*>", html)
    assert lens_buttons
    for button in lens_buttons:
        assert "disabled" not in button

    # (c) the firecrawl results render in the web pane, not under the Lens heading
    assert "Stickley Oak Dining Chair" in html
    assert html.index('id="lens-result-crop1"') < html.index("No search run yet.")
    assert html.index("No search run yet.") < html.index('id="firecrawl-result-crop1"')
    assert html.index('id="firecrawl-result-crop1"') < html.index("Stickley Oak Dining Chair")


def test_firecrawl_empty_results_suggest_editing_the_query(client):
    c, _ = client
    with patch(
        "cvp.routers.serp.call_firecrawl",
        return_value=("u", {}, {"success": True, "data": {"web": []}}, 200),
    ):
        resp = c.post("/api/items/item1/crops/crop1/serp/firecrawl", data={"query": "x"})
    assert resp.status_code == 200
    assert "No priced product pages found — try editing the query" in resp.text
    assert "No results found." not in resp.text


def test_panel_disables_web_search_when_firecrawl_is_unconfigured(client):
    c, _ = client
    with patch.object(settings, "firecrawl_api_key", ""):
        resp = c.get("/api/items/item1/serp-panel")
    assert resp.status_code == 200
    assert "Firecrawl is not configured" in resp.text
    web_form = resp.text.split('id="serp-pane-web-crop1"')[1]
    assert "disabled" in web_form.split("Search web")[0]


def test_panel_enables_web_search_when_firecrawl_is_configured(client):
    c, _ = client
    with patch.object(settings, "firecrawl_api_key", "fc-test-key"):
        resp = c.get("/api/items/item1/serp-panel")
    assert resp.status_code == 200
    assert "Firecrawl is not configured" not in resp.text


def test_panel_reuses_the_items_brand_for_match_type(client):
    """The stored-row path must pass brand, or a reload downgrades exact -> nearest."""
    c, Session = client
    db = Session()
    db.add(
        SerpSearch(
            id="ss-panel-brand",
            item_crop_id="crop1",
            service="firecrawl",
            request_url="u",
            request_params="{}",
            response_json=json.dumps(_PAYLOAD),
            status_code=200,
        )
    )
    db.commit()
    db.close()

    resp = c.get("/api/items/item1/serp-panel")
    assert resp.status_code == 200
    assert 'name="match_type" value="exact"' in resp.text
