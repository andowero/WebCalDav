from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select

import webcaldav.mcp_server as mcp_server
from webcaldav import tokens as tok
from webcaldav.admin import _provision_user, _reset_user
from webcaldav.config import settings as cfg
from webcaldav.crypto import encrypt_bytes, generate_dek
from webcaldav.db import get_session_factory
from webcaldav.models import APIToken, APITokenCalendar, CalDAVAccount, Calendar, User
from webcaldav.mcp_server import ToolError, TokenContext, _current
from webcaldav.tokens import resolve_token


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
async def _create_user(email: str, password: str = "initial") -> int:
    async with get_session_factory()() as db:
        user = await _provision_user(email, password, db)
        return user.id


async def _login_unrestricted(client: AsyncClient, email: str) -> None:
    await _create_user(email)
    await client.post("/auth/login", json={"email": email, "password": "initial"})
    await client.post(
        "/auth/change-password",
        json={"old_password": "initial", "new_password": "new-secure-password"},
    )


async def _add_account_with_calendars(user_id: int, dek: bytes, n: int = 2) -> list[int]:
    """Insert a CalDAV account (password encrypted with ``dek``) and ``n``
    calendars directly, returning the calendar ids."""
    async with get_session_factory()() as db:
        ct, nonce = encrypt_bytes(b"secret-pw", dek)
        acct = CalDAVAccount(
            user_id=user_id, url="https://dav.example.com", username="u",
            encrypted_password=ct, nonce=nonce,
        )
        db.add(acct)
        await db.flush()
        ids = []
        for i in range(n):
            cal = Calendar(
                caldav_account_id=acct.id, caldav_id=f"cal-{i}",
                display_name=f"Cal {i}", color="#3788d8", enabled=True,
            )
            db.add(cal)
            await db.flush()
            ids.append(cal.id)
        await db.commit()
        return ids


@pytest.fixture()
def mcp_on(monkeypatch):
    monkeypatch.setattr(cfg, "mcp_server_enabled", True)
    yield


@pytest.fixture()
def mcp_off(monkeypatch):
    # Force-disabled regardless of any .env / env override on the host.
    monkeypatch.setattr(cfg, "mcp_server_enabled", False)
    yield


# --------------------------------------------------------------------------- #
# Token core: mint / resolve
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_mint_token_prefix_and_mode():
    dek = generate_dek()
    full, sha, blob, nonce = tok.mint_token(dek, "rw", True, None, None)
    assert full.startswith("WebCalDavRW")
    assert len(sha) == 32
    ro, _, _, _ = tok.mint_token(dek, "ro", True, None, None)
    assert ro.startswith("WebCalDavRO")


@pytest.mark.asyncio
async def test_resolve_roundtrip(db_engine):
    uid = await _create_user("mcp-resolve@example.com")
    dek = generate_dek()
    full, sha, blob, nonce = tok.mint_token(dek, "rw", False, [3, 1, 2], None)
    async with get_session_factory()() as db:
        db.add(APIToken(
            user_id=uid, name="t", token_sha256=sha, sealed_blob=blob,
            blob_nonce=nonce, mode="rw", all_calendars=False,
        ))
        await db.commit()
    async with get_session_factory()() as db:
        ctx = await resolve_token(full, db)
    assert ctx is not None
    assert ctx.user_id == uid
    assert ctx.dek == dek
    assert ctx.mode == "rw"
    assert ctx.all_calendars is False
    assert ctx.calendar_ids == [1, 2, 3]  # sorted in the sealed blob


@pytest.mark.asyncio
async def test_resolve_rejects_unknown_and_malformed(db_engine):
    async with get_session_factory()() as db:
        assert await resolve_token("not-a-token", db) is None
        assert await resolve_token("WebCalDavRWdeadbeef", db) is None


@pytest.mark.asyncio
async def test_resolve_rejects_expired(db_engine):
    uid = await _create_user("mcp-exp@example.com")
    dek = generate_dek()
    past = datetime.now(UTC) - timedelta(days=1)
    full, sha, blob, nonce = tok.mint_token(dek, "ro", True, None, past)
    async with get_session_factory()() as db:
        db.add(APIToken(
            user_id=uid, name="t", token_sha256=sha, sealed_blob=blob,
            blob_nonce=nonce, mode="ro", all_calendars=True, expires_at=past,
        ))
        await db.commit()
    async with get_session_factory()() as db:
        assert await resolve_token(full, db) is None


