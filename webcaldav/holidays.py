"""Country holiday definitions and resolution.

The app keeps an **authoritative local** holiday table here — no runtime
network calls. An external API (Nager.Date is the designated upstream
reference, see ``Plan.md``) is only used to periodically verify/refresh this
table by hand; it is never on the request path.

Holiday *definitions* carry a validity range (``effective_from`` /
``effective_to`` years, inclusive, ``None`` = unbounded). This makes future
additions and removals first-class: a holiday that started in some year
carries ``effective_from``; a hypothetically abolished one carries
``effective_to``. Resolution filters the queried year against that range, so
``holidays_for_year`` returns only the holidays actually in force then.

Easter-based holidays (Good Friday, Easter Monday) are *not* computed at
runtime. ``EASTER_SUNDAY`` is a hardcoded date table for years 2000–2100
(per the project's "prefer fixed easter calendar to calculation" rule).
Easter-based ``HolidayDef``\\s carry an ``easter_offset`` (days from Easter
Sunday) and resolve to a concrete date via that table. After resolution they
are indistinguishable from fixed-date holidays — both come back as
``(date_iso, name_key)`` in one flat list, so nothing downstream branches on
the holiday kind.

Weekend days are country-specific (Czechia = Saturday+Sunday); the
``/holidays`` endpoint marks non-holiday weekend days with the
``holiday.weekend`` label so the UI colors them too.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

# Country codes the UI offers. "none" disables the feature.
SUPPORTED_COUNTRIES: dict[str, str] = {
    "none": "holiday.country.none",
    "CZ": "holiday.country.cz",
}

# Hardcoded Gregorian Easter Sunday for the supported year range.
# No runtime Computus/Gauss — per the project rule to prefer a fixed easter
# calendar. Years outside this range degrade gracefully: Easter-based holidays
# are silently skipped (fixed holidays are unaffected). Extending the table is
# a one-place edit.
EASTER_SUNDAY: dict[int, str] = {
    2000: "2000-04-23", 2001: "2001-04-15", 2002: "2002-03-31", 2003: "2003-04-20",
    2004: "2004-04-11", 2005: "2005-03-27", 2006: "2006-04-16", 2007: "2007-04-08",
    2008: "2008-03-23", 2009: "2009-04-12", 2010: "2010-04-04", 2011: "2011-04-24",
    2012: "2012-04-08", 2013: "2013-03-31", 2014: "2014-04-20", 2015: "2015-04-05",
    2016: "2016-03-27", 2017: "2017-04-16", 2018: "2018-04-01", 2019: "2019-04-21",
    2020: "2020-04-12", 2021: "2021-04-04", 2022: "2022-04-17", 2023: "2023-04-09",
    2024: "2024-03-31", 2025: "2025-04-20", 2026: "2026-04-05", 2027: "2027-03-28",
    2028: "2028-04-16", 2029: "2029-04-01", 2030: "2030-04-21", 2031: "2031-04-13",
    2032: "2032-03-28", 2033: "2033-04-17", 2034: "2034-04-09", 2035: "2035-03-25",
    2036: "2036-04-13", 2037: "2037-04-05", 2038: "2038-04-25", 2039: "2039-04-10",
    2040: "2040-04-01", 2041: "2041-04-21", 2042: "2042-04-06", 2043: "2043-03-29",
    2044: "2044-04-17", 2045: "2045-04-09", 2046: "2046-03-25", 2047: "2047-04-14",
    2048: "2048-04-05", 2049: "2049-04-18", 2050: "2050-04-10", 2051: "2051-04-02",
    2052: "2052-04-21", 2053: "2053-04-06", 2054: "2054-03-29", 2055: "2055-04-18",
    2056: "2056-04-02", 2057: "2057-04-22", 2058: "2058-04-14", 2059: "2059-03-30",
    2060: "2060-04-18", 2061: "2061-04-10", 2062: "2062-03-26", 2063: "2063-04-15",
    2064: "2064-04-06", 2065: "2065-03-29", 2066: "2066-04-11", 2067: "2067-04-03",
    2068: "2068-04-22", 2069: "2069-04-14", 2070: "2070-03-30", 2071: "2071-04-19",
    2072: "2072-04-10", 2073: "2073-03-26", 2074: "2074-04-15", 2075: "2075-04-07",
    2076: "2076-04-19", 2077: "2077-04-11", 2078: "2078-04-03", 2079: "2079-04-23",
    2080: "2080-04-07", 2081: "2081-03-30", 2082: "2082-04-19", 2083: "2083-04-04",
    2084: "2084-03-26", 2085: "2085-04-15", 2086: "2086-03-31", 2087: "2087-04-20",
    2088: "2088-04-11", 2089: "2089-04-03", 2090: "2090-04-16", 2091: "2091-04-08",
    2092: "2092-03-30", 2093: "2093-04-12", 2094: "2094-04-04", 2095: "2095-04-24",
    2096: "2096-04-15", 2097: "2097-03-31", 2098: "2098-04-20", 2099: "2099-04-12",
    2100: "2100-03-28",
}


@dataclass(frozen=True)
class HolidayDef:
    """One holiday, locale-agnostic.

    ``kind="fixed"``: ``month``/``day`` give the calendar date.
    ``kind="easter"``: ``easter_offset`` is days from Easter Sunday
    (e.g. Good Friday = -2, Easter Monday = +1).
    """

    country: str
    name_key: str
    kind: str
    month: int | None = None
    day: int | None = None
    easter_offset: int | None = None
    effective_from: int | None = None  # year (inclusive); None = unbounded past
    effective_to: int | None = None  # year (inclusive); None = ongoing


# Country weekend days, JS/FullCalendar convention 0=Sun..6=Sat.
WEEKEND_DAYS: dict[str, frozenset[int]] = {
    "CZ": frozenset({0, 6}),  # Sunday, Saturday
}


_HOLIDAY_DEFS: list[HolidayDef] = [
    # --- Czechia ---
    # Fixed-date holidays (validity ranges leave room for future adds/removals).
    HolidayDef("CZ", "holiday.cz.new_year", "fixed", month=1, day=1),
    # Good Friday became a CZ public holiday in 2016.
    HolidayDef(
        "CZ", "holiday.cz.good_friday", "easter", easter_offset=-2, effective_from=2016
    ),
    HolidayDef("CZ", "holiday.cz.easter_monday", "easter", easter_offset=1),
    HolidayDef("CZ", "holiday.cz.labour_day", "fixed", month=5, day=1),
    HolidayDef("CZ", "holiday.cz.liberation", "fixed", month=5, day=8),
    HolidayDef("CZ", "holiday.cz.ss_cyril_methodius", "fixed", month=7, day=5),
    HolidayDef("CZ", "holiday.cz.jan_hus", "fixed", month=7, day=6),
    HolidayDef("CZ", "holiday.cz.st_wenceslas", "fixed", month=9, day=28),
    HolidayDef("CZ", "holiday.cz.independence", "fixed", month=10, day=28),
    HolidayDef("CZ", "holiday.cz.velvet", "fixed", month=11, day=17),
    HolidayDef("CZ", "holiday.cz.christmas_eve", "fixed", month=12, day=24),
    HolidayDef("CZ", "holiday.cz.christmas", "fixed", month=12, day=25),
    HolidayDef("CZ", "holiday.cz.boxing_day", "fixed", month=12, day=26),
]

# Label key for weekend days (not a real holiday, but colored the same way).
WEEKEND_NAME_KEY = "holiday.weekend"


def weekend_days(country: str) -> frozenset[int]:
    """Return the set of weekend weekday numbers (0=Sun..6=Sat) for ``country``."""
    return WEEKEND_DAYS.get(country, frozenset())


def _applicable(country: str, year: int) -> list[HolidayDef]:
    out: list[HolidayDef] = []
    for d in _HOLIDAY_DEFS:
        if d.country != country:
            continue
        if d.effective_from is not None and year < d.effective_from:
            continue
        if d.effective_to is not None and year > d.effective_to:
            continue
        out.append(d)
    return out


def holidays_for_year(country: str, year: int) -> list[tuple[str, str]]:
    """Resolve all holidays in force for ``(country, year)`` to concrete dates.

    Fixed and Easter-based holidays are merged into one flat list — after
    resolution Easter is indistinguishable from fixed dates (no special-case
    branch downstream). Returns ``[(date_iso, name_key), ...]`` sorted by date.
    """
    out: list[tuple[str, str]] = []
    for d in _applicable(country, year):
        if d.kind == "fixed":
            if d.month is None or d.day is None:
                continue
            iso = f"{year:04d}-{d.month:02d}-{d.day:02d}"
        elif d.kind == "easter":
            sun = EASTER_SUNDAY.get(year)
            if sun is None or d.easter_offset is None:
                continue  # outside the hardcoded table range — skip silently
            iso = (date.fromisoformat(sun) + timedelta(days=d.easter_offset)).isoformat()
        else:
            continue
        out.append((iso, d.name_key))
    out.sort(key=lambda x: x[0])
    return out


def holidays_for_range(country: str, start_iso: str, end_iso: str) -> dict[str, str]:
    """Return ``{date_iso: name_key}`` for all holidays in ``[start, end]``.

    Inclusive on both ends. Each date appears once; if two definitions ever
    resolve to the same date, the later one in iteration order wins (CZ has no
    such collisions today).
    """
    start = date.fromisoformat(start_iso)
    end = date.fromisoformat(end_iso)
    if end < start:
        return {}
    result: dict[str, str] = {}
    year = start.year
    while year <= end.year:
        for iso, key in holidays_for_year(country, year):
            d = date.fromisoformat(iso)
            if start <= d <= end:
                result[iso] = key
        year += 1
    return result
