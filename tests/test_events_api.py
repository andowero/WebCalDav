"""API-level tests for the events router additions (recurrence preview, scopes)."""
import pytest
from httpx import AsyncClient

from webcaldav.admin import _provision_user
from webcaldav.db import get_session_factory


async def _unrestricted(client: AsyncClient, email: str) -> None:
    """Provision a user and drive login -> change-password to an open session."""
    async with get_session_factory()() as db:
        await _provision_user(email, "initial-pw", db)
    await client.post("/auth/login", json={"email": email, "password": "initial-pw"})
    await client.post(
        "/auth/change-password",
        json={"old_password": "initial-pw", "new_password": "new-secure-password"},
    )


@pytest.mark.asyncio
async def test_recurrence_preview_count(client: AsyncClient, db_engine):
    await _unrestricted(client, "rp1@example.com")
    r = await client.post(
        "/events/recurrence-preview",
        json={
            "start": "2026-06-22T09:00:00+00:00",
            "all_day": False,
            "timezone": "UTC",
            "recurrence": {"freq": "weekly", "interval": 1, "count": 3},
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 3
    assert body["last"].startswith("2026-07-06")


@pytest.mark.asyncio
async def test_recurrence_preview_infinite(client: AsyncClient, db_engine):
    await _unrestricted(client, "rp2@example.com")
    r = await client.post(
        "/events/recurrence-preview",
        json={"start": "2026-06-22T09:00:00+00:00", "recurrence": {"freq": "daily"}},
    )
    assert r.status_code == 200
    assert r.json() == {"last": None, "count": None}


@pytest.mark.asyncio
async def test_recurrence_preview_requires_session(client: AsyncClient, db_engine):
    r = await client.post(
        "/events/recurrence-preview",
        json={"start": "2026-06-22T09:00:00+00:00", "recurrence": {"freq": "daily"}},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_put_invalid_scope_rejected(client: AsyncClient, db_engine):
    await _unrestricted(client, "rp3@example.com")
    # "thisprev" was dropped: only this / thisfuture / all are standard scopes.
    for scope in ("bogus", "thisprev"):
        r = await client.put(
            "/events/whatever@webcaldav",
            json={"calendar_id": 1, "title": "x", "start": "2026-06-22T09:00:00+00:00",
                  "end": "2026-06-22T10:00:00+00:00", "scope": scope},
        )
        assert r.status_code == 400


@pytest.mark.asyncio
async def test_reminders_validation(client: AsyncClient, db_engine):
    await _unrestricted(client, "rem1@example.com")
    base = {
        "calendar_id": 1,
        "title": "x",
        "start": "2026-06-22T09:00:00+00:00",
        "end": "2026-06-22T10:00:00+00:00",
    }
    bad_bodies = [
        # negative value
        {**base, "reminders": [{"value": -5, "unit": "minutes"}]},
        # unknown unit (months is not an RFC 5545 duration)
        {**base, "reminders": [{"value": 1, "unit": "months"}]},
        # more than 10 reminders
        {**base, "reminders": [{"value": i, "unit": "minutes"} for i in range(11)]},
        # timed event must not carry a time of day
        {**base, "reminders": [{"value": 15, "unit": "minutes", "time": "09:00"}]},
        # all-day reminders need days/weeks...
        {**base, "all_day": True, "start": "2026-06-22", "end": "2026-06-22",
         "reminders": [{"value": 15, "unit": "minutes", "time": "09:00"}]},
        # ...and a valid HH:MM time
        {**base, "all_day": True, "start": "2026-06-22", "end": "2026-06-22",
         "reminders": [{"value": 1, "unit": "days"}]},
        {**base, "all_day": True, "start": "2026-06-22", "end": "2026-06-22",
         "reminders": [{"value": 1, "unit": "days", "time": "25:00"}]},
    ]
    for body in bad_bodies:
        r = await client.post("/events", json=body)
        assert r.status_code == 422, body


def test_reminder_anchor_direction_defaults_and_validation():
    from webcaldav.routers.events import Reminder

    # Defaults reproduce the original "before start" behavior.
    r = Reminder(value=15, unit="minutes")
    assert r.anchor == "start"
    assert r.direction == "before"
    # Explicit quadrant accepted.
    r = Reminder(value=15, unit="minutes", anchor="end", direction="after")
    assert (r.anchor, r.direction) == ("end", "after")
    # Bad enum values rejected.
    for bad in ({"anchor": "middle"}, {"direction": "during"}):
        with pytest.raises(ValueError):
            Reminder(value=1, unit="minutes", **bad)
