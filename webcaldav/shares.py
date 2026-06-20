"""Share links: minting and resolution.

A share's URL carries a random secret in its fragment (``/s/<id>#<secret>``),
shown to the sharer once and never stored. The DEK and the AUTHORITATIVE
scope/mode/bounds/expiry are sealed together in an AES-GCM blob keyed by a key
derived from the secret (see :func:`webcaldav.crypto.derive_token_key`).
Authorization always reads the decrypted blob, never the plaintext mirror
columns, so tampering with the DB rows cannot widen a share's scope or mode
without the secret. This mirrors :mod:`webcaldav.tokens`.

Three kinds:
- ``item``: one event/task/journal (uid + calendar).
- ``grid``: a month/week/day period; the window is derived from the view, an
  anchor date, and the sharer's first-day-of-week.
- ``agenda``: an explicit ``[from, to]`` datetime slice.
"""
import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .crypto import derive_token_key, unwrap_dek, wrap_dek
from .models import Share

_KINDS = {"item", "grid", "agenda"}
_MODES = {"ro", "rw"}
_GRID_VIEWS = {"dayGridMonth", "timeGridWeek", "timeGridDay"}


@dataclass
class ShareContext:
    """Resolved, authenticated state for a share request, built from the sealed
    blob only (never from the plaintext mirror columns)."""

    share_id: int
    user_id: int
    dek: bytes
    kind: str  # "item" | "grid" | "agenda"
    mode: str  # "ro" | "rw"
    expires_at: datetime | None
    readable_calendar_ids: set[int]
    writable_calendar_ids: set[int]
    default_calendar_id: int | None
    item_uid: str | None
    item_kind: str | None  # "event" | "task" | "journal"
    item_calendar_id: int | None
    grid_view: str | None
    grid_anchor: str | None
    window_from: datetime | None
    window_to: datetime | None
    tz: str
    first_day_of_week: int
    calendars: list[dict[str, Any]] = field(default_factory=list)


def _zone(tzname: str) -> ZoneInfo:
    try:
        return ZoneInfo(tzname)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def grid_window(view: str, anchor_iso: str, fdow: int, tzname: str) -> tuple[datetime, datetime]:
    """Compute the [from, to) datetime window a grid view renders, in ``tzname``.

    ``fdow`` is the first day of the week in FullCalendar's convention
    (0=Sunday..6=Saturday). Month uses a fixed 6-week (42-day) grid to match
    FullCalendar's default ``fixedWeekCount``.
    """
    tz = _zone(tzname)
    anchor = date.fromisoformat(anchor_iso[:10])
    if view == "timeGridDay":
        start = anchor
        end = anchor + timedelta(days=1)
    elif view == "timeGridWeek":
        start = _week_start(anchor, fdow)
        end = start + timedelta(days=7)
    else:  # dayGridMonth
        first = date(anchor.year, anchor.month, 1)
        start = _week_start(first, fdow)
        end = start + timedelta(days=42)
    return (
        datetime(start.year, start.month, start.day, tzinfo=tz),
        datetime(end.year, end.month, end.day, tzinfo=tz),
    )


def _week_start(d: date, fdow: int) -> date:
    """Snap ``d`` back to the start of its week given a Sunday=0 first day."""
    dow_sun0 = (d.weekday() + 1) % 7  # Mon=0..Sun=6 -> Sun=0..Sat=6
    return d - timedelta(days=(dow_sun0 - fdow) % 7)


def mint_share(
    dek: bytes,
    kind: str,
    mode: str,
    *,
    expires_at: datetime | None,
    item: dict[str, Any] | None = None,
    grid: dict[str, Any] | None = None,
    agenda: dict[str, Any] | None = None,
    calendars: list[dict[str, Any]] | None = None,
    default_calendar_id: int | None = None,
) -> tuple[str, bytes, bytes, bytes]:
    """Return (secret, token_sha256, sealed_blob, blob_nonce).

    The caller persists the last three and embeds ``secret`` in the URL fragment
    shown to the sharer once. ``item``/``grid``/``agenda`` carry the kind-specific
    scope; ``calendars`` is ``[{"id": int, "writable": bool}, ...]`` for
    grid/agenda.
    """
    if kind not in _KINDS:
        raise ValueError(f"invalid kind: {kind}")
    if mode not in _MODES:
        raise ValueError(f"invalid mode: {mode}")
    secret = secrets.token_urlsafe(32)
    payload: dict[str, Any] = {
        "dek": base64.b64encode(dek).decode("ascii"),
        "kind": kind,
        "mode": mode,
        "expires_at": expires_at.isoformat() if expires_at else None,
    }
    if kind == "item":
        payload.update(
            item_uid=item["item_uid"],  # type: ignore[index]
            item_kind=item["item_kind"],  # type: ignore[index]
            calendar_id=item["calendar_id"],  # type: ignore[index]
        )
    else:
        payload["calendars"] = [
            {"id": c["id"], "writable": bool(c.get("writable"))}
            for c in (calendars or [])
        ]
        payload["default_calendar_id"] = default_calendar_id
        if kind == "grid":
            payload.update(
                grid_view=grid["grid_view"],  # type: ignore[index]
                grid_anchor=grid["grid_anchor"],  # type: ignore[index]
                tz=grid.get("tz", "UTC"),  # type: ignore[union-attr]
                first_day_of_week=grid.get("first_day_of_week", 1),  # type: ignore[union-attr]
            )
        else:  # agenda
            payload.update(
                agenda_from=agenda["agenda_from"],  # type: ignore[index]
                agenda_to=agenda["agenda_to"],  # type: ignore[index]
                tz=agenda.get("tz", "UTC"),  # type: ignore[union-attr]
            )
    blob = json.dumps(payload).encode("utf-8")
    key = derive_token_key(secret)
    sealed_blob, blob_nonce = wrap_dek(blob, key)
    token_sha256 = hashlib.sha256(secret.encode("utf-8")).digest()
    return secret, token_sha256, sealed_blob, blob_nonce