# --------------------------------------------------------------------------- #
# API: create / list / revoke / toggle gating
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_create_requires_mcp_enabled(client: AsyncClient, db_engine, mcp_off):
    await _login_unrestricted(client, "mcp-disabled@example.com")
    r = await client.post("/api-tokens", json={"name": "t", "mode": "rw"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_create_list_revoke(client: AsyncClient, db_engine, mcp_on):
    await _login_unrestricted(client, "mcp-crud@example.com")
    r = await client.post("/api-tokens", json={"name": "laptop", "mode": "ro"})
    assert r.status_code == 200
    body = r.json()
    assert body["token"].startswith("WebCalDavRO")
    # Listing returns metadata but never the secret.
    r = await client.get("/api-tokens")
    items = r.json()
    assert len(items) == 1
    assert "token" not in items[0]
    assert "token_sha256" not in items[0]
    assert items[0]["mode"] == "ro"
    tid = items[0]["id"]
    # Revoke works.
    r = await client.delete(f"/api-tokens/{tid}")
    assert r.status_code == 200
    r = await client.get("/api-tokens")
    assert r.json() == []


@pytest.mark.asyncio
async def test_revoke_works_when_mcp_disabled(client: AsyncClient, db_engine, monkeypatch):
    await _login_unrestricted(client, "mcp-revoke@example.com")
    # Create while enabled, revoke while disabled.
    monkeypatch.setattr(cfg, "mcp_server_enabled", True)
    r = await client.post("/api-tokens", json={"name": "t", "mode": "ro"})
    tid = r.json()["info"]["id"]
    monkeypatch.setattr(cfg, "mcp_server_enabled", False)
    r = await client.delete(f"/api-tokens/{tid}")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_scoped_token_persists_calendars(client: AsyncClient, db_engine, mcp_on):
    await _login_unrestricted(client, "mcp-scope@example.com")
    async with get_session_factory()() as db:
        uid = (await db.execute(select(User.id))).scalar_one()
    cal_ids = await _add_account_with_calendars(uid, generate_dek(), n=2)
    r = await client.post("/api-tokens", json={
        "name": "scoped", "mode": "rw", "all_calendars": False,
        "calendar_ids": [cal_ids[0]],
    })
    assert r.status_code == 200
    items = (await client.get("/api-tokens")).json()
    assert items[0]["all_calendars"] is False
    assert items[0]["calendar_ids"] == [cal_ids[0]]


@pytest.mark.asyncio
async def test_create_rejects_foreign_calendar(client: AsyncClient, db_engine, mcp_on):
    await _login_unrestricted(client, "mcp-foreign@example.com")
    r = await client.post("/api-tokens", json={
        "name": "x", "mode": "rw", "all_calendars": False, "calendar_ids": [99999],
    })
    assert r.status_code == 400


# --------------------------------------------------------------------------- #
# Scope tamper: DB edits cannot escalate
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_db_tamper_cannot_escalate(client: AsyncClient, db_engine, mcp_on):
    await _login_unrestricted(client, "mcp-tamper@example.com")
    async with get_session_factory()() as db:
        uid = (await db.execute(select(User.id))).scalar_one()
    cal_ids = await _add_account_with_calendars(uid, generate_dek(), n=2)
    r = await client.post("/api-tokens", json={
        "name": "ro-scoped", "mode": "ro", "all_calendars": False,
        "calendar_ids": [cal_ids[0]],
    })
    full = r.json()["token"]
    tid = r.json()["info"]["id"]

    # Tamper the plaintext mirror: flip to rw, all calendars, add the other cal.
    async with get_session_factory()() as db:
        token = (
            await db.execute(select(APIToken).where(APIToken.id == tid))
        ).scalar_one()
        token.mode = "rw"
        token.all_calendars = True
        db.add(APITokenCalendar(api_token_id=tid, calendar_id=cal_ids[1]))
        await db.commit()

    # Authoritative (sealed) scope/mode are unchanged.
    async with get_session_factory()() as db:
        ctx = await resolve_token(full, db)
    assert ctx is not None
    assert ctx.mode == "ro"
    assert ctx.all_calendars is False
    assert ctx.calendar_ids == [cal_ids[0]]


@pytest.mark.asyncio
async def test_prefix_mode_must_match_sealed(db_engine):
    uid = await _create_user("mcp-prefix@example.com")
    dek = generate_dek()
    full, sha, blob, nonce = tok.mint_token(dek, "ro", True, None, None)
    async with get_session_factory()() as db:
        db.add(APIToken(
            user_id=uid, name="t", token_sha256=sha, sealed_blob=blob,
            blob_nonce=nonce, mode="ro", all_calendars=True,
        ))
        await db.commit()
    # Forge an RW prefix over the same secret -> rejected (mode mismatch).
    forged = "WebCalDavRW" + full[len("WebCalDavRO"):]
    async with get_session_factory()() as db:
        assert await resolve_token(forged, db) is None


# --------------------------------------------------------------------------- #
# Tool-level RO/RW + scope enforcement (no CalDAV network needed)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_ro_token_rejects_write_tools():
    ctx = TokenContext(user_id=1, dek=b"0" * 32, mode="ro",
                       all_calendars=True, calendar_ids=None, token_id=1)
    reset = _current.set(ctx)
    try:
        with pytest.raises(ToolError):
            await mcp_server.set_task_done(uid="x", calendar_id=1, completed=True)
        with pytest.raises(ToolError):
            await mcp_server.delete_event_tool(uid="x", calendar_id=1)
        with pytest.raises(ToolError):
            await mcp_server.create_journal_tool(calendar_id=1, title="x", start="2026-06-18")
        with pytest.raises(ToolError):
            await mcp_server.delete_journal_tool(uid="x", calendar_id=1)
    finally:
        _current.reset(reset)


@pytest.mark.asyncio
async def test_list_journals_backward_default_window(db_engine, monkeypatch):
    """list_journals defaults to a backward window (30 days ago -> now), the
    reverse of list_items, and only queries in-scope calendars."""
    uid = await _create_user("mcp-journals@example.com")
    dek = generate_dek()
    cal_ids = await _add_account_with_calendars(uid, dek, n=2)

    seen: list[dict] = []

    async def fake_fetch_journals(**kwargs):
        seen.append(kwargs)
        return [{"id": f"j{kwargs['calendar_id']}",
                 "extendedProps": {"isJournal": True, "calendarId": kwargs["calendar_id"],
                                   "description": "# long body"}}]

    monkeypatch.setattr(mcp_server, "fetch_journals", fake_fetch_journals)

    ctx = TokenContext(user_id=uid, dek=dek, mode="ro", all_calendars=False,
                       calendar_ids=[cal_ids[0]], token_id=1)
    reset = _current.set(ctx)
    try:
        out = await mcp_server.list_journals()
    finally:
        _current.reset(reset)

    assert [k["calendar_id"] for k in seen] == [cal_ids[0]]
    assert len(out) == 1 and out[0]["extendedProps"]["isJournal"] is True
    # The listing omits the (potentially long) Markdown body.
    assert "description" not in out[0]["extendedProps"]
    # Default window points into the past.
    assert seen[0]["from_dt"] < seen[0]["to_dt"]
    assert (seen[0]["to_dt"] - seen[0]["from_dt"]) == timedelta(days=30)


@pytest.mark.asyncio
async def test_get_item_details_journal_returns_description(db_engine, monkeypatch):
    """get_item_details(item_type='journal') returns the full Markdown body that
    list_journals omits."""
    uid = await _create_user("mcp-journal-detail@example.com")
    dek = generate_dek()
    cal_ids = await _add_account_with_calendars(uid, dek, n=1)

    async def fake_fetch_journals(**kwargs):
        return [{"id": "jx", "title": "Log",
                 "extendedProps": {"isJournal": True, "calendarId": kwargs["calendar_id"],
                                   "description": "# full body"}}]

    monkeypatch.setattr(mcp_server, "fetch_journals", fake_fetch_journals)

    ctx = TokenContext(user_id=uid, dek=dek, mode="ro", all_calendars=True,
                       calendar_ids=None, token_id=1)
    reset = _current.set(ctx)
    try:
        out = await mcp_server.get_item_details(uid="jx", calendar_id=cal_ids[0], item_type="journal")
    finally:
        _current.reset(reset)
    assert out["extendedProps"]["description"] == "# full body"


@pytest.mark.asyncio
async def test_create_journal_tool_writes(db_engine, monkeypatch):
    uid = await _create_user("mcp-journal-create@example.com")
    dek = generate_dek()
    cal_ids = await _add_account_with_calendars(uid, dek, n=1)

    captured: dict = {}

    async def fake_create_journal(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(mcp_server, "create_journal", fake_create_journal)

    ctx = TokenContext(user_id=uid, dek=dek, mode="rw", all_calendars=True,
                       calendar_ids=None, token_id=1)
    reset = _current.set(ctx)
    try:
        out = await mcp_server.create_journal_tool(
            calendar_id=cal_ids[0], title="Log", start="2026-06-18",
            description="# notes",
        )
    finally:
        _current.reset(reset)
    assert out["status"] == "ok" and out["id"].endswith("@webcaldav")
    assert captured["title"] == "Log"
    assert captured["description"] == "# notes"
    # all_day defaults true -> stored as a date.
    assert str(captured["start"]) == "2026-06-18"


@pytest.mark.asyncio
async def test_list_calendars_respects_scope(db_engine):
    uid = await _create_user("mcp-listcal@example.com")
    dek = generate_dek()
    cal_ids = await _add_account_with_calendars(uid, dek, n=3)

    ctx = TokenContext(user_id=uid, dek=dek, mode="ro", all_calendars=False,
                       calendar_ids=[cal_ids[0], cal_ids[2]], token_id=1)
    reset = _current.set(ctx)
    try:
        out = await mcp_server.list_calendars()
    finally:
        _current.reset(reset)
    ids = sorted(c["calendar_id"] for c in out)
    assert ids == sorted([cal_ids[0], cal_ids[2]])
    assert all("name" in c and "account_url" in c for c in out)


def test_mcp_event_allday_end_is_inclusive():
    # Single-day all-day: iCal DTEND exclusive (next day) -> inclusive == start.
    single = mcp_server._mcp_event(
        {"allDay": True, "start": "2026-06-17", "end": "2026-06-18", "extendedProps": {}}
    )
    assert single["end"] == "2026-06-17"
    # Multi-day all-day: 17–19 inclusive (DTEND exclusive 2026-06-20).
    multi = mcp_server._mcp_event(
        {"allDay": True, "start": "2026-06-17", "end": "2026-06-20", "extendedProps": {}}
    )
    assert multi["end"] == "2026-06-19"
    # Timed event untouched.
    timed = {"allDay": False, "start": "2026-06-17T10:00:00", "end": "2026-06-17T11:00:00"}
    assert mcp_server._mcp_event(timed)["end"] == "2026-06-17T11:00:00"
    # All-day task untouched (its DUE is the day itself, not exclusive).
    task = {"allDay": True, "start": "2026-06-17", "end": "2026-06-17",
            "extendedProps": {"isTask": True}}
    assert mcp_server._mcp_event(task)["end"] == "2026-06-17"


@pytest.mark.asyncio
async def test_missing_token_rejected():
    reset = _current.set(None)
    try:
        with pytest.raises(ToolError):
            await mcp_server.list_items()
    finally:
        _current.reset(reset)


@pytest.mark.asyncio
async def test_scoped_token_filters_calendars(db_engine, monkeypatch):
    uid = await _create_user("mcp-filter@example.com")
    dek = generate_dek()
    cal_ids = await _add_account_with_calendars(uid, dek, n=2)

    seen: list[int] = []

    async def fake_fetch_events(**kwargs):
        seen.append(kwargs["calendar_id"])
        return [{"id": f"e{kwargs['calendar_id']}", "extendedProps": {"calendarId": kwargs["calendar_id"]}}]

    monkeypatch.setattr(mcp_server, "fetch_events", fake_fetch_events)

    ctx = TokenContext(user_id=uid, dek=dek, mode="ro", all_calendars=False,
                       calendar_ids=[cal_ids[0]], token_id=1)
    reset = _current.set(ctx)
    try:
        out = await mcp_server.list_items(item_type="events")
    finally:
        _current.reset(reset)
    # Only the in-scope calendar was queried.
    assert seen == [cal_ids[0]]
    assert len(out) == 1


# --------------------------------------------------------------------------- #
# Admin reset revokes tokens
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_reset_password_deletes_tokens(db_engine):
    uid = await _create_user("mcp-reset@example.com")
    dek = generate_dek()
    full, sha, blob, nonce = tok.mint_token(dek, "rw", True, None, None)
    async with get_session_factory()() as db:
        db.add(APIToken(
            user_id=uid, name="t", token_sha256=sha, sealed_blob=blob,
            blob_nonce=nonce, mode="rw", all_calendars=True,
        ))
        await db.commit()
    async with get_session_factory()() as db:
        pw = await _reset_user("mcp-reset@example.com", db)
    assert pw is not None
    async with get_session_factory()() as db:
        remaining = (
            await db.execute(select(APIToken).where(APIToken.user_id == uid))
        ).scalars().all()
    assert remaining == []
