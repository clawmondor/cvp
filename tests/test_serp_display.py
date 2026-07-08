"""Tests for SerpAPI result extraction."""

from claimos.services.serp_display import extract_results

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
