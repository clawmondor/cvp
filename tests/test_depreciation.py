"""Unit tests for the depreciation formula."""

from claimos.depreciation import compute_acv


def test_normal_case():
    # 10-year life, 3 years old, average condition (×1.0), floor 20%
    # dep = min(1/10 * 3 * 1.0, 0.80) = 0.30
    # acv_unit = round(10000 * 0.70) = 7000
    # acv_total = 7000 * 2 = 14000
    result = compute_acv(
        rcv_unit_cents=10_000,
        quantity=2,
        age_years=3.0,
        useful_life_years=10,
        acv_floor_pct=0.20,
        condition="average",
    )
    assert result == 14_000


def test_zero_age():
    # 0 years old → no depreciation → ACV == RCV
    result = compute_acv(
        rcv_unit_cents=5_000,
        quantity=1,
        age_years=0.0,
        useful_life_years=10,
        acv_floor_pct=0.20,
        condition="average",
    )
    assert result == 5_000


def test_age_exceeds_useful_life_hits_floor():
    # 5-year life, 20 years old → dep would be 1/5 * 20 * 1.0 = 4.0 but capped
    # max_dep = 1 - 0.20 = 0.80 → accumulated_dep = 0.80
    # acv_unit = round(10000 * 0.20) = 2000
    result = compute_acv(
        rcv_unit_cents=10_000,
        quantity=1,
        age_years=20.0,
        useful_life_years=5,
        acv_floor_pct=0.20,
        condition="average",
    )
    assert result == 2_000


def test_floor_enforcement_exact():
    # 10-year life, 8 years, average → dep = 0.80 = max_dep → ACV = floor
    result = compute_acv(
        rcv_unit_cents=10_000,
        quantity=1,
        age_years=8.0,
        useful_life_years=10,
        acv_floor_pct=0.20,
        condition="average",
    )
    assert result == 2_000  # exactly at floor


def test_condition_excellent_slows_depreciation():
    # multiplier 0.75 → dep = 1/10 * 5 * 0.75 = 0.375
    # acv_unit = round(10000 * 0.625) = 6250
    result = compute_acv(
        rcv_unit_cents=10_000,
        quantity=1,
        age_years=5.0,
        useful_life_years=10,
        acv_floor_pct=0.20,
        condition="excellent",
    )
    assert result == 6_250


def test_condition_below_average_accelerates_depreciation():
    # multiplier 1.15 → dep = 1/10 * 5 * 1.15 = 0.575
    # acv_unit = round(10000 * 0.425) = 4250
    result = compute_acv(
        rcv_unit_cents=10_000,
        quantity=1,
        age_years=5.0,
        useful_life_years=10,
        acv_floor_pct=0.20,
        condition="below_average",
    )
    assert result == 4_250


def test_override_takes_precedence():
    # Even with old age and bad condition, override wins
    result = compute_acv(
        rcv_unit_cents=10_000,
        quantity=3,
        age_years=99.0,
        useful_life_years=5,
        acv_floor_pct=0.20,
        condition="below_average",
        acv_override_cents=99_999,
    )
    assert result == 99_999


def test_null_useful_life_no_depreciation():
    # Artwork / jewelry — ACV == RCV total, regardless of age
    result = compute_acv(
        rcv_unit_cents=50_000,
        quantity=2,
        age_years=30.0,
        useful_life_years=None,
        acv_floor_pct=1.00,
        condition="below_average",
    )
    assert result == 100_000


def test_quantity_multiplied_correctly():
    # ACV per unit then × quantity (not round(total))
    # dep = 1/10 * 3 * 1.0 = 0.30 → acv_unit = round(333 * 0.70) = 233
    # acv_total = 233 * 5 = 1165
    result = compute_acv(
        rcv_unit_cents=333,
        quantity=5,
        age_years=3.0,
        useful_life_years=10,
        acv_floor_pct=0.20,
        condition="average",
    )
    assert result == 1_165
