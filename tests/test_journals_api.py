"""API-level tests for the journals router (validation + auth boundaries)."""
import pytest
from httpx import AsyncClient

from webcaldav.admin import _provision_user
from webcaldav.db import get_session_factory


async def _unrestricted(client: AsyncClient, email: str) -> None:
    async with get_session_factory()() as db:
        await _provision_user(email, "initial-pw", db)
    await client.post("/auth/login", json={"email": email, "password": "initial-pw"})
    await client.post(
        "/auth/change-password",
        json={"old_password": "initial-pw", "new_password": "new-secure-password"},
    )


@pytest.mark.asyncio
async def test_journals_requires_session(client: AsyncClient, db_engine):
    assert (await client.get("/journals")).status_code == 401


@pytest.mark.asyncio
async def test_journal_post_unknown_calendar_404(client: AsyncClient, db_engine):
    await _unrestricted(client, "jr-cal@example.com")
    # Valid body, but calendar 1 doesn't belong to this user -> 404.
    r = await client.post(
        "/journals", json={"calendar_id": 1, "title": "x", "start": "2026-06-18"}
    )
    assert r.status_code == 404


def test_resolve_journal_start_parsing():
    from fastapi import HTTPException

    from webcaldav.routers.journals import JournalUpdate, _resolve_journal_start

    # all-day -> date
    d = _resolve_journal_start(JournalUpdate(calendar_id=1, title="x", start="2026-06-18"))
    assert str(d) == "2026-06-18"
    # timed -> tz-aware datetime stamped with the request timezone
    dt = _resolve_journal_start(JournalUpdate(
        calendar_id=1, title="x", start="2026-06-18T09:30:00",
        all_day=False, timezone="Europe/Prague",
    ))
    assert dt.tzinfo is not None and dt.hour == 9
    # garbage -> 400
    with pytest.raises(HTTPException) as exc:
        _resolve_journal_start(JournalUpdate(calendar_id=1, title="x", start="not-a-date"))
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_journal_start_required(client: AsyncClient, db_engine):
    await _unrestricted(client, "jr-nostart@example.com")
    r = await client.post("/journals", json={"calendar_id": 1, "title": "x"})
    assert r.status_code == 422  # start is required by the model


def test_journal_update_model_defaults():
    from webcaldav.routers.journals import JournalUpdate

    j = JournalUpdate(calendar_id=1, title="x", start="2026-06-18")
    assert j.all_day is True
    assert j.original_calendar_id is None
    assert j.description is None
