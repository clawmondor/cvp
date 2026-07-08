# Depreciation Schedule

**Status:** Source of truth for `src/claimos/seed.py` and `src/claimos/depreciation.py`
**Last reviewed:** [date]

This file is the canonical reference for the personal-property depreciation methodology used in every Contents Inventory and Valuation Report. The seed script reads this table and populates the `categories` table. The depreciation formula in `src/claimos/depreciation.py` uses these values at runtime. **If you edit this file, regenerate the seed and re-run migrations.**

---

## Sources

The useful-life values below are drawn from three sources, in order of precedence:

1. **IRS Publication 946 — How to Depreciate Property** (MACRS tables for personal-use property).
2. **Marshall & Swift / CoreLogic residential depreciation tables**, which underlie the pricing databases used by Xactimate Contents and Symbility.
3. **Enservio / Verisk contents-valuation norms** observed in carrier-accepted reports, where categories 1–3 don't give clear guidance.

Where sources disagree, the values below reflect a conservative midpoint that mirrors what California first-party property carriers typically accept without pushback. These values should be reviewed annually and updated if market or carrier practice shifts.

## Methodology

ACV is computed as:

```
straight_line_dep_rate = 1 / useful_life_years
accumulated_dep = min(
    straight_line_dep_rate * age_years * condition_multiplier,
    1 - acv_floor_pct
)
acv_unit_cents = round(rcv_unit_cents * (1 - accumulated_dep))
acv_total_cents = acv_unit_cents * quantity
```

**Condition multipliers** (applied to the straight-line depreciation rate):

| Condition     | Multiplier | Interpretation |
|---------------|-----------:|----------------|
| Excellent     | 0.75       | Documented as above-average care; depreciates slower |
| Above average | 0.90       | Slight adjustment for well-maintained items |
| Average       | 1.00       | Default — normal wear and tear |
| Below average | 1.15       | Documented damage, heavy use, or outdated condition |

**Floor:** an item's ACV is never depreciated below `rcv × acv_floor_pct` while the item is still functional. This floor mirrors the practical reality that a 20-year-old working refrigerator still has real replacement value, and it's what carriers using Xactimate and Enservio typically accept.

**Non-depreciable categories:** items in categories with `useful_life_years = NULL` (artwork, jewelry, collectibles, precious metals) are presented at RCV with no depreciation applied. These items are usually covered by scheduled-property riders rather than Coverage C, and the seed script flags them accordingly. A note appears in the inventory row explaining why no depreciation was taken.

---

## The 42 categories

| ID | Category                                         | Useful life (yrs) | Annual dep. | ACV floor | Notes |
|---:|:-------------------------------------------------|:-----------------:|:-----------:|:---------:|:------|
|  1 | Clothing, everyday                               |  5  | 20.0% | 20% | T-shirts, jeans, socks, underwear, casual wear |
|  2 | Clothing, outerwear and formal                   |  8  | 12.5% | 20% | Coats, suits, dresses, formal wear |
|  3 | Clothing, children                               |  3  | 33.3% | 20% | Shorter useful life due to outgrowth |
|  4 | Footwear                                         |  4  | 25.0% | 20% | Shoes, boots, sandals, athletic |
|  5 | Accessories (belts, bags, scarves, hats)         |  6  | 16.7% | 20% | Excludes designer handbags — see category 6 |
|  6 | Designer handbags and luxury accessories         |  10 | 10.0% | 30% | Items over $500 at purchase; may need rider |
|  7 | Jewelry, non-appraised, within policy sublimit   | N/A |  —    | 100%| Presented at RCV; often rider-covered |
|  8 | Watches (non-luxury, non-appraised)              |  10 | 10.0% | 25% | Casual and fashion watches |
|  9 | Furniture, upholstered (sofas, chairs)           |  10 | 10.0% | 20% | Fabric and leather upholstery |
| 10 | Furniture, wood case goods                       |  15 | 6.7%  | 25% | Tables, dressers, bookcases, desks |
| 11 | Furniture, mattresses and box springs            |  8  | 12.5% | 20% | Includes foundations |
| 12 | Bedding, linens, towels                          |  6  | 16.7% | 20% | Sheets, duvets, pillowcases, bath linens |
| 13 | Window treatments (curtains, blinds, shades)     |  10 | 10.0% | 20% | Soft and hard window coverings |
| 14 | Rugs, machine-made                               |  10 | 10.0% | 25% | Area rugs, runners, entry rugs |
| 15 | Rugs, handmade or antique                        |  25 | 4.0%  | 50% | Oriental, tribal, hand-knotted |
| 16 | Kitchen appliances, large                        |  12 | 8.3%  | 20% | Refrigerator, oven, dishwasher, washer, dryer |
| 17 | Kitchen appliances, small                        |  8  | 12.5% | 20% | Toasters, blenders, coffee makers, mixers |
| 18 | Cookware, bakeware, utensils                     |  10 | 10.0% | 25% | Pots, pans, knives, kitchen tools |
| 19 | Dinnerware, glassware, flatware                  |  15 | 6.7%  | 25% | Plates, bowls, glasses, silverware |
| 20 | Small kitchen goods (storage, serveware)         |  8  | 12.5% | 20% | Food containers, serving platters, dish towels |
| 21 | Electronics, TVs and displays                    |  7  | 14.3% | 20% | TVs, monitors, projectors |
| 22 | Electronics, computers and tablets               |  4  | 25.0% | 20% | Laptops, desktops, iPads, Chromebooks |
| 23 | Electronics, smartphones                         |  3  | 33.3% | 20% | Fastest-depreciating electronics category |
| 24 | Electronics, audio and home theater              |  7  | 14.3% | 20% | Speakers, receivers, soundbars |
| 25 | Electronics, cameras and lenses                  |  6  | 16.7% | 25% | DSLRs, mirrorless, lenses, accessories |
| 26 | Electronics, gaming consoles and games           |  5  | 20.0% | 20% | PlayStation, Xbox, Nintendo, handhelds |
| 27 | Electronics, small and miscellaneous             |  5  | 20.0% | 20% | Routers, printers, chargers, cables |
| 28 | Books, records, physical media                   |  20 | 5.0%  | 25% | Books, vinyl, CDs, DVDs |
| 29 | Toys and games                                   |  6  | 16.7% | 20% | Children's toys, board games, puzzles |
| 30 | Sporting goods and exercise equipment            |  8  | 12.5% | 20% | Bikes, weights, treadmills, gear |
| 31 | Outdoor furniture and grills                     |  8  | 12.5% | 20% | Patio sets, umbrellas, gas/charcoal grills |
| 32 | Outdoor equipment (lawn, garden, tools)          |  10 | 10.0% | 20% | Mowers, trimmers, hand tools, hoses |
| 33 | Power tools and workshop                         |  12 | 8.3%  | 25% | Drills, saws, compressors, workbenches |
| 34 | Hand tools and hardware                          |  15 | 6.7%  | 25% | Hammers, wrenches, screwdrivers, hardware |
| 35 | Musical instruments (non-appraised)              |  20 | 5.0%  | 30% | Guitars, keyboards, drums, wind instruments |
| 36 | Artwork, non-appraised                           | N/A |  —    | 100%| Presented at RCV; often rider-covered |
| 37 | Collectibles and memorabilia                     | N/A |  —    | 100%| Presented at RCV; often rider-covered |
| 38 | Precious metals and coins                        | N/A |  —    | 100%| Presented at RCV; often rider-covered |
| 39 | Food, pantry, household consumables              |  1  | 100%  | 20% | Non-perishables; perishables excluded from report |
| 40 | Personal care and cosmetics                      |  2  | 50.0% | 20% | Toiletries, makeup, skincare |
| 41 | Office supplies and stationery                   |  5  | 20.0% | 20% | Paper, pens, binders, small office equipment |
| 42 | Miscellaneous household goods                    |  8  | 12.5% | 20% | Catch-all for items not fitting categories 1-41 |

