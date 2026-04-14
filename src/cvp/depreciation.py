"""Depreciation formula — pure functions, no database access."""

CONDITION_MULTIPLIERS: dict[str, float] = {
    "excellent": 0.75,
    "above_average": 0.90,
    "average": 1.00,
    "below_average": 1.15,
}

CONDITIONS = list(CONDITION_MULTIPLIERS.keys())


def compute_acv(
    rcv_unit_cents: int,
    quantity: int,
    age_years: float,
    useful_life_years: int | None,
    acv_floor_pct: float,
    condition: str,
    acv_override_cents: int | None = None,
) -> int:
    """
    Return ACV total cents per the depreciation schedule.

    If acv_override_cents is set it takes absolute precedence.
    If useful_life_years is None the item is non-depreciable: ACV == RCV.
    """
    if acv_override_cents is not None:
        return acv_override_cents

    rcv_total = rcv_unit_cents * quantity

    if useful_life_years is None:
        return rcv_total  # artwork, jewelry, etc. — no depreciation

    multiplier = CONDITION_MULTIPLIERS.get(condition, 1.00)
    dep_rate = 1.0 / useful_life_years
    max_dep = 1.0 - acv_floor_pct  # floor enforced here
    accumulated_dep = min(dep_rate * age_years * multiplier, max_dep)
    acv_unit = round(rcv_unit_cents * (1.0 - accumulated_dep))
    return acv_unit * quantity
