"""API tests for the /holidays endpoint and the holidays settings roundtrip."""

import pytest
from httpx import AsyncClient

from webcaldav.admin import _provision_user
from webcaldav.db import get_session_factory


async def _login_unrestricted(client: AsyncClient, email: str) -> None:
    async with get_session_factory()() as db:
        await _provision_user(email, "initial", db)
    await client.post("/auth/login", json={"email": email, "password": "initial"})
    await client.post(
        "/auth/change-password",
        json={"old_password": "initial", "new_password": "new-secure-password"},
    )


@pytest.mark.asyncio
async def test_holidays_disabled_by_default(client: AsyncClient, db_engine):
    await _login_unrestricted(client, "hol1@example.com")
    r = await client.get("/holidays", params={"from": "2024-12-24", "to": "2024-12-26"})
    assert r.status_code == 200
    assert r.json() == {"days": []}


@pytest.mark.asyncio
async def test_holidays_requires_session(client: AsyncClient, db_engine):
    # No login -> 401 (the session dependency rejects before reaching the handler).
    r = await client.get("/holidays", params={"from": "2024-12-24", "to": "2024-12-26"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_holidays_cz_range(client: AsyncClient, db_engine):
    await _login_unrestricted(client, "hol2@example.com")
    await client.put("/settings", json={"holidays_enabled": True, "holidays_country": "CZ"})
    r = await client.get(
        "/holidays", params={"from": "2024-12-24", "to": "2024-12-26"}
    )
    assert r.status_code == 200
    days = r.json()["days"]
    # 24th, 25th, 26th are all CZ holidays; no weekend in this slice.
    assert [d["date"] for d in days] == ["2024-12-24", "2024-12-25", "2024-12-26"]
    assert all(d["kind"] == "holiday" for d in days)
    assert days[0]["name_key"] == "holiday.cz.christmas_eve"


@pytest.mark.asyncio
async def test_holidays_marks_weekend(client: AsyncClient, db_engine):
    await _login_unrestricted(client, "hol3@example.com")
    await client.put("/settings", json={"holidays_enabled": True, "holidays_country": "CZ"})
    # 2024-12-21 (Sat) and 2024-12-22 (Sun): both weekend, no holiday.
    r = await client.get(
        "/holidays", params={"from": "2024-12-21", "to": "2024-12-22"}
    )
    assert r.status_code == 200
    days = r.json()["days"]
    assert [d["date"] for d in days] == ["2024-12-21", "2024-12-22"]
    assert all(d["kind"] == "weekend" for d in days)
    assert all(d["name_key"] == "holiday.weekend" for d in days)


@pytest.mark.asyncio
async def test_holidays_holiday_takes_precedence_over_weekend(client: AsyncClient, db_engine):
    await _login_unrestricted(client, "hol4@example.com")
    await client.put("/settings", json={"holidays_enabled": True, "holidays_country": "CZ"})
    # 2024-01-01 is a Monday holiday (New Year) — not a weekend, but confirms
    # a holiday is returned as kind=holiday. 2024-05-01 (Labour Day) is a Wed.
    r = await client.get("/holidays", params={"from": "2024-01-01", "to": "2024-01-01"})
    days = r.json()["days"]
    assert len(days) == 1
    assert days[0]["kind"] == "holiday"
    assert days[0]["name_key"] == "holiday.cz.new_year"


@pytest.mark.asyncio
async def test_holidays_country_none_yields_empty(client: AsyncClient, db_engine):
    await _login_unrestricted(client, "hol5@example.com")
    await client.put(
        "/settings", json={"holidays_enabled": True, "holidays_country": "none"}
    )
    r = await client.get("/holidays", params={"from": "2024-12-24", "to": "2024-12-26"})
    assert r.status_code == 200
    assert r.json() == {"days": []}


@pytest.mark.asyncio
async def test_holidays_invalid_date_returns_empty(client: AsyncClient, db_engine):
    await _login_unrestricted(client, "hol6@example.com")
    await client.put("/settings", json={"holidays_enabled": True, "holidays_country": "CZ"})
    r = await client.get("/holidays", params={"from": "not-a-date", "to": "2024-12-26"})
    assert r.status_code == 200
    assert r.json() == {"days": []}


@pytest.mark.asyncio
async def test_holidays_good_friday_absent_in_2015(client: AsyncClient, db_engine):
    await _login_unrestricted(client, "hol7@example.com")
    await client.put("/settings", json={"holidays_enabled": True, "holidays_country": "CZ"})
    # Good Friday 2015 would have been 2015-04-03 (Easter Sunday 2015-04-05).
    r = await client.get("/holidays", params={"from": "2015-04-03", "to": "2015-04-03"})
    assert r.status_code == 200
    assert r.json()["days"] == []


@pytest.mark.asyncio
async def test_holidays_settings_roundtrip(client: AsyncClient, db_engine):
    await _login_unrestricted(client, "hol8@example.com")
    r = await client.put(
        "/settings", json={"holidays_enabled": True, "holidays_country": "CZ"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["holidays_enabled"] is True
    assert body["holidays_country"] == "CZ"
    r = await client.get("/settings")
    assert r.json()["holidays_enabled"] is True
    assert r.json()["holidays_country"] == "CZ"


@pytest.mark.asyncio
async def test_holidays_country_rejects_invalid(client: AsyncClient, db_engine):
    await _login_unrestricted(client, "hol9@example.com")
    r = await client.put("/settings", json={"holidays_country": "DE"})
    assert r.status_code == 422
