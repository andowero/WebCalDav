"""API-level tests for the tasks router and the task display settings."""
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
async def test_task_reminders_validation(client: AsyncClient, db_engine):
    await _unrestricted(client, "tk-rem@example.com")
    base = {"calendar_id": 1, "title": "x", "due": "2026-06-22T10:00:00+00:00"}
    bad_bodies = [
        {**base, "reminders": [{"value": -5, "unit": "minutes"}]},
        {**base, "reminders": [{"value": 1, "unit": "months"}]},
        {**base, "reminders": [{"value": i, "unit": "minutes"} for i in range(11)]},
        {**base, "reminders": [{"value": 15, "unit": "minutes", "time": "09:00"}]},
        {**base, "all_day": True, "due": "2026-06-22",
         "reminders": [{"value": 1, "unit": "days"}]},
        {**base, "priority": 99},  # priority out of 0..9
    ]
    for body in bad_bodies:
        r = await client.post("/tasks", json=body)
        assert r.status_code == 422, body


@pytest.mark.asyncio
async def test_task_put_invalid_scope_rejected(client: AsyncClient, db_engine):
    await _unrestricted(client, "tk-scope@example.com")
    r = await client.put(
        "/tasks/whatever@webcaldav",
        json={"calendar_id": 1, "title": "x", "scope": "bogus"},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_task_recurrence_needs_a_date(client: AsyncClient, db_engine):
    await _unrestricted(client, "tk-recur@example.com")
    # Recurring task with neither start nor due -> 422 (model validator).
    r = await client.post(
        "/tasks",
        json={"calendar_id": 1, "title": "x",
              "recurrence": {"freq": "weekly", "interval": 1, "count": 3}},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_tasks_requires_session(client: AsyncClient, db_engine):
    r = await client.get("/tasks")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_settings_task_fields_roundtrip(client: AsyncClient, db_engine):
    await _unrestricted(client, "tk-set@example.com")
    # Defaults.
    r = await client.get("/settings")
    body = r.json()
    assert body["completed_task_display"] == "hidden"
    assert body["undated_task_display"] == "agenda"
    # Update.
    r = await client.put(
        "/settings",
        json={"completed_task_display": "grayed", "undated_task_display": "today"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["completed_task_display"] == "grayed"
    assert body["undated_task_display"] == "today"
    # Persisted.
    assert (await client.get("/settings")).json()["completed_task_display"] == "grayed"


@pytest.mark.asyncio
async def test_settings_task_fields_validation(client: AsyncClient, db_engine):
    await _unrestricted(client, "tk-setbad@example.com")
    for bad in (
        {"completed_task_display": "sparkle"},
        {"undated_task_display": "yesterday"},
    ):
        r = await client.put("/settings", json=bad)
        assert r.status_code == 422, bad


def test_task_update_model_allows_undated():
    from webcaldav.routers.tasks import TaskUpdate

    t = TaskUpdate(calendar_id=1, title="x")
    assert t.start is None and t.due is None
    assert t.scope == "all"
