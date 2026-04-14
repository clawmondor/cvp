"""
Category seed data from docs/depreciation-schedule.md.
Entry point: uv run seed
Idempotent: safe to run multiple times.
"""

from sqlalchemy.orm import Session

from cvp.db import SessionLocal
from cvp.models import Category

CATEGORIES: list[dict] = [
    {
        "id": 1,
        "name": "Clothing, everyday",
        "useful_life_years": 5,
        "acv_floor_pct": 0.20,
        "notes": "T-shirts, jeans, socks, underwear, casual wear",
    },
    {
        "id": 2,
        "name": "Clothing, outerwear and formal",
        "useful_life_years": 8,
        "acv_floor_pct": 0.20,
        "notes": "Coats, suits, dresses, formal wear",
    },
    {
        "id": 3,
        "name": "Clothing, children",
        "useful_life_years": 3,
        "acv_floor_pct": 0.20,
        "notes": "Shorter useful life due to outgrowth",
    },
    {
        "id": 4,
        "name": "Footwear",
        "useful_life_years": 4,
        "acv_floor_pct": 0.20,
        "notes": "Shoes, boots, sandals, athletic",
    },
    {
        "id": 5,
        "name": "Accessories (belts, bags, scarves, hats)",
        "useful_life_years": 6,
        "acv_floor_pct": 0.20,
        "notes": "Excludes designer handbags — see category 6",
    },
    {
        "id": 6,
        "name": "Designer handbags and luxury accessories",
        "useful_life_years": 10,
        "acv_floor_pct": 0.30,
        "notes": "Items over $500 at purchase; may need rider",
    },
    {
        "id": 7,
        "name": "Jewelry, non-appraised, within policy sublimit",
        "useful_life_years": None,
        "acv_floor_pct": 1.00,
        "notes": "Presented at RCV; often rider-covered",
    },
    {
        "id": 8,
        "name": "Watches (non-luxury, non-appraised)",
        "useful_life_years": 10,
        "acv_floor_pct": 0.25,
        "notes": "Casual and fashion watches",
    },
    {
        "id": 9,
        "name": "Furniture, upholstered (sofas, chairs)",
        "useful_life_years": 10,
        "acv_floor_pct": 0.20,
        "notes": "Fabric and leather upholstery",
    },
    {
        "id": 10,
        "name": "Furniture, wood case goods",
        "useful_life_years": 15,
        "acv_floor_pct": 0.25,
        "notes": "Tables, dressers, bookcases, desks",
    },
    {
        "id": 11,
        "name": "Furniture, mattresses and box springs",
        "useful_life_years": 8,
        "acv_floor_pct": 0.20,
        "notes": "Includes foundations",
    },
    {
        "id": 12,
        "name": "Bedding, linens, towels",
        "useful_life_years": 6,
        "acv_floor_pct": 0.20,
        "notes": "Sheets, duvets, pillowcases, bath linens",
    },
    {
        "id": 13,
        "name": "Window treatments (curtains, blinds, shades)",
        "useful_life_years": 10,
        "acv_floor_pct": 0.20,
        "notes": "Soft and hard window coverings",
    },
    {
        "id": 14,
        "name": "Rugs, machine-made",
        "useful_life_years": 10,
        "acv_floor_pct": 0.25,
        "notes": "Area rugs, runners, entry rugs",
    },
    {
        "id": 15,
        "name": "Rugs, handmade or antique",
        "useful_life_years": 25,
        "acv_floor_pct": 0.50,
        "notes": "Oriental, tribal, hand-knotted",
    },
    {
        "id": 16,
        "name": "Kitchen appliances, large",
        "useful_life_years": 12,
        "acv_floor_pct": 0.20,
        "notes": "Refrigerator, oven, dishwasher, washer, dryer",
    },
    {
        "id": 17,
        "name": "Kitchen appliances, small",
        "useful_life_years": 8,
        "acv_floor_pct": 0.20,
        "notes": "Toasters, blenders, coffee makers, mixers",
    },
    {
        "id": 18,
        "name": "Cookware, bakeware, utensils",
        "useful_life_years": 10,
        "acv_floor_pct": 0.25,
        "notes": "Pots, pans, knives, kitchen tools",
    },
    {
        "id": 19,
        "name": "Dinnerware, glassware, flatware",
        "useful_life_years": 15,
        "acv_floor_pct": 0.25,
        "notes": "Plates, bowls, glasses, silverware",
    },
    {
        "id": 20,
        "name": "Small kitchen goods (storage, serveware)",
        "useful_life_years": 8,
        "acv_floor_pct": 0.20,
        "notes": "Food containers, serving platters, dish towels",
    },
    {
        "id": 21,
        "name": "Electronics, TVs and displays",
        "useful_life_years": 7,
        "acv_floor_pct": 0.20,
        "notes": "TVs, monitors, projectors",
    },
    {
        "id": 22,
        "name": "Electronics, computers and tablets",
        "useful_life_years": 4,
        "acv_floor_pct": 0.20,
        "notes": "Laptops, desktops, iPads, Chromebooks",
    },
    {
        "id": 23,
        "name": "Electronics, smartphones",
        "useful_life_years": 3,
        "acv_floor_pct": 0.20,
        "notes": "Fastest-depreciating electronics category",
    },
    {
        "id": 24,
        "name": "Electronics, audio and home theater",
        "useful_life_years": 7,
        "acv_floor_pct": 0.20,
        "notes": "Speakers, receivers, soundbars",
    },
    {
        "id": 25,
        "name": "Electronics, cameras and lenses",
        "useful_life_years": 6,
        "acv_floor_pct": 0.25,
        "notes": "DSLRs, mirrorless, lenses, accessories",
    },
    {
        "id": 26,
        "name": "Electronics, gaming consoles and games",
        "useful_life_years": 5,
        "acv_floor_pct": 0.20,
        "notes": "PlayStation, Xbox, Nintendo, handhelds",
    },
    {
        "id": 27,
        "name": "Electronics, small and miscellaneous",
        "useful_life_years": 5,
        "acv_floor_pct": 0.20,
        "notes": "Routers, printers, chargers, cables",
    },
    {
        "id": 28,
        "name": "Books, records, physical media",
        "useful_life_years": 20,
        "acv_floor_pct": 0.25,
        "notes": "Books, vinyl, CDs, DVDs",
    },
    {
        "id": 29,
        "name": "Toys and games",
        "useful_life_years": 6,
        "acv_floor_pct": 0.20,
        "notes": "Children's toys, board games, puzzles",
    },
    {
        "id": 30,
        "name": "Sporting goods and exercise equipment",
        "useful_life_years": 8,
        "acv_floor_pct": 0.20,
        "notes": "Bikes, weights, treadmills, gear",
    },
    {
        "id": 31,
        "name": "Outdoor furniture and grills",
        "useful_life_years": 8,
        "acv_floor_pct": 0.20,
        "notes": "Patio sets, umbrellas, gas/charcoal grills",
    },
    {
        "id": 32,
        "name": "Outdoor equipment (lawn, garden, tools)",
        "useful_life_years": 10,
        "acv_floor_pct": 0.20,
        "notes": "Mowers, trimmers, hand tools, hoses",
    },
    {
        "id": 33,
        "name": "Power tools and workshop",
        "useful_life_years": 12,
        "acv_floor_pct": 0.25,
        "notes": "Drills, saws, compressors, workbenches",
    },
    {
        "id": 34,
        "name": "Hand tools and hardware",
        "useful_life_years": 15,
        "acv_floor_pct": 0.25,
        "notes": "Hammers, wrenches, screwdrivers, hardware",
    },
    {
        "id": 35,
        "name": "Musical instruments (non-appraised)",
        "useful_life_years": 20,
        "acv_floor_pct": 0.30,
        "notes": "Guitars, keyboards, drums, wind instruments",
    },
    {
        "id": 36,
        "name": "Artwork, non-appraised",
        "useful_life_years": None,
        "acv_floor_pct": 1.00,
        "notes": "Presented at RCV; often rider-covered",
    },
    {
        "id": 37,
        "name": "Collectibles and memorabilia",
        "useful_life_years": None,
        "acv_floor_pct": 1.00,
        "notes": "Presented at RCV; often rider-covered",
    },
    {
        "id": 38,
        "name": "Precious metals and coins",
        "useful_life_years": None,
        "acv_floor_pct": 1.00,
        "notes": "Presented at RCV; often rider-covered",
    },
    {
        "id": 39,
        "name": "Food, pantry, household consumables",
        "useful_life_years": 1,
        "acv_floor_pct": 0.20,
        "notes": "Non-perishables; perishables excluded from report",
    },
    {
        "id": 40,
        "name": "Personal care and cosmetics",
        "useful_life_years": 2,
        "acv_floor_pct": 0.20,
        "notes": "Toiletries, makeup, skincare",
    },
    {
        "id": 41,
        "name": "Office supplies and stationery",
        "useful_life_years": 5,
        "acv_floor_pct": 0.20,
        "notes": "Paper, pens, binders, small office equipment",
    },
    {
        "id": 42,
        "name": "Miscellaneous household goods",
        "useful_life_years": 8,
        "acv_floor_pct": 0.20,
        "notes": "Catch-all for items not fitting categories 1-41",
    },
]


def seed_categories(db: Session) -> int:
    """Insert all 42 categories; skip any that already exist. Returns count inserted."""
    inserted = 0
    for row in CATEGORIES:
        if db.get(Category, row["id"]) is None:
            db.add(Category(**row))
            inserted += 1
    db.commit()
    return inserted


def main() -> None:
    db = SessionLocal()
    try:
        count = seed_categories(db)
        print(f"Seed complete — {count} categories inserted (skipped existing).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
