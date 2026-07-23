"""Depreciation formula — pure functions, no database access."""

CONDITION_MULTIPLIERS: dict[str, float] = {
    "excellent": 0.75,
    "above_average": 0.90,
    "average": 1.00,
    "below_average": 1.15,
}

CONDITIONS = list(CONDITION_MULTIPLIERS.keys())


def compute_acv(
    retail_unit_cents: int,
    quantity: int,
    age_years: float,
    useful_life_years: int | None,
    acv_floor_pct: float,
    condition: str,
    acv_override_cents: int | None = None,
    shipping_cents: int = 0,
) -> int:
    """
    Return ACV total cents per the depreciation schedule.

    RCV = retail value + shipping. Shipping is part of RCV but passes through
    ACV undepreciated (you cannot depreciate the cost of shipping a new
    replacement item), so it is added after depreciation.

    If acv_override_cents is set it is the absolute final ACV — shipping is NOT
    added on top of it. If useful_life_years is None the item is
    non-depreciable: item ACV == item RCV (shipping still added).
    """
    if acv_override_cents is not None:
        return acv_override_cents

    if useful_life_years is None:
        return retail_unit_cents * quantity + shipping_cents  # non-depreciable

    multiplier = CONDITION_MULTIPLIERS.get(condition, 1.00)
    dep_rate = 1.0 / useful_life_years
    max_dep = 1.0 - acv_floor_pct  # floor enforced here
    accumulated_dep = min(dep_rate * age_years * multiplier, max_dep)
    acv_unit = round(retail_unit_cents * (1.0 - accumulated_dep))
    return acv_unit * quantity + shipping_cents
