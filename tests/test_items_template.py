"""Integration test: items tbody renders crop-edit overlay link."""
import pytest
from jinja2 import Environment, FileSystemLoader
from pathlib import Path
from urllib.parse import quote_plus

TEMPLATE_DIR = Path(__file__).parent.parent / "src" / "cvp" / "templates"


@pytest.fixture
def env():
    e = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))
    e.filters["qplus"] = quote_plus
    return e


class FakeCrop:
    def __init__(self):
        self.id = "crop-abc"
        self.evidence_file_id = "ef-xyz"
        self.crop_path = "ef-xyz/item.jpg"


class FakeItem:
    def __init__(self):
        self.id = "item-1"
        self.matter_id = "matter-1"
        self.line_number = 1
        self.description = "Lamp"
        self.brand = None
        self.model = None
        self.source_url = "https://example.com"
        self.search_hint = None
        self.room_id = None
        self.category_id = 1
        self.quantity = 1
        self.age_years = 3
        self.condition = "average"
        self.rcv_unit_cents = 5000
        self.rcv_total_cents = 5000
        self.acv_total_cents = 4000
        self.acv_override_cents = None
        self.acv_override_reason = None
        self.confirmed = False
        self.excluded = False
        self.crops = [FakeCrop()]


def test_tbody_renders_crop_edit_link(env):
    tmpl = env.get_template("_items_tbody.html")
    html = tmpl.render(items=[FakeItem()], categories=[], rooms=[], conditions=[])
    assert "Edit crop" in html
    assert "/matters/matter-1?file=ef-xyz&amp;crop=crop-abc#evidence" in html
    assert 'target="_blank"' in html


def test_tbody_no_overlay_when_no_crop(env):
    item = FakeItem()
    item.crops = []
    tmpl = env.get_template("_items_tbody.html")
    html = tmpl.render(items=[item], categories=[], rooms=[], conditions=[])
    assert "Edit crop" not in html


def test_tbody_no_overlay_when_crop_path_empty(env):
    item = FakeItem()
    item.crops[0].crop_path = None
    tmpl = env.get_template("_items_tbody.html")
    html = tmpl.render(items=[item], categories=[], rooms=[], conditions=[])
    assert "Edit crop" not in html
