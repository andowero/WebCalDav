import pytest
from httpx import AsyncClient

from webcaldav.admin import _provision_user
from webcaldav.db import get_session_factory


async def _create_user(email: str, password: str) -> None:
    async with get_session_factory()() as db:
        await _provision_user(email, password, db)


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient, db_engine):
    await _create_user("alice@example.com", "first-password")
    r = await client.post("/auth/login", json={"email": "alice@example.com", "password": "first-password"})
    assert r.status_code == 200
    assert r.json()["must_change_password"] is True
    assert "session_id" in r.cookies


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient, db_engine):
    await _create_user("bob@example.com", "correct")
    r = await client.post("/auth/login", json={"email": "bob@example.com", "password": "wrong"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_login_unknown_email(client: AsyncClient, db_engine):
    r = await client.post("/auth/login", json={"email": "nobody@example.com", "password": "x"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_restricted_session_blocks_protected_routes(client: AsyncClient, db_engine):
    await _create_user("carol@example.com", "pw")
    await client.post("/auth/login", json={"email": "carol@example.com", "password": "pw"})
    r = await client.get("/settings")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_no_session_returns_401(client: AsyncClient, db_engine):
    r = await client.get("/settings")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_first_login_change_password_flow(client: AsyncClient, db_engine):
    await _create_user("dave@example.com", "initial")
    await client.post("/auth/login", json={"email": "dave@example.com", "password": "initial"})

    # Restricted — settings blocked
    r = await client.get("/settings")
    assert r.status_code == 403

    # Change password
    r = await client.post(
        "/auth/change-password",
        json={"old_password": "initial", "new_password": "new-secure-password"},
    )
    assert r.status_code == 200

    # Now unrestricted
    r = await client.get("/settings")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_change_password_wrong_old_password(client: AsyncClient, db_engine):
    await _create_user("eve@example.com", "pw")
    await client.post("/auth/login", json={"email": "eve@example.com", "password": "pw"})
    r = await client.post(
        "/auth/change-password",
        json={"old_password": "wrong", "new_password": "new"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_logout_wipes_session(client: AsyncClient, db_engine):
    await _create_user("frank@example.com", "pw1")
    await client.post("/auth/login", json={"email": "frank@example.com", "password": "pw1"})
    r = await client.post("/auth/logout")
    assert r.status_code == 200
    r = await client.get("/settings")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_no_signup_endpoint(client: AsyncClient, db_engine):
    r = await client.post("/auth/signup", json={})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_events_returns_dummy_when_no_calendars(client: AsyncClient, db_engine):
    await _create_user("grace@example.com", "pw")
    await client.post("/auth/login", json={"email": "grace@example.com", "password": "pw"})
    await client.post(
        "/auth/change-password",
        json={"old_password": "pw", "new_password": "new-secure-password"},
    )
    r = await client.get("/events")
    assert r.status_code == 200
    events = r.json()
    assert isinstance(events, list)
    assert len(events) > 0
    titles = [e["title"] for e in events]
    assert any("Welcome" in t for t in titles)
