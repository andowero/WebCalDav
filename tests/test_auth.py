import pytest
from httpx import AsyncClient
from sqlalchemy import select

from webcaldav.admin import _provision_user
from webcaldav.config import settings
from webcaldav.db import get_session_factory
from webcaldav.models import User


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
        json={"old_password": "wrong", "new_password": "new-secure-password"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_change_password_too_short(client: AsyncClient, db_engine):
    await _create_user("shorty@example.com", "pw")
    await client.post("/auth/login", json={"email": "shorty@example.com", "password": "pw"})
    r = await client.post(
        "/auth/change-password",
        json={"old_password": "pw", "new_password": "short"},
    )
    assert r.status_code == 400
    assert "12" in r.json()["detail"]


@pytest.mark.asyncio
async def test_mutating_request_without_csrf_header_rejected(client: AsyncClient, db_engine):
    r = await client.post(
        "/auth/login",
        json={"email": "x@example.com", "password": "x"},
        headers={"X-Requested-With": ""},
    )
    assert r.status_code == 403
    assert r.json()["detail"] == "Missing CSRF header"


@pytest.mark.asyncio
async def test_get_requests_need_no_csrf_header(client: AsyncClient, db_engine):
    r = await client.get("/health", headers={"X-Requested-With": ""})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_login_uses_per_user_kdf_params(client: AsyncClient, db_engine):
    """Hardening the global argon2 defaults must not lock out existing users."""
    from webcaldav.config import settings
    from webcaldav.models import User
    from sqlalchemy import select

    await _create_user("legacy@example.com", "pw")

    old = (settings.argon2_time_cost, settings.argon2_memory_cost)
    settings.argon2_time_cost, settings.argon2_memory_cost = 2, 2048
    try:
        r = await client.post(
            "/auth/login", json={"email": "legacy@example.com", "password": "pw"}
        )
        assert r.status_code == 200

        # Password change re-derives with the new params and stores them.
        r = await client.post(
            "/auth/change-password",
            json={"old_password": "pw", "new_password": "new-secure-password"},
        )
        assert r.status_code == 200
        async with get_session_factory()() as db:
            user = (
                await db.execute(select(User).where(User.email == "legacy@example.com"))
            ).scalar_one()
            assert user.kdf_time_cost == 2
            assert user.kdf_memory_cost == 2048

        r = await client.post(
            "/auth/login",
            json={"email": "legacy@example.com", "password": "new-secure-password"},
        )
        assert r.status_code == 200
    finally:
        settings.argon2_time_cost, settings.argon2_memory_cost = old


@pytest.mark.asyncio
async def test_kdf_columns_migration_for_old_schema():
    """create_tables() adds the kdf_* columns to a pre-existing users table."""
    from sqlalchemy import text

    from webcaldav.db import create_tables, init_engine

    engine = init_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "CREATE TABLE users ("
                    "id INTEGER PRIMARY KEY, email VARCHAR NOT NULL UNIQUE, "
                    "kdf_salt BLOB NOT NULL, wrapped_dek BLOB NOT NULL, "
                    "dek_nonce BLOB NOT NULL, password_verifier BLOB NOT NULL, "
                    "must_change_password BOOLEAN NOT NULL, created_at DATETIME NOT NULL)"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO users (email, kdf_salt, wrapped_dek, dek_nonce, "
                    "password_verifier, must_change_password, created_at) "
                    "VALUES ('old@example.com', x'00', x'00', x'00', x'00', 1, '2025-01-01')"
                )
            )
        await create_tables()
        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT kdf_time_cost, kdf_memory_cost, kdf_parallelism "
                        "FROM users WHERE email = 'old@example.com'"
                    )
                )
            ).one()
        assert tuple(row) == (3, 65536, 1)
    finally:
        await engine.dispose()


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


