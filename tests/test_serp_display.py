"""Tests for SerpAPI result extraction."""

from cvp.services.serp_display import extract_results

GOOGLE_LENS_FIXTURE = {
    "visual_matches": [
        {
            "title": "KitchenAid 5-Qt. Artisan Stand Mixer",
            "source": "amazon.com",
            "link": "https://www.amazon.com/dp/B00005UP2P",
            "thumbnail": "https://example.com/thumb1.jpg",
            "source_icon": "https://example.com/amazon.ico",
            "price": {"value": "$449.99", "extracted_value": 449.99, "currency": "$"},
        },
        {
            "title": "KitchenAid Stand Mixer Red",
            "source": "target.com",
            "link": "https://www.target.com/p/12345",
            "thumbnail": "https://example.com/thumb2.jpg",
            "source_icon": None,
            "price": None,
        },
        {
            "title": "Mixer 3",
            "source": "walmart.com",
            "link": "https://walmart.com/p/3",
            "thumbnail": None,
            "source_icon": None,
        },
        {
            "title": "Mixer 4",
            "source": "homedepot.com",
            "link": "https://homedepot.com/p/4",
            "thumbnail": None,
            "source_icon": None,
        },
        {
            "title": "Mixer 5",
            "source": "bestbuy.com",
            "link": "https://bestbuy.com/p/5",
            "thumbnail": None,
            "source_icon": None,
        },
        {
            "title": "Mixer 6 — should be excluded",
            "source": "extra.com",
            "link": "https://extra.com",
            "thumbnail": None,
            "source_icon": None,
        },
    ]
}


def test_extract_google_lens_returns_up_to_5():
    results = extract_results("google_lens", GOOGLE_LENS_FIXTURE)
    assert len(results) == 5


def test_extract_google_lens_fields():
    results = extract_results("google_lens", GOOGLE_LENS_FIXTURE)
    first = results[0]
    assert first["title"] == "KitchenAid 5-Qt. Artisan Stand Mixer"
    assert first["source"] == "amazon.com"
    assert first["link"] == "https://www.amazon.com/dp/B00005UP2P"
    assert first["thumbnail"] == "https://example.com/thumb1.jpg"
    assert first["source_icon"] == "https://example.com/amazon.ico"


def test_extract_google_lens_price_cents():
    results = extract_results("google_lens", GOOGLE_LENS_FIXTURE)
    assert results[0]["price_cents"] == 44999
    assert results[1]["price_cents"] is None


def test_extract_google_lens_empty_response():
    results = extract_results("google_lens", {})
    assert results == []


def test_extract_unknown_service_returns_empty():
    results = extract_results("unknown_service", GOOGLE_LENS_FIXTURE)
    assert results == []


def _fc(results):
    return {"success": True, "data": {"web": results}}


def _hit(url="https://shop.example/p/1", title="Result", **extracted):
    payload = {
        "product_title": "Oak Dining Chair",
        "price": 129.99,
        "currency": "USD",
        "retailer": "Shop Example",
        "is_product_page": True,
    }
    payload.update(extracted)
    return {"url": url, "title": title, "json": payload}


def test_extract_firecrawl_maps_fields():
    [r] = extract_results("firecrawl", _fc([_hit()]))
    assert r["title"] == "Oak Dining Chair"
    assert r["source"] == "Shop Example"
    assert r["link"] == "https://shop.example/p/1"
    assert r["price_cents"] == 12999
    assert r["thumbnail"] is None
    assert r["source_icon"] is None


def test_extract_firecrawl_falls_back_to_result_title_and_hostname():
    hit = _hit(product_title=None, retailer=None)
    [r] = extract_results("firecrawl", _fc([hit]))
    assert r["title"] == "Result"
    assert r["source"] == "shop.example"


def test_extract_firecrawl_drops_non_product_pages():
    assert extract_results("firecrawl", _fc([_hit(is_product_page=False)])) == []


def test_extract_firecrawl_drops_non_usd():
    assert extract_results("firecrawl", _fc([_hit(currency="GBP")])) == []


def test_extract_firecrawl_keeps_missing_currency():
    [r] = extract_results("firecrawl", _fc([_hit(currency=None)]))
    assert r["price_cents"] == 12999


def test_extract_firecrawl_drops_missing_price():
    assert extract_results("firecrawl", _fc([_hit(price=None)])) == []


def test_extract_firecrawl_drops_zero_price():
    assert extract_results("firecrawl", _fc([_hit(price=0)])) == []


def test_extract_firecrawl_drops_results_without_extraction():
    assert extract_results("firecrawl", _fc([{"url": "https://x.example", "title": "X"}])) == []


def test_extract_firecrawl_caps_at_5():
    assert len(extract_results("firecrawl", _fc([_hit() for _ in range(9)]))) == 5


def test_extract_firecrawl_empty_response():
    assert extract_results("firecrawl", {}) == []


def test_extract_firecrawl_match_type_exact_when_brand_in_title():
    [r] = extract_results(
        "firecrawl", _fc([_hit(product_title="Stickley Oak Chair")]), brand="Stickley"
    )
    assert r["match_type"] == "exact"


def test_extract_firecrawl_match_type_nearest_when_brand_absent():
    [r] = extract_results("firecrawl", _fc([_hit()]), brand="Stickley")
    assert r["match_type"] == "nearest_comparable"


def test_extract_firecrawl_match_type_nearest_when_no_brand_known():
    [r] = extract_results("firecrawl", _fc([_hit()]))
    assert r["match_type"] == "nearest_comparable"


def test_extract_google_lens_match_type_is_nearest_comparable():
    """A visual match is a resemblance, not a confirmed exact product."""
    resp = {"visual_matches": [{"title": "Chair", "link": "https://x.example"}]}
    [r] = extract_results("google_lens", resp)
    assert r["match_type"] == "nearest_comparable"
