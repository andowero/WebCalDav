import pytest
from httpx import AsyncClient

from webcaldav.admin import _provision_user
from webcaldav.db import get_session_factory


async def _create_user(email: str, password: str) -> None:
    async with get_session_factory()() as db:
        await _provision_user(email, password, db)


async def _login_unrestricted(client: AsyncClient, email: str) -> None:
    """Create + log in a user and clear the forced first-login restriction."""
    await _create_user(email, "initial")
    await client.post("/auth/login", json={"email": email, "password": "initial"})
    await client.post(
        "/auth/change-password",
        json={"old_password": "initial", "new_password": "new-secure-password"},
    )


@pytest.mark.asyncio
async def test_default_view_defaults_to_month(client: AsyncClient, db_engine):
    await _login_unrestricted(client, "dv1@example.com")
    r = await client.get("/settings")
    assert r.status_code == 200
    assert r.json()["default_view"] == "dayGridMonth"


@pytest.mark.asyncio
async def test_default_view_roundtrip(client: AsyncClient, db_engine):
    await _login_unrestricted(client, "dv2@example.com")
    r = await client.put("/settings", json={"default_view": "agenda"})
    assert r.status_code == 200
    assert r.json()["default_view"] == "agenda"
    # Persisted across a fresh read.
    r = await client.get("/settings")
    assert r.json()["default_view"] == "agenda"


@pytest.mark.asyncio
async def test_default_view_rejects_invalid(client: AsyncClient, db_engine):
    await _login_unrestricted(client, "dv3@example.com")
    r = await client.put("/settings", json={"default_view": "bogusView"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_dblclick_create_default_off(client: AsyncClient, db_engine):
    await _login_unrestricted(client, "dc1@example.com")
    r = await client.get("/settings")
    assert r.status_code == 200
    assert r.json()["double_click_to_create_events"] is False


@pytest.mark.asyncio
async def test_dblclick_create_roundtrip(client: AsyncClient, db_engine):
    await _login_unrestricted(client, "dc2@example.com")
    r = await client.put("/settings", json={"double_click_to_create_events": True})
    assert r.status_code == 200
    assert r.json()["double_click_to_create_events"] is True
    r = await client.get("/settings")
    assert r.json()["double_click_to_create_events"] is True


@pytest.mark.asyncio
async def test_notifications_default_off(client: AsyncClient, db_engine):
    await _login_unrestricted(client, "nt1@example.com")
    r = await client.get("/settings")
    assert r.status_code == 200
    assert r.json()["notifications_enabled"] is False


@pytest.mark.asyncio
async def test_notifications_roundtrip(client: AsyncClient, db_engine):
    await _login_unrestricted(client, "nt2@example.com")
    r = await client.put("/settings", json={"notifications_enabled": True})
    assert r.status_code == 200
    assert r.json()["notifications_enabled"] is True
    r = await client.get("/settings")
    assert r.json()["notifications_enabled"] is True


@pytest.mark.asyncio
async def test_enabling_notifications_forces_auto_logout_off(client: AsyncClient, db_engine):
    """Notifications need the tab logged in to keep resyncing, so the server
    forces auto-logout off whenever notifications are enabled — even if the same
    request tries to turn auto-logout on."""
    await _login_unrestricted(client, "nt3@example.com")
    r = await client.put(
        "/settings",
        json={"notifications_enabled": True, "auto_logout_enabled": True},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["notifications_enabled"] is True
    assert body["auto_logout_enabled"] is False


@pytest.mark.asyncio
async def test_theme_defaults_to_system(client: AsyncClient, db_engine):
    await _login_unrestricted(client, "th1@example.com")
    r = await client.get("/settings")
    assert r.status_code == 200
    assert r.json()["theme"] == "system"


@pytest.mark.asyncio
async def test_theme_roundtrip(client: AsyncClient, db_engine):
    await _login_unrestricted(client, "th2@example.com")
    r = await client.put("/settings", json={"theme": "dark"})
    assert r.status_code == 200
    assert r.json()["theme"] == "dark"
    # Persisted across a fresh read.
    r = await client.get("/settings")
    assert r.json()["theme"] == "dark"


@pytest.mark.asyncio
async def test_theme_rejects_invalid(client: AsyncClient, db_engine):
    await _login_unrestricted(client, "th3@example.com")
    r = await client.put("/settings", json={"theme": "neon"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_language_defaults_to_autodetect(client: AsyncClient, db_engine):
    await _login_unrestricted(client, "lng1@example.com")
    r = await client.get("/settings")
    assert r.status_code == 200
    assert r.json()["language"] == "autodetect"


@pytest.mark.asyncio
async def test_language_roundtrip(client: AsyncClient, db_engine):
    await _login_unrestricted(client, "lng2@example.com")
    r = await client.put("/settings", json={"language": "czech"})
    assert r.status_code == 200
    assert r.json()["language"] == "czech"
    # Persisted across a fresh read.
    r = await client.get("/settings")
    assert r.json()["language"] == "czech"


@pytest.mark.asyncio
async def test_language_rejects_invalid(client: AsyncClient, db_engine):
    await _login_unrestricted(client, "lng3@example.com")
    r = await client.put("/settings", json={"language": "klingon"})
    assert r.status_code == 422
