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
    r = await client.put(
        "/events/whatever@webcaldav",
        json={"calendar_id": 1, "title": "x", "start": "2026-06-22T09:00:00+00:00",
              "end": "2026-06-22T10:00:00+00:00", "scope": "bogus"},
    )
    assert r.status_code == 400
