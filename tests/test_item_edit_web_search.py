"""The Web search (Firecrawl) section renders in the inline item edit row.

These tests drive the real `GET /api/items/{id}/edit` endpoint rather than
asserting against template source. An earlier attempt at this feature put the
markup in `_serp_panel.html`, a template no route reaches from the UI, and a
source-level assertion happily passed while the button was invisible. Rendering
through the endpoint is what makes these tests mean anything.
"""

import inspect
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cvp.models_vision  # noqa: F401
from cvp.db import get_db
from cvp.dependencies import CurrentUser
from cvp.main import app
from cvp.models import Base, Category, EvidenceFile, Item, ItemCrop, Matter
from cvp.models_auth import User
from cvp.services import access_cache

MATTER_ID = "m-fcs"
USER_ID = "u-fcs"


@pytest.fixture(autouse=True)
def _clear_access_cache():
    access_cache._cache.clear()
    yield
    access_cache._cache.clear()


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    s.add(Matter(id=MATTER_ID, policyholder_name="P", loss_type="total_loss"))
    s.add(Category(id=1, name="Furniture", useful_life_years=10, acv_floor_pct=0.2))
    s.add(User(id=USER_ID, email="u@t.com", display_name="U", system_role="internal_user"))
    s.add(
        EvidenceFile(
            id="ef-fcs",
            matter_id=MATTER_ID,
            filename="p.jpg",
            stored_path="ef-fcs/p.jpg",
            kind="image",
            scanned=True,
        )
    )
    s.commit()
    yield s
    s.close()


@pytest.fixture
def client(db_session, monkeypatch):
    import cvp.routers.items as items_router

    async def mock_user():
        return CurrentUser(
            id=USER_ID,
            email="u@t.com",
            system_role="internal_user",
            group_id=None,
            group_kind="internal",
        )

    def override_get_db():
        yield db_session

    dep = inspect.signature(items_router.item_edit_form).parameters["user"].default.dependency
    app.dependency_overrides[dep] = mock_user
    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr("cvp.routers.items.SessionLocal", lambda: db_session)
    monkeypatch.setattr("cvp.config.settings.firecrawl_api_key", "fc-test")
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _item_with_crop(db, *, brand="Stickley", description="oak dining chair"):
    it = Item(
        matter_id=MATTER_ID,
        category_id=1,
        description=description,
        brand=brand,
        confirmed=True,
    )
    db.add(it)
    db.commit()
    db.refresh(it)
    db.add(
        ItemCrop(
            id=f"crop-{it.id}",
            item_id=it.id,
            evidence_file_id="ef-fcs",
            bbox_left=0,
            bbox_upper=0,
            bbox_right=10,
            bbox_lower=10,
            crop_path="ef-fcs/crop.jpg",
        )
    )
    db.commit()
    return it


def test_edit_row_renders_the_web_search_section(client, db_session):
    it = _item_with_crop(db_session)
    resp = client.get(f"/api/items/{it.id}/edit")
    assert resp.status_code == 200
    assert "Web search" in resp.text
    assert "Search web" in resp.text


def test_web_search_form_posts_to_the_firecrawl_endpoint(client, db_session):
    it = _item_with_crop(db_session)
    resp = client.get(f"/api/items/{it.id}/edit")
    assert f'hx-post="/api/items/{it.id}/crops/crop-{it.id}/serp/firecrawl"' in resp.text


def test_query_input_is_prefilled_from_the_items_fields(client, db_session):
    it = _item_with_crop(db_session)
    resp = client.get(f"/api/items/{it.id}/edit")
    assert 'name="query" value="Stickley oak dining chair"' in resp.text


def test_query_input_is_editable(client, db_session):
    """The whole point is refining a bad auto-query and re-running."""
    it = _item_with_crop(db_session)
    resp = client.get(f"/api/items/{it.id}/edit")
    form = resp.text.split('name="query"')[1].split(">")[0]
    assert "readonly" not in form
    assert "disabled" not in form


def test_search_button_is_never_disabled(client, db_session):
    """Unlike the Lens button, which locks after one run."""
    it = _item_with_crop(db_session)
    resp = client.get(f"/api/items/{it.id}/edit")
    button = resp.text.split("Search web")[0].rsplit("<button", 1)[1]
    assert "disabled" not in button


def test_unconfigured_key_shows_a_message_instead_of_the_form(client, db_session, monkeypatch):
    monkeypatch.setattr("cvp.config.settings.firecrawl_api_key", "")
    it = _item_with_crop(db_session)
    resp = client.get(f"/api/items/{it.id}/edit")
    assert "Firecrawl is not configured." in resp.text
    assert "/serp/firecrawl" not in resp.text


def test_web_search_section_has_no_inline_event_handlers(client, db_session):
    """CSP script-src has no unsafe-inline; handlers must be delegated via app.js."""
    it = _item_with_crop(db_session)
    section = client.get(f"/api/items/{it.id}/edit").text.split("Web search")[1]
    for attr in ("onclick=", "onchange=", "onsubmit="):
        assert attr not in section, f"inline handler {attr} is CSP-blocked"


def test_lens_section_still_renders_alongside_it(client, db_session):
    """The new section must not displace the existing Google Lens UI."""
    it = _item_with_crop(db_session)
    resp = client.get(f"/api/items/{it.id}/edit")
    assert "Google Lens" in resp.text
    assert "/serp/google_lens" in resp.text


# ── Regression coverage ported from the deleted serp-panel tests ────────────
# These guard two defects found in review of the original feature. They were
# written against `/api/items/{id}/serp-panel`, a route removed as dead code;
# the behaviours they cover are shared, so they move here rather than lapse.


def _firecrawl_row(db, item, *, row_id, payload):
    from cvp.models import SerpSearch

    db.add(
        SerpSearch(
            id=row_id,
            item_crop_id=f"crop-{item.id}",
            service="firecrawl",
            request_url="https://api.firecrawl.dev/v2/search",
            request_params="{}",
            response_json=json.dumps(payload),
            status_code=200,
        )
    )
    db.commit()


_PAYLOAD = {
    "success": True,
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


def test_a_web_search_does_not_disable_the_lens_button(client, db_session):
    """C1: the latest-search lookup is service-aware, so firecrawl rows leave Lens alone."""
    it = _item_with_crop(db_session)
    _firecrawl_row(db_session, it, row_id="ss-edit-c1", payload=_PAYLOAD)

    resp = client.get(f"/api/items/{it.id}/edit")
    assert resp.status_code == 200
    lens_button = resp.text.split("data-lens-btn", 1)[1].split(">", 1)[0]
    assert "disabled" not in lens_button


def test_stored_row_reuses_the_items_brand_for_match_type(client, db_session):
    """I2: the stored-row path must pass brand, or a reload downgrades exact -> nearest."""
    it = _item_with_crop(db_session)
    _firecrawl_row(db_session, it, row_id="ss-edit-i2", payload=_PAYLOAD)

    resp = client.get(f"/api/items/{it.id}/edit")
    assert 'name="match_type" value="exact"' in resp.text
