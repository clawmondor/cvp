"""The "Get AI Recommendations" button renders in the inline item edit row.

Follows the pattern established in tests/test_item_edit_web_search.py: the
route under test, `items.item_edit_form`, declares its auth inline
(`Depends(require_matter_role("editor"))`), so there is no stable
module-level object to override by identity — the inline dependency has to
be extracted via `inspect.signature`. The route also opens its own session
with `SessionLocal()` rather than taking `get_db`, so the session is patched
via monkeypatch rather than `app.dependency_overrides[get_db]`.
"""

import inspect
import pathlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from cvp.dependencies import CurrentUser
from cvp.main import app
from cvp.models import Base, Category, Item, Matter
from cvp.models_agent import AgentKey, AgentRun
from cvp.services.agent_keys import generate_key

MATTER_ID = "m-agb"
USER_ID = "u-agb"


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

    dep = inspect.signature(items_router.item_edit_form).parameters["user"].default.dependency
    app.dependency_overrides[dep] = mock_user
    monkeypatch.setattr("cvp.routers.items.SessionLocal", lambda: db_session)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _item(db):
    it = Item(matter_id=MATTER_ID, category_id=1, description="chair", quantity=1)
    db.add(it)
    db.commit()
    db.refresh(it)
    return it


def test_edit_row_renders_launch_button(client, db_session):
    item = _item(db_session)
    resp = client.get(f"/api/items/{item.id}/edit")
    assert resp.status_code == 200
    assert "Get AI Recommendations" in resp.text
    assert f'hx-post="/api/items/{item.id}/agent-runs"' in resp.text


def test_edit_row_has_no_inline_handlers(client, db_session):
    item = _item(db_session)
    html = client.get(f"/api/items/{item.id}/edit").text
    for handler in ("onclick=", "onchange=", "onsubmit="):
        assert handler not in html


def test_edit_row_shows_existing_run_status(client, db_session):
    item = _item(db_session)
    _, prefix, key_hash = generate_key()
    key = AgentKey(name="cf", key_prefix=prefix, key_hash=key_hash)
    db_session.add(key)
    db_session.commit()
    db_session.add(
        AgentRun(
            item_id=item.id,
            matter_id=item.matter_id,
            agent_impl="custom-python",
            model_slug="anthropic/claude-haiku-4.5",
            agent_key_id=key.id,
            status="searching",
            status_message="Looking for retail matches…",
        )
    )
    db_session.commit()

    html = client.get(f"/api/items/{item.id}/edit").text
    assert "Looking for retail matches" in html
    assert 'hx-trigger="every 2s"' in html


def test_edit_row_wires_launch_errors_to_an_error_box(client, db_session):
    """A rejected launch must be visible: htmx discards non-2xx bodies, so the
    guard's `detail` only reaches the specialist through this wiring."""
    item = _item(db_session)
    html = client.get(f"/api/items/{item.id}/edit").text
    assert "data-agent-run-form" in html
    assert f'data-agent-run-error="agent-run-error-{item.id}"' in html
    assert f'id="agent-run-error-{item.id}"' in html


def test_app_js_renders_launch_errors_without_inline_handlers(client, db_session):
    """The listener has to live in app.js: CSP script-src has no unsafe-inline."""
    app_js = (
        pathlib.Path(__file__).resolve().parents[1] / "src" / "cvp" / "static" / "app.js"
    ).read_text()
    assert "htmx:responseError" in app_js
    assert "data-agent-run-form" in app_js
    assert "data-agent-run-error" in app_js


def test_succeeded_run_in_edit_row_omits_the_out_of_band_swap(client, db_session):
    """Inline in the edit row, #ai-recs-<id> has not loaded yet — an OOB swap
    here is dropped by htmx with oobErrorNoTarget."""
    item = _item(db_session)
    _, prefix, key_hash = generate_key()
    key = AgentKey(name="cf", key_prefix=prefix, key_hash=key_hash)
    db_session.add(key)
    db_session.commit()
    db_session.add(
        AgentRun(
            item_id=item.id,
            matter_id=item.matter_id,
            agent_impl="custom-python",
            model_slug="anthropic/claude-haiku-4.5",
            agent_key_id=key.id,
            status="succeeded",
        )
    )
    db_session.commit()

    html = client.get(f"/api/items/{item.id}/edit").text
    assert "Done" in html
    assert "hx-swap-oob" not in html
