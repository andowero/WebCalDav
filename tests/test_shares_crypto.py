"""Unit tests for the share sealed-blob layer (mint_share / resolve_share),
mirroring the MCP token crypto tests. Authoritative scope/mode/expiry live in the
AES-GCM blob; the DB mirror columns are never trusted."""
from datetime import UTC, datetime, timedelta

import pytest

from webcaldav.admin import _provision_user
from webcaldav.crypto import generate_dek
from webcaldav.db import get_session_factory
from webcaldav.models import Share
from webcaldav.shares import grid_window, mint_share, resolve_share


async def _create_user(email: str) -> int:
    async with get_session_factory()() as db:
        user = await _provision_user(email, "initial", db)
        return user.id


async def _insert(uid: int, sha: bytes, blob: bytes, nonce: bytes, **cols) -> int:
    async with get_session_factory()() as db:
        s = Share(
            user_id=uid, name="s", token_sha256=sha, sealed_blob=blob,
            blob_nonce=nonce, **cols,
        )
        db.add(s)
        await db.commit()
        await db.refresh(s)
        return s.id


@pytest.mark.asyncio
async def test_item_roundtrip(db_engine):
    uid = await _create_user("share-item@example.com")
    dek = generate_dek()
    secret, sha, blob, nonce = mint_share(
        dek, "item", "rw", expires_at=None,
        item={"item_uid": "e1@x", "item_kind": "event", "calendar_id": 7},
    )
    await _insert(uid, sha, blob, nonce, kind="item", mode="rw",
                  item_uid="e1@x", item_kind="event", item_calendar_id=7)
    async with get_session_factory()() as db:
        ctx = await resolve_share(secret, db)
    assert ctx is not None
    assert ctx.dek == dek
    assert ctx.kind == "item"
    assert ctx.mode == "rw"
    assert ctx.item_uid == "e1@x"
    assert ctx.item_calendar_id == 7
    assert ctx.readable_calendar_ids == {7}
    assert ctx.writable_calendar_ids == {7}


@pytest.mark.asyncio
async def test_grid_roundtrip_and_window(db_engine):
    uid = await _create_user("share-grid@example.com")
    dek = generate_dek()
    secret, sha, blob, nonce = mint_share(
        dek, "grid", "rw", expires_at=None,
        grid={"grid_view": "dayGridMonth", "grid_anchor": "2026-06-15",
              "tz": "Europe/Prague", "first_day_of_week": 1},
        calendars=[{"id": 1, "writable": True}, {"id": 2, "writable": False}],
        default_calendar_id=1,
    )
    await _insert(uid, sha, blob, nonce, kind="grid", mode="rw")
    async with get_session_factory()() as db:
        ctx = await resolve_share(secret, db)
    assert ctx is not None
    assert ctx.readable_calendar_ids == {1, 2}
    assert ctx.writable_calendar_ids == {1}  # only the writable one
    assert ctx.default_calendar_id == 1
    assert ctx.tz == "Europe/Prague"
    assert ctx.window_from is not None and ctx.window_to is not None
    # 6-week (42-day) month grid.
    assert (ctx.window_to - ctx.window_from).days == 42


@pytest.mark.asyncio
async def test_agenda_roundtrip(db_engine):
    uid = await _create_user("share-agenda@example.com")
    dek = generate_dek()
    secret, sha, blob, nonce = mint_share(
        dek, "agenda", "ro", expires_at=None,
        agenda={"agenda_from": "2026-06-19T00:00:00+02:00",
                "agenda_to": "2026-06-26T00:00:00+02:00", "tz": "Europe/Prague"},
        calendars=[{"id": 3, "writable": True}],  # writable ignored for RO
        default_calendar_id=3,
    )
    await _insert(uid, sha, blob, nonce, kind="agenda", mode="ro")
    async with get_session_factory()() as db:
        ctx = await resolve_share(secret, db)
    assert ctx is not None
    assert ctx.mode == "ro"
    assert ctx.readable_calendar_ids == {3}
    assert ctx.writable_calendar_ids == set()  # RO => nothing writable
    assert ctx.window_from.isoformat() == "2026-06-19T00:00:00+02:00"


@pytest.mark.asyncio
async def test_tamper_rejected(db_engine):
    uid = await _create_user("share-tamper@example.com")
    dek = generate_dek()
    secret, sha, blob, nonce = mint_share(
        dek, "item", "ro", expires_at=None,
        item={"item_uid": "e", "item_kind": "event", "calendar_id": 1},
    )
    bad_blob = bytes([blob[0] ^ 0xFF]) + blob[1:]
    await _insert(uid, sha, bad_blob, nonce, kind="item", mode="ro")
    async with get_session_factory()() as db:
        assert await resolve_share(secret, db) is None


@pytest.mark.asyncio
async def test_mirror_columns_not_trusted(db_engine):
    """Flip the display ``mode`` column to rw while the sealed blob says ro: the
    resolved mode must come from the blob (ro)."""
    uid = await _create_user("share-mirror@example.com")
    dek = generate_dek()
    secret, sha, blob, nonce = mint_share(
        dek, "item", "ro", expires_at=None,
        item={"item_uid": "e", "item_kind": "event", "calendar_id": 1},
    )
    # Lie in the mirror column.
    await _insert(uid, sha, blob, nonce, kind="item", mode="rw",
                  item_uid="e", item_kind="event", item_calendar_id=1)
    async with get_session_factory()() as db:
        ctx = await resolve_share(secret, db)
    assert ctx is not None
    assert ctx.mode == "ro"
    assert ctx.writable_calendar_ids == set()


@pytest.mark.asyncio
async def test_expired_rejected(db_engine):
    uid = await _create_user("share-exp@example.com")
    dek = generate_dek()
    past = datetime.now(UTC) - timedelta(days=1)
    secret, sha, blob, nonce = mint_share(
        dek, "item", "ro", expires_at=past,
        item={"item_uid": "e", "item_kind": "event", "calendar_id": 1},
    )
    # Mirror column claims a future expiry; the sealed (past) one wins.
    future = datetime.now(UTC) + timedelta(days=30)
    await _insert(uid, sha, blob, nonce, kind="item", mode="ro", expires_at=future)
    async with get_session_factory()() as db:
        assert await resolve_share(secret, db) is None


@pytest.mark.asyncio
async def test_unknown_secret_rejected(db_engine):
    async with get_session_factory()() as db:
        assert await resolve_share("nope", db) is None
        assert await resolve_share("", db) is None


def test_grid_window_views():
    # Day: exactly one day.
    f, t = grid_window("timeGridDay", "2026-06-17", 1, "UTC")
    assert (t - f).days == 1
    # Week starting Monday (fdow=1): anchor Wed 2026-06-17 -> Mon 2026-06-15.
    f, t = grid_window("timeGridWeek", "2026-06-17", 1, "UTC")
    assert f.date().isoformat() == "2026-06-15"
    assert (t - f).days == 7
    # Week starting Sunday (fdow=0): anchor Wed -> Sun 2026-06-14.
    f, _ = grid_window("timeGridWeek", "2026-06-17", 0, "UTC")
    assert f.date().isoformat() == "2026-06-14"