---

## Seed data format

The seed script reads this file and populates the `categories` table. The JSON representation of each row must match this shape exactly:

```python
{
    "id": 1,
    "name": "Clothing, everyday",
    "useful_life_years": 5,         # or None for non-depreciable
    "acv_floor_pct": 0.20,           # float between 0 and 1
    "notes": "T-shirts, jeans, socks, underwear, casual wear"
}
```

Store the full list as a Python constant in `src/claimos/seed.py`. The seed script is idempotent: running it twice should not create duplicate rows. Use `INSERT OR IGNORE` or an upsert keyed on `id`.

---

## Edge cases the formula must handle

These are the cases the unit tests in `tests/test_depreciation.py` must cover:

1. **Brand-new item (age = 0).** `accumulated_dep = 0`, ACV equals RCV exactly.
2. **Item older than its useful life (age > useful_life).** Without a floor, straight-line would drive ACV negative. The floor clamps ACV at `rcv × acv_floor_pct`. Test with age = useful_life × 2 and age = useful_life × 5 to confirm the floor holds.
3. **Condition = excellent with a high age.** The multiplier of 0.75 slows depreciation. A 6-year-old "excellent" sofa depreciates as if it were 4.5 years old in average condition.
4. **Condition = below average.** The multiplier of 1.15 accelerates depreciation but the floor still holds.
5. **Non-depreciable category (useful_life_years IS NULL).** ACV equals RCV regardless of age and condition. The formula must short-circuit before dividing.
6. **Override present.** When `acv_override_cents` is set with a non-empty reason, the computed value is ignored and the override is used. The presence of the override must be surfaced to the UI.
7. **Fractional age (age = 0.5).** Straight-line depreciation is linear, so a half-year-old item depreciates at half the annual rate. Use `float` for age input but `int` for all currency math.
8. **Quantity > 1.** RCV total and ACV total both scale by quantity. Per-unit values are computed first, then multiplied by quantity to avoid rounding accumulation.
9. **Very small RCV (under 100 cents).** Rounding to integer cents must not zero out small items. Test with RCV = 50 cents.
10. **Very large RCV (over $100,000).** No overflow, no float conversion. Test with RCV = $250,000.

---

## Revision policy

- Useful-life values are reviewed annually, or sooner if a carrier or appraisal panel formally rejects one of them in a real claim. When that happens, document the rejection in this file with the date, the carrier, and the panel's reasoning.
- New categories are added only when a real claim has more than 10 items that don't fit any existing category. Expanding the category list dilutes the usefulness of each category and makes bulk-editing harder.
- Condition multipliers and floor percentages are more stable than useful lives. Do not change them without a team discussion and a note in the PR.
- Any change to this file requires a corresponding test update in `tests/test_depreciation.py`.
