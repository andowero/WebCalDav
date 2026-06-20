"""HTTP tests for the sharing API: create/list/revoke (session-authed) and the
share-view resolve/items/write/export endpoints (X-Share-Secret authed).

CalDAV I/O is faked by monkeypatching the fetch/create functions in the share
and event router namespaces, so no live server is needed.
"""
import pytest
from httpx import AsyncClient

import webcaldav.routers.events as events_router
import webcaldav.routers.shares as shares_router
from webcaldav.admin import _provision_user
from webcaldav.config import settings as cfg
from webcaldav.crypto import encrypt_bytes
from webcaldav.db import get_session_factory
from webcaldav.models import CalDAVAccount, Calendar


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
async def _create_user(email: str) -> int:
    async with get_session_factory()() as db:
        user = await _provision_user(email, "initial", db)
        return user.id


async def _login(client: AsyncClient, store, email: str) -> tuple[int, bytes]:
    uid = await _create_user(email)
    await client.post("/auth/login", json={"email": email, "password": "initial"})
    await client.post(
        "/auth/change-password",
        json={"old_password": "initial", "new_password": "new-secure-password"},
    )
    sid = client.cookies.get("session_id")
    dek = store.get(sid).dek
    return uid, dek


async def _add_calendars(uid: int, dek: bytes, n: int = 2) -> list[int]:
    async with get_session_factory()() as db:
        ct, nonce = encrypt_bytes(b"secret-pw", dek)
        acct = CalDAVAccount(
            user_id=uid, url="https://dav.example.com", username="u",
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
def sharing_on(monkeypatch):
    monkeypatch.setattr(cfg, "sharing_enabled", True)
    yield


@pytest.fixture()
def sharing_off(monkeypatch):
    monkeypatch.setattr(cfg, "sharing_enabled", False)
    yield


def _secret(url: str) -> str:
    return url.split("#", 1)[1]


def _hdr(secret: str) -> dict[str, str]:
    return {"X-Share-Secret": secret}


# --------------------------------------------------------------------------- #
# Create / list / revoke
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_create_requires_sharing_enabled(client, db_engine, store, sharing_off):
    uid, dek = await _login(client, store, "s-off@example.com")
    ids = await _add_calendars(uid, dek)
    r = await client.post("/shares", json={
        "kind": "grid", "mode": "ro",
        "grid": {"grid_view": "dayGridMonth", "grid_anchor": "2026-06-15"},
        "calendars": [{"id": ids[0]}],
    })
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_create_grid_returns_fragment_url(client, db_engine, store, sharing_on):
    uid, dek = await _login(client, store, "s-grid@example.com")
    ids = await _add_calendars(uid, dek)
    r = await client.post("/shares", json={
        "kind": "grid", "mode": "rw",
        "grid": {"grid_view": "dayGridMonth", "grid_anchor": "2026-06-15"},
        "calendars": [{"id": ids[0], "writable": True}, {"id": ids[1]}],
        "default_calendar_id": ids[0],
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert "#" in body["url"]
    assert "/s/" in body["url"]
    assert body["info"]["kind"] == "grid"


@pytest.mark.asyncio
async def test_create_rejects_bad_inputs(client, db_engine, store, sharing_on):
    uid, dek = await _login(client, store, "s-bad@example.com")
    ids = await _add_calendars(uid, dek)
    base = {
        "kind": "grid", "mode": "rw",
        "grid": {"grid_view": "dayGridMonth", "grid_anchor": "2026-06-15"},
    }
    # Out-of-scope calendar id.
    r = await client.post("/shares", json={**base, "calendars": [{"id": 99999}]})
    assert r.status_code == 400
    # default not writable.
    r = await client.post("/shares", json={
        **base, "calendars": [{"id": ids[0], "writable": False}],
        "default_calendar_id": ids[0],
    })
    assert r.status_code == 400
    # past expiry.
    r = await client.post("/shares", json={
        **base, "calendars": [{"id": ids[0], "writable": True}],
        "expires_at": "2000-01-01T00:00:00+00:00",
    })
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_list_and_revoke(client, db_engine, store, sharing_on):
    uid, dek = await _login(client, store, "s-list@example.com")
    ids = await _add_calendars(uid, dek)
    r = await client.post("/shares", json={
        "kind": "grid", "mode": "ro",
        "grid": {"grid_view": "dayGridMonth", "grid_anchor": "2026-06-15"},
        "calendars": [{"id": ids[0]}],
    })
    url = r.json()["url"]
    secret = _secret(url)
    share_id = r.json()["info"]["id"]

    lst = await client.get("/shares")
    assert lst.status_code == 200
    assert any(s["id"] == share_id for s in lst.json())

    # Resolve works before revoke.
    res = await client.post("/shares/resolve", headers=_hdr(secret))
    assert res.status_code == 200

    rev = await client.delete(f"/shares/{share_id}")
    assert rev.status_code == 200

    # After revoke the secret no longer resolves.
    res = await client.post("/shares/resolve", headers=_hdr(secret))
    assert res.status_code == 401


# --------------------------------------------------------------------------- #
# Resolve auth
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_resolve_missing_and_invalid(client, db_engine, store, sharing_on):
    await _login(client, store, "s-auth@example.com")
    r = await client.post("/shares/resolve")
    assert r.status_code == 401
    r = await client.post("/shares/resolve", headers=_hdr("garbage"))
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_resolve_grid_returns_anchor_and_window(client, db_engine, store, sharing_on):
    uid, dek = await _login(client, store, "s-anchor@example.com")
    ids = await _add_calendars(uid, dek, n=1)
    r = await client.post("/shares", json={
        "kind": "grid", "mode": "ro",
        "grid": {"grid_view": "dayGridMonth", "grid_anchor": "2026-06-15"},
        "calendars": [{"id": ids[0]}],
    })
    secret = _secret(r.json()["url"])
    cfg = (await client.post("/shares/resolve", headers=_hdr(secret))).json()
    assert cfg["kind"] == "grid"
    assert cfg["grid_view"] == "dayGridMonth"
    assert cfg["grid_anchor"] == "2026-06-15"
    assert cfg["window_from"] is not None and cfg["window_to"] is not None
    assert cfg["calendars"][0]["id"] == ids[0]


@pytest.mark.asyncio
async def test_share_page_is_share_mode(client, db_engine, store, sharing_on):
    # The /s/{id} page reuses index.html in share mode (no separate share.js).
    r = await client.get("/s/1")
    assert r.status_code == 200
    assert "__SHARE_MODE__ = true" in r.text
    assert "/static/app.js" in r.text


# --------------------------------------------------------------------------- #
# Items read clamps to the sealed window
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_items_clamped_to_window(client, db_engine, store, sharing_on, monkeypatch):
    uid, dek = await _login(client, store, "s-items@example.com")
    ids = await _add_calendars(uid, dek, n=1)
    seen = {}

    async def fake_fetch_events(**kwargs):
        seen["from"] = kwargs["from_dt"]
        seen["to"] = kwargs["to_dt"]
        return [{"id": "e1", "extendedProps": {"calendarId": kwargs["calendar_id"]}}]

    async def empty(**kwargs):
        return []

    monkeypatch.setattr(shares_router, "fetch_events", fake_fetch_events)
    monkeypatch.setattr(shares_router, "fetch_tasks", empty)
    monkeypatch.setattr(shares_router, "fetch_journals", empty)

    r = await client.post("/shares", json={
        "kind": "grid", "mode": "ro",
        "grid": {"grid_view": "dayGridMonth", "grid_anchor": "2026-06-15"},
        "calendars": [{"id": ids[0]}],
    })
    secret = _secret(r.json()["url"])
    res = await client.get("/shares/items", headers=_hdr(secret))
    assert res.status_code == 200
    assert len(res.json()["events"]) == 1
    # The window is the sealed June grid, not a client-chosen range.
    assert (seen["to"] - seen["from"]).days == 42


# --------------------------------------------------------------------------- #
# Write scope enforcement
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_rw_write_scope(client, db_engine, store, sharing_on, monkeypatch):
    uid, dek = await _login(client, store, "s-write@example.com")
    ids = await _add_calendars(uid, dek, n=2)  # ids[0] writable, ids[1] read-only

    created = {}

    async def fake_create_event(**kwargs):
        created["uid"] = kwargs["uid"]

    monkeypatch.setattr(events_router, "create_event", fake_create_event)

    r = await client.post("/shares", json={
        "kind": "grid", "mode": "rw",
        "grid": {"grid_view": "dayGridMonth", "grid_anchor": "2026-06-15"},
        "calendars": [{"id": ids[0], "writable": True}, {"id": ids[1], "writable": False}],
        "default_calendar_id": ids[0],
    })
    secret = _secret(r.json()["url"])

    ev = {
        "calendar_id": ids[0], "title": "X", "all_day": True,
        "start": "2026-06-20", "end": "2026-06-20",
    }
    ok = await client.post("/shares/events", json=ev, headers=_hdr(secret))
    assert ok.status_code == 200
    assert created  # the underlying create ran

    # Writing to the read-only-scoped calendar is forbidden.
    bad = await client.post(
        "/shares/events", json={**ev, "calendar_id": ids[1]}, headers=_hdr(secret)
    )
    assert bad.status_code == 403


@pytest.mark.asyncio
async def test_ro_share_rejects_writes(client, db_engine, store, sharing_on):
    uid, dek = await _login(client, store, "s-ro@example.com")
    ids = await _add_calendars(uid, dek, n=1)
    r = await client.post("/shares", json={
        "kind": "grid", "mode": "ro",
        "grid": {"grid_view": "dayGridMonth", "grid_anchor": "2026-06-15"},
        "calendars": [{"id": ids[0]}],
    })
    secret = _secret(r.json()["url"])
    bad = await client.post("/shares/events", json={
        "calendar_id": ids[0], "title": "X", "all_day": True,
        "start": "2026-06-20", "end": "2026-06-20",
    }, headers=_hdr(secret))
    assert bad.status_code == 403


@pytest.mark.asyncio
async def test_item_share_limited_to_uid(client, db_engine, store, sharing_on, monkeypatch):
    uid, dek = await _login(client, store, "s-item-w@example.com")
    ids = await _add_calendars(uid, dek, n=1)

    async def fake_update_event(**kwargs):
        return None

    monkeypatch.setattr(events_router, "update_event", fake_update_event)

    r = await client.post("/shares", json={
        "kind": "item", "mode": "rw",
        "item": {"uid": "the-uid@x", "item_kind": "event", "calendar_id": ids[0]},
    })
    secret = _secret(r.json()["url"])
    body = {
        "calendar_id": ids[0], "title": "X", "all_day": True,
        "start": "2026-06-20", "end": "2026-06-20", "scope": "all",
    }
    # Editing the shared uid works.
    ok = await client.put("/shares/events/the-uid@x", json=body, headers=_hdr(secret))
    assert ok.status_code == 200
    # Editing any other uid is forbidden.
    bad = await client.put("/shares/events/other-uid@x", json=body, headers=_hdr(secret))
    assert bad.status_code == 403


# --------------------------------------------------------------------------- #
# .ics export
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_export_ics(client, db_engine, store, sharing_on, monkeypatch):
    uid, dek = await _login(client, store, "s-ics@example.com")
    ids = await _add_calendars(uid, dek, n=1)

    async def fake_export_range(sources, from_dt, to_dt):
        return "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n"

    monkeypatch.setattr(shares_router, "export_range_ics", fake_export_range)

    r = await client.post("/shares", json={
        "kind": "grid", "mode": "ro",
        "grid": {"grid_view": "dayGridMonth", "grid_anchor": "2026-06-15"},
        "calendars": [{"id": ids[0]}],
    })
    secret = _secret(r.json()["url"])
    share_id = r.json()["info"]["id"]
    res = await client.get(f"/shares/{share_id}/export.ics", headers=_hdr(secret))
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/calendar")
    assert "VCALENDAR" in res.text
