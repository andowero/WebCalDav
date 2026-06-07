import pytest
from httpx import AsyncClient

from webcaldav.admin import _provision_user
from webcaldav.db import get_session_factory


async def _create_user(email: str, password: str) -> None:
    async with get_session_factory()() as db:
        await _provision_user(email, password, db)


async def _login_unrestricted(client: AsyncClient, email: str, pw: str) -> None:
    await _create_user(email, pw)
    await client.post("/auth/login", json={"email": email, "password": pw})
    await client.post(
        "/auth/change-password",
        json={"old_password": pw, "new_password": "new-secure-password"},
    )


@pytest.mark.asyncio
async def test_settings_default_auto_logout(client: AsyncClient, db_engine):
    await _login_unrestricted(client, "al@example.com", "pw")
    r = await client.get("/settings")
    assert r.status_code == 200
    body = r.json()
    assert body["auto_logout_enabled"] is True
    assert body["auto_logout_timeout_seconds"] == 3600


@pytest.mark.asyncio
async def test_settings_persist_auto_logout(client: AsyncClient, db_engine):
    await _login_unrestricted(client, "be@example.com", "pw")
    r = await client.put(
        "/settings",
        json={"auto_logout_enabled": False, "auto_logout_timeout_seconds": 600},
    )
    assert r.status_code == 200
    assert r.json()["auto_logout_enabled"] is False
    r = await client.get("/settings")
    assert r.json()["auto_logout_enabled"] is False
    assert r.json()["auto_logout_timeout_seconds"] == 600


@pytest.mark.asyncio
async def test_settings_rejects_short_timeout(client: AsyncClient, db_engine):
    await _login_unrestricted(client, "ce@example.com", "pw")
    r = await client.put("/settings", json={"auto_logout_timeout_seconds": 5})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_session_endpoint_enabled(client: AsyncClient, db_engine):
    await _login_unrestricted(client, "de@example.com", "pw")
    r = await client.get("/auth/session")
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True
    assert body["timeout_seconds"] == 3600
    assert 0 < body["remaining_seconds"] <= 3600


@pytest.mark.asyncio
async def test_session_endpoint_disabled_after_update(client: AsyncClient, db_engine):
    await _login_unrestricted(client, "ee@example.com", "pw")
    await client.put("/settings", json={"auto_logout_enabled": False})
    r = await client.get("/auth/session")
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is False
    assert body["remaining_seconds"] is None


@pytest.mark.asyncio
async def test_session_endpoint_no_session(client: AsyncClient, db_engine):
    r = await client.get("/auth/session")
    assert r.status_code == 401
