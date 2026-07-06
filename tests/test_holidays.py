"""Unit tests for the holiday table (webcaldav.holidays).

Covers: fixed-date holidays, Easter-based holidays (Good Friday/Easter Monday),
validity ranges (Good Friday effective_from=2016), and graceful skip outside
the hardcoded Easter table bounds.
"""

from webcaldav.holidays import (
    EASTER_SUNDAY,
    SUPPORTED_COUNTRIES,
    WEEKEND_NAME_KEY,
    holidays_for_range,
    holidays_for_year,
    weekend_days,
)


def _keys(country: str, year: int) -> set[str]:
    return {k for _, k in holidays_for_year(country, year)}


def _dates(country: str, year: int) -> set[str]:
    return {iso for iso, _ in holidays_for_year(country, year)}


def test_supported_countries():
    assert "none" in SUPPORTED_COUNTRIES
    assert "CZ" in SUPPORTED_COUNTRIES


def test_weekend_cz_is_sat_sun():
    # JS/FC convention: 0=Sunday, 6=Saturday.
    assert weekend_days("CZ") == frozenset({0, 6})


def test_weekend_unknown_country_empty():
    assert weekend_days("XX") == frozenset()


def test_cz_fixed_holidays_2024():
    # 13 holidays total in 2024 (Good Friday included since 2016).
    assert len(holidays_for_year("CZ", 2024)) == 13
    dates = _dates("CZ", 2024)
    assert "2024-01-01" in dates
    assert "2024-05-01" in dates
    assert "2024-05-08" in dates
    assert "2024-07-05" in dates
    assert "2024-07-06" in dates
    assert "2024-09-28" in dates
    assert "2024-10-28" in dates
    assert "2024-11-17" in dates
    assert "2024-12-24" in dates
    assert "2024-12-25" in dates
    assert "2024-12-26" in dates


def test_cz_easter_monday_known_dates():
    # Verified against public Czech calendars + Nager.Date.
    assert "2024-04-01" in _dates("CZ", 2024)
    assert "2025-04-21" in _dates("CZ", 2025)
    assert "2026-04-06" in _dates("CZ", 2026)


def test_cz_good_friday_known_dates():
    # Good Friday = Easter Sunday - 2.
    assert "2024-03-29" in _dates("CZ", 2024)
    assert "2025-04-18" in _dates("CZ", 2025)
    assert "2026-04-03" in _dates("CZ", 2026)


def test_good_friday_absent_before_2016():
    # Good Friday became a CZ public holiday in 2016.
    assert "holiday.cz.good_friday" not in _keys("CZ", 2015)
    assert "holiday.cz.good_friday" in _keys("CZ", 2016)


def test_easter_skipped_outside_table_bounds():
    # Years outside the EASTER_SUNDAY table degrade gracefully: Easter-based
    # holidays are silently skipped, fixed holidays are unaffected.
    assert EASTER_SUNDAY  # table non-empty
    min_year, max_year = min(EASTER_SUNDAY), max(EASTER_SUNDAY)
    pre = _keys("CZ", min_year - 1)
    post = _keys("CZ", max_year + 1)
    assert "holiday.cz.easter_monday" not in pre
    assert "holiday.cz.good_friday" not in pre
    assert "holiday.cz.easter_monday" not in post
    assert "holiday.cz.good_friday" not in post
    # Fixed holidays still present outside the table bounds.
    assert "holiday.cz.new_year" in pre
    assert "holiday.cz.new_year" in post


def test_holidays_sorted_by_date():
    out = holidays_for_year("CZ", 2024)
    isos = [iso for iso, _ in out]
    assert isos == sorted(isos)


def test_range_spans_multiple_years():
    # Dec 2024 -> Jan 2025 crosses a year boundary.
    r = holidays_for_range("CZ", "2024-12-24", "2025-01-02")
    assert r["2024-12-24"] == "holiday.cz.christmas_eve"
    assert r["2024-12-26"] == "holiday.cz.boxing_day"
    assert r["2025-01-01"] == "holiday.cz.new_year"


def test_range_reversed_is_empty():
    assert holidays_for_range("CZ", "2025-01-02", "2024-12-24") == {}


def test_weekend_name_key_constant():
    assert WEEKEND_NAME_KEY == "holiday.weekend"


def test_unknown_country_yields_no_holidays():
    assert holidays_for_year("XX", 2024) == []
