"""The crop panel renders both search tabs with no inline event handlers."""

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent

TPL = (ROOT / "src/cvp/templates/_serp_panel.html").read_text()


def test_panel_has_both_search_tabs():
    assert "data-serp-tab-target" in TPL
    assert "Google Lens" in TPL
    assert "Web search" in TPL


def test_panel_posts_to_the_firecrawl_endpoint():
    assert "/serp/firecrawl" in TPL


def test_panel_prefills_an_editable_query_input():
    assert re.search(r'name="query"[^>]*value="\{\{ *default_query', TPL)


def test_panel_has_no_inline_event_handlers():
    """CSP script-src has no unsafe-inline — handlers must be delegated via app.js."""
    for attr in ("onclick=", "onchange=", "onsubmit=", "hx-on:"):
        assert attr not in TPL, f"inline handler {attr} is CSP-blocked"


EDIT_TPL = (Path(__file__).parent.parent / "src/cvp/templates/_item_row_edit.html").read_text()


def test_edit_row_lens_button_keys_off_the_lens_map_only():
    """The inline edit row is a second copy of the same UI — same service-aware binding."""
    assert "latest_lens_by_crop" in EDIT_TPL
    assert "display_lens_by_crop" in EDIT_TPL
    assert "latest_by_crop" not in EDIT_TPL.replace("latest_lens_by_crop", "")
    assert "display_by_crop" not in EDIT_TPL.replace("display_lens_by_crop", "")