async def resolve_share(secret: str, db: AsyncSession) -> ShareContext | None:
    """Authenticate a share secret and return its context, or None if the secret
    is unknown, tampered, or expired. Bumps ``last_used_at``."""
    if not secret:
        return None
    token_sha256 = hashlib.sha256(secret.encode("utf-8")).digest()
    row = (
        await db.execute(select(Share).where(Share.token_sha256 == token_sha256))
    ).scalar_one_or_none()
    if row is None:
        return None
    # Defensive constant-time confirm of the lookup match.
    if not hmac.compare_digest(row.token_sha256, token_sha256):
        return None

    key = derive_token_key(secret)
    try:
        payload = json.loads(unwrap_dek(row.sealed_blob, row.blob_nonce, key))
    except Exception:
        return None

    if payload.get("kind") not in _KINDS or payload.get("mode") not in _MODES:
        return None

    expires_at: datetime | None = None
    expires_raw = payload.get("expires_at")
    if expires_raw:
        try:
            expires_at = datetime.fromisoformat(expires_raw)
        except ValueError:
            return None
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if datetime.now(UTC) >= expires_at:
            return None

    try:
        dek = base64.b64decode(payload["dek"])
    except Exception:
        return None

    kind = payload["kind"]
    mode = payload["mode"]
    tz = "UTC"
    fdow = 1
    item_uid = item_kind = None
    item_calendar_id = None
    grid_view = None
    grid_anchor = None
    window_from = window_to = None
    default_calendar_id = None
    readable: set[int] = set()
    writable: set[int] = set()
    cal_meta: list[dict[str, Any]] = []

    if kind == "item":
        item_uid = payload.get("item_uid")
        item_kind = payload.get("item_kind")
        item_calendar_id = payload.get("calendar_id")
        if item_calendar_id is not None:
            readable = {item_calendar_id}
            if mode == "rw":
                writable = {item_calendar_id}
    else:
        tz = payload.get("tz", "UTC")
        default_calendar_id = payload.get("default_calendar_id")
        for c in payload.get("calendars", []):
            cid = c["id"]
            w = bool(c.get("writable"))
            readable.add(cid)
            if mode == "rw" and w:
                writable.add(cid)
            cal_meta.append({"id": cid, "writable": w})
        if kind == "grid":
            grid_view = payload.get("grid_view")
            grid_anchor = payload.get("grid_anchor")
            fdow = int(payload.get("first_day_of_week", 1))
            try:
                window_from, window_to = grid_window(
                    grid_view, payload["grid_anchor"], fdow, tz
                )
            except Exception:
                return None
        else:  # agenda
            try:
                window_from = datetime.fromisoformat(payload["agenda_from"])
                window_to = datetime.fromisoformat(payload["agenda_to"])
            except Exception:
                return None

    row.last_used_at = datetime.now(UTC)
    await db.commit()

    return ShareContext(
        share_id=row.id,
        user_id=row.user_id,
        dek=dek,
        kind=kind,
        mode=mode,
        expires_at=expires_at,
        readable_calendar_ids=readable,
        writable_calendar_ids=writable,
        default_calendar_id=default_calendar_id,
        item_uid=item_uid,
        item_kind=item_kind,
        item_calendar_id=item_calendar_id,
        grid_view=grid_view,
        grid_anchor=grid_anchor,
        window_from=window_from,
        window_to=window_to,
        tz=tz,
        first_day_of_week=fdow,
        calendars=cal_meta,
    )
