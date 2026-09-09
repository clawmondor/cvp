"""Unit tests for the Firecrawl service."""

from cvp.models import Item
from cvp.services.firecrawl import build_query


def _item(**kw) -> Item:
    defaults = {"description": "", "brand": None, "model": None}
    defaults.update(kw)
    return Item(**defaults)


def test_build_query_joins_brand_model_description():
    item = _item(brand="Stickley", model="A-12", description="oak dining chair")
    assert build_query(item) == "Stickley A-12 oak dining chair"


def test_build_query_skips_missing_brand_and_model():
    item = _item(description="oak dining chair")
    assert build_query(item) == "oak dining chair"


def test_build_query_skips_blank_strings():
    item = _item(brand="   ", model="", description="lamp")
    assert build_query(item) == "lamp"


def test_build_query_collapses_internal_whitespace():
    item = _item(brand="West  Elm", description="floor\tlamp\n")
    assert build_query(item) == "West Elm floor lamp"


def test_build_query_all_empty_returns_empty_string():
    assert build_query(_item()) == ""