@pytest.mark.asyncio
async def test_header_auth_disabled_ignores_header(client: AsyncClient, db_engine):
    old = (
        settings.header_authentication,
        settings.header_auth_secret,
        settings.header_auth_header_name,
    )
    settings.header_authentication = False
    settings.header_auth_secret = None
    settings.header_auth_header_name = "Remote-User"
    try:
        r = await client.get("/", headers={"Remote-User": "proxy-user@example.com"})
        assert r.status_code == 200
        assert "session_id" not in r.cookies
        r = await client.get("/settings")
        assert r.status_code == 401
    finally:
        (
            settings.header_authentication,
            settings.header_auth_secret,
            settings.header_auth_header_name,
        ) = old


@pytest.mark.asyncio
async def test_header_auth_enabled_missing_header_no_session(client: AsyncClient, db_engine):
    old = (
        settings.header_authentication,
        settings.header_auth_secret,
        settings.header_auth_header_name,
    )
    settings.header_authentication = True
    settings.header_auth_secret = "secret-for-tests"
    settings.header_auth_header_name = "Remote-User"
    try:
        r = await client.get("/")
        assert r.status_code == 200
        assert "session_id" not in r.cookies
        r = await client.get("/settings")
        assert r.status_code == 401
    finally:
        (
            settings.header_authentication,
            settings.header_auth_secret,
            settings.header_auth_header_name,
        ) = old


@pytest.mark.asyncio
async def test_header_auth_autoprovisions_and_authenticates(client: AsyncClient, db_engine):
    old = (
        settings.header_authentication,
        settings.header_auth_secret,
        settings.header_auth_header_name,
    )
    settings.header_authentication = True
    settings.header_auth_secret = "secret-for-tests"
    settings.header_auth_header_name = "Remote-User"
    try:
        email = "header-new@example.com"
        r = await client.get("/", headers={"Remote-User": email})
        assert r.status_code == 200
        assert "session_id" in r.cookies

        async with get_session_factory()() as db:
            user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
            assert user is not None
            assert user.must_change_password is False

        r = await client.get("/settings")
        assert r.status_code == 200
    finally:
        (
            settings.header_authentication,
            settings.header_auth_secret,
            settings.header_auth_header_name,
        ) = old


@pytest.mark.asyncio
async def test_header_auth_existing_user_works(client: AsyncClient, db_engine):
    old = (
        settings.header_authentication,
        settings.header_auth_secret,
        settings.header_auth_header_name,
    )
    settings.header_authentication = True
    settings.header_auth_secret = "secret-for-tests"
    settings.header_auth_header_name = "Remote-User"
    try:
        email = "header-existing@example.com"
        r = await client.get("/", headers={"Remote-User": email})
        assert r.status_code == 200
        assert "session_id" in r.cookies

        r = await client.post("/auth/logout")
        assert r.status_code == 200

        r = await client.post("/auth/header-login", headers={"Remote-User": email})
        assert r.status_code == 200
        assert "session_id" in r.cookies

        r = await client.get("/settings")
        assert r.status_code == 200
    finally:
        (
            settings.header_authentication,
            settings.header_auth_secret,
            settings.header_auth_header_name,
        ) = old


@pytest.mark.asyncio
async def test_header_auth_rejects_incompatible_password_user(client: AsyncClient, db_engine):
    old = (
        settings.header_authentication,
        settings.header_auth_secret,
        settings.header_auth_header_name,
    )
    settings.header_authentication = True
    settings.header_auth_secret = "secret-for-tests"
    settings.header_auth_header_name = "Remote-User"
    try:
        email = "legacy-password@example.com"
        await _create_user(email, "password-mode-user")
        r = await client.post("/auth/header-login", headers={"Remote-User": email})
        assert r.status_code == 409
        assert "cannot be auto-authenticated" in r.json()["detail"]
    finally:
        (
            settings.header_authentication,
            settings.header_auth_secret,
            settings.header_auth_header_name,
        ) = old
