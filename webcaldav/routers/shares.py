"""Calendar sharing: share-link CRUD (settings panel) + the unauthenticated
share-view data/write endpoints.

Creating a share requires sharing to be enabled and an active session (the
session's DEK is sealed into the share). Listing and revoking always work, so a
user can clean up shares even after sharing is turned off.

The share-view endpoints (``/shares/resolve``, ``/shares/items``, the
``/shares/events|tasks|journals`` writers, and ``/shares/{id}/export.ics``) are
authenticated by the URL-fragment secret presented in the ``X-Share-Secret``
header, resolved by :func:`webcaldav.deps.get_share_context`. The sealed blob is
authoritative for mode/scope/window — request parameters can only narrow, never
widen. This mirrors the MCP token model.
"""
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..baseurl import base_url
from ..caldav_client import (
    CalendarRef,
    export_item_ics,
    export_range_ics,
    fetch_account_data,
)
from ..config import settings
from ..crypto import decrypt_bytes
from ..deps import get_db, get_share_context, get_unrestricted_session
from ..models import Calendar, CalDAVAccount, Share, ShareCalendar, UserSettings
from ..session import SessionEntry
from ..shares import ShareContext, mint_share
from . import events as events_router
from . import journals as journals_router
from . import tasks as tasks_router

logger = structlog.get_logger()

router = APIRouter(prefix="/shares", tags=["shares"])


# --------------------------------------------------------------------------- #
# Create / list / revoke (session-authed)
# --------------------------------------------------------------------------- #
class ItemSpec(BaseModel):
    uid: str = Field(min_length=1)
    item_kind: Literal["event", "task", "journal"]
    calendar_id: int


class GridSpec(BaseModel):
    grid_view: Literal["dayGridMonth", "timeGridWeek", "timeGridDay"]
    grid_anchor: str  # ISO date


class AgendaSpec(BaseModel):
    agenda_from: str  # ISO datetime
    agenda_to: str


class CalScope(BaseModel):
    id: int
    writable: bool = False


class ShareCreate(BaseModel):
    name: str = Field(default="", max_length=200)
    kind: Literal["item", "grid", "agenda"]
    mode: Literal["ro", "rw"]
    expires_at: str | None = None  # ISO 8601; None = never expires
    item: ItemSpec | None = None
    grid: GridSpec | None = None
    agenda: AgendaSpec | None = None
    calendars: list[CalScope] | None = None
    default_calendar_id: int | None = None


class ShareOut(BaseModel):
    id: int
    name: str
    kind: str
    mode: str
    expires_at: str | None
    created_at: str
    last_used_at: str | None
    item_uid: str | None
    item_kind: str | None
    item_calendar_id: int | None
    grid_view: str | None
    grid_anchor: str | None
    agenda_from: str | None
    agenda_to: str | None
    default_calendar_id: int | None
    calendars: list[dict[str, Any]]


async def _user_calendars(user_id: int, db: AsyncSession) -> dict[int, Calendar]:
    rows = (
        await db.execute(
            select(Calendar)
            .join(CalDAVAccount, Calendar.caldav_account_id == CalDAVAccount.id)
            .where(CalDAVAccount.user_id == user_id)
        )
    ).scalars().all()
    return {c.id: c for c in rows}


async def _user_settings(user_id: int, db: AsyncSession) -> tuple[str, int]:
    s = (
        await db.execute(select(UserSettings).where(UserSettings.user_id == user_id))
    ).scalar_one_or_none()
    if s is None:
        return "UTC", 1
    return s.timezone, s.first_day_of_week


def _to_out(share: Share, cal_rows: list[ShareCalendar]) -> ShareOut:
    return ShareOut(
        id=share.id,
        name=share.name,
        kind=share.kind,
        mode=share.mode,
        expires_at=share.expires_at.isoformat() if share.expires_at else None,
        created_at=share.created_at.isoformat(),
        last_used_at=share.last_used_at.isoformat() if share.last_used_at else None,
        item_uid=share.item_uid,
        item_kind=share.item_kind,
        item_calendar_id=share.item_calendar_id,
        grid_view=share.grid_view,
        grid_anchor=share.grid_anchor,
        agenda_from=share.agenda_from.isoformat() if share.agenda_from else None,
        agenda_to=share.agenda_to.isoformat() if share.agenda_to else None,
        default_calendar_id=share.default_calendar_id,
        calendars=[{"id": c.calendar_id, "writable": c.writable} for c in cal_rows],
    )


def _parse_expiry(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        exp = datetime.fromisoformat(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid expires_at")
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=UTC)
    if exp <= datetime.now(UTC):
        raise HTTPException(status_code=400, detail="expires_at must be in the future")
    return exp


@router.get("")
async def list_shares(
    entry: SessionEntry = Depends(get_unrestricted_session),
    db: AsyncSession = Depends(get_db),
) -> list[ShareOut]:
    rows = (
        await db.execute(
            select(Share)
            .where(Share.user_id == entry.user_id)
            .order_by(Share.created_at.desc())
        )
    ).scalars().all()
    out = []
    for s in rows:
        cals = (
            await db.execute(
                select(ShareCalendar).where(ShareCalendar.share_id == s.id)
            )
        ).scalars().all()
        out.append(_to_out(s, list(cals)))
    return out


@router.post("")
async def create_share(
    body: ShareCreate,
    request: Request,
    entry: SessionEntry = Depends(get_unrestricted_session),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if not settings.sharing_enabled:
        raise HTTPException(status_code=403, detail="Sharing is disabled")

    expires_at = _parse_expiry(body.expires_at)
    owned = await _user_calendars(entry.user_id, db)
    tz, fdow = await _user_settings(entry.user_id, db)

    # Per-kind validation + sealed-blob arguments.
    mint_kwargs: dict[str, Any] = {}
    share_cols: dict[str, Any] = {}
    scope_rows: list[tuple[int, bool]] = []

    if body.kind == "item":
        if body.item is None:
            raise HTTPException(status_code=400, detail="item is required")
        if body.item.calendar_id not in owned:
            raise HTTPException(status_code=400, detail="Unknown calendar")
        mint_kwargs["item"] = {
            "item_uid": body.item.uid,
            "item_kind": body.item.item_kind,
            "calendar_id": body.item.calendar_id,
        }
        share_cols.update(
            item_uid=body.item.uid,
            item_kind=body.item.item_kind,
            item_calendar_id=body.item.calendar_id,
        )
    else:
        scope = body.calendars or []
        ids = [c.id for c in scope]
        if not ids:
            raise HTTPException(status_code=400, detail="At least one calendar is required")
        if len(set(ids)) != len(ids):
            raise HTTPException(status_code=400, detail="Duplicate calendar in scope")
        if not set(ids).issubset(owned):
            raise HTTPException(status_code=400, detail="Unknown calendar in scope")
        # Writable flags only apply to RW shares.
        writable_ids = {c.id for c in scope if c.writable} if body.mode == "rw" else set()
        default_cal = body.default_calendar_id if body.mode == "rw" else None
        if default_cal is not None and default_cal not in writable_ids:
            raise HTTPException(
                status_code=400, detail="default_calendar_id must be a writable calendar"
            )
        if default_cal is None and writable_ids:
            # Pick a stable default so sharee-created items have a home.
            default_cal = sorted(writable_ids)[0]
        cal_list = [{"id": c.id, "writable": c.id in writable_ids} for c in scope]
        mint_kwargs["calendars"] = cal_list
        mint_kwargs["default_calendar_id"] = default_cal
        scope_rows = [(c.id, c.id in writable_ids) for c in scope]
        share_cols["default_calendar_id"] = default_cal

        if body.kind == "grid":
            if body.grid is None:
                raise HTTPException(status_code=400, detail="grid is required")
            mint_kwargs["grid"] = {
                "grid_view": body.grid.grid_view,
                "grid_anchor": body.grid.grid_anchor,
                "tz": tz,
                "first_day_of_week": fdow,
            }
            share_cols.update(grid_view=body.grid.grid_view, grid_anchor=body.grid.grid_anchor)
        else:  # agenda
            if body.agenda is None:
                raise HTTPException(status_code=400, detail="agenda is required")
            try:
                a_from = datetime.fromisoformat(body.agenda.agenda_from)
                a_to = datetime.fromisoformat(body.agenda.agenda_to)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid agenda range")
            if a_to <= a_from:
                raise HTTPException(status_code=400, detail="agenda_to must be after agenda_from")
            mint_kwargs["agenda"] = {
                "agenda_from": body.agenda.agenda_from,
                "agenda_to": body.agenda.agenda_to,
                "tz": tz,
            }
            share_cols.update(agenda_from=a_from, agenda_to=a_to)

    secret, token_sha256, sealed_blob, blob_nonce = mint_share(
        dek=entry.dek,
        kind=body.kind,
        mode=body.mode,
        expires_at=expires_at,
        **mint_kwargs,
    )

    name = body.name.strip() or _default_name(body)
    share = Share(
        user_id=entry.user_id,
        name=name,
        token_sha256=token_sha256,
        sealed_blob=sealed_blob,
        blob_nonce=blob_nonce,
        kind=body.kind,
        mode=body.mode,
        expires_at=expires_at,
        **share_cols,
    )
    db.add(share)
    await db.flush()
    for cid, writable in scope_rows:
        db.add(ShareCalendar(share_id=share.id, calendar_id=cid, writable=writable))
    await db.commit()
    await db.refresh(share)

    logger.info(
        "share_created",
        user_id=entry.user_id,
        share_id=share.id,
        kind=body.kind,
        mode=body.mode,
    )
    cal_rows = (
        await db.execute(select(ShareCalendar).where(ShareCalendar.share_id == share.id))
    ).scalars().all()
    url = f"{base_url(request)}/s/{share.id}#{secret}"
    # The URL (with secret) is returned exactly once and never stored.
    return {"url": url, "info": _to_out(share, list(cal_rows)).model_dump()}


def _default_name(body: ShareCreate) -> str:
    if body.kind == "item" and body.item:
        return f"{body.item.item_kind} share"
    if body.kind == "grid" and body.grid:
        return f"{body.grid.grid_view} share"
    return "agenda share"


@router.delete("/{share_id}")
async def revoke_share(
    share_id: int,
    entry: SessionEntry = Depends(get_unrestricted_session),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    share = (
        await db.execute(
            select(Share).where(Share.id == share_id, Share.user_id == entry.user_id)
        )
    ).scalar_one_or_none()
    if share is None:
        raise HTTPException(status_code=404, detail="Share not found")
    await db.delete(share)
    await db.commit()
    logger.info("share_revoked", user_id=entry.user_id, share_id=share_id)
    return {"status": "ok"}


# --------------------------------------------------------------------------- #
# Share-view: resolve + data + writes (share-secret authed)
# --------------------------------------------------------------------------- #
def _entry(ctx: ShareContext) -> SessionEntry:
    """A SessionEntry the existing router helpers accept (they read user_id/dek)."""
    return SessionEntry(
        user_id=ctx.user_id, dek=ctx.dek, last_seen=datetime.now(UTC), restricted=False
    )


def _require_rw(ctx: ShareContext) -> None:
    if ctx.mode != "rw":
        raise HTTPException(status_code=403, detail="This share is read-only")


def _authorize_write(
    ctx: ShareContext, *, calendar_id: int, original_calendar_id: int | None = None,
    uid: str | None = None,
) -> None:
    """Enforce RW + that every touched calendar (and, for item shares, the uid) is
    in the sealed writable scope."""
    _require_rw(ctx)
    if calendar_id not in ctx.writable_calendar_ids:
        raise HTTPException(status_code=403, detail="Calendar not writable in this share")
    if original_calendar_id is not None and original_calendar_id not in ctx.writable_calendar_ids:
        raise HTTPException(status_code=403, detail="Calendar not writable in this share")
    if ctx.kind == "item" and uid is not None and uid != ctx.item_uid:
        raise HTTPException(status_code=403, detail="This share is limited to one item")


async def _readable_calendars(
    ctx: ShareContext, db: AsyncSession
) -> list[tuple[Calendar, CalDAVAccount]]:
    rows = (
        await db.execute(
            select(Calendar, CalDAVAccount)
            .join(CalDAVAccount, Calendar.caldav_account_id == CalDAVAccount.id)
            .where(CalDAVAccount.user_id == ctx.user_id)
        )
    ).all()
    ids = ctx.readable_calendar_ids
    return [(c, a) for (c, a) in rows if c.id in ids]


def _password(account: CalDAVAccount, ctx: ShareContext) -> str:
    return decrypt_bytes(account.encrypted_password, account.nonce, ctx.dek).decode()


@router.post("/resolve")
async def resolve(
    ctx: ShareContext = Depends(get_share_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return the share's view configuration (no DEK, no credentials). The share
    page calls this first to configure its bounded, navigation-locked view."""
    cals = await _readable_calendars(ctx, db)
    by_id = {c.id: (c, a) for c, a in cals}
    cal_meta = []
    writable_meta = {cid: cid in ctx.writable_calendar_ids for cid in ctx.readable_calendar_ids}
    for cid in sorted(ctx.readable_calendar_ids):
        if cid in by_id:
            c, _ = by_id[cid]
            cal_meta.append(
                {
                    "id": c.id,
                    "name": c.display_name,
                    "color": c.color,
                    "writable": writable_meta.get(cid, False),
                }
            )
    return {
        "kind": ctx.kind,
        "mode": ctx.mode,
        "tz": ctx.tz,
        "first_day_of_week": ctx.first_day_of_week,
        "grid_view": ctx.grid_view,
        "grid_anchor": ctx.grid_anchor,
        "window_from": ctx.window_from.isoformat() if ctx.window_from else None,
        "window_to": ctx.window_to.isoformat() if ctx.window_to else None,
        "default_calendar_id": ctx.default_calendar_id,
        "calendars": cal_meta,
        "item": (
            {
                "uid": ctx.item_uid,
                "item_kind": ctx.item_kind,
                "calendar_id": ctx.item_calendar_id,
            }
            if ctx.kind == "item"
            else None
        ),
    }


def _clamp_window(ctx: ShareContext) -> tuple[datetime, datetime]:
    """The authoritative fetch window. For item shares (no window) use a wide
    range so a recurring master/override is captured."""
    if ctx.window_from and ctx.window_to:
        return ctx.window_from, ctx.window_to
    now = datetime.now(UTC)
    return now - timedelta(days=3650), now + timedelta(days=3650)


@router.get("/items")
async def items(
    ctx: ShareContext = Depends(get_share_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Events, tasks and journals visible to the share, scoped to the sealed
    window and calendars."""
    from_dt, to_dt = _clamp_window(ctx)
    cals = await _readable_calendars(ctx, db)

    # Group by account so each opens one shared client across its calendars.
    by_account: dict[int, tuple[CalDAVAccount, list[CalendarRef]]] = {}
    for cal, account in cals:
        if account.id not in by_account:
            by_account[account.id] = (account, [])
        by_account[account.id][1].append(
            CalendarRef(calendar_url=cal.caldav_id, color=cal.color, calendar_id=cal.id)
        )

    kinds = frozenset(("events", "tasks", "journals"))
    out_events: list[dict[str, Any]] = []
    out_tasks: list[dict[str, Any]] = []
    out_journals: list[dict[str, Any]] = []
    for account, refs in by_account.values():
        pw = _password(account, ctx)
        try:
            res = await fetch_account_data(
                account_url=account.url,
                username=account.username,
                password=pw,
                calendars=refs,
                from_dt=from_dt,
                to_dt=to_dt,
                kinds=kinds,
            )
        except Exception as e:
            logger.warning("share_fetch_failed", account_id=account.id, error=repr(e))
            continue
        out_events.extend(res["events"])
        out_tasks.extend(res["tasks"])
        out_journals.extend(res["journals"])
    if ctx.kind == "item":
        # Narrow to the shared uid only.
        out_events = [e for e in out_events if e.get("id") == ctx.item_uid]
        out_tasks = [t for t in out_tasks if t.get("id") == ctx.item_uid]
        out_journals = [j for j in out_journals if j.get("id") == ctx.item_uid]
    return {"events": out_events, "tasks": out_tasks, "journals": out_journals}


# ---- writes (RW shares) — delegate to the existing route handlers ---------- #
@router.post("/events")
async def share_post_event(
    body: events_router.EventUpdate,
    ctx: ShareContext = Depends(get_share_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _authorize_write(ctx, calendar_id=body.calendar_id)
    return await events_router.post_event(body, _entry(ctx), db)


@router.put("/events/{uid:path}")
async def share_put_event(
    uid: str,
    body: events_router.EventUpdate,
    ctx: ShareContext = Depends(get_share_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _authorize_write(
        ctx, calendar_id=body.calendar_id,
        original_calendar_id=body.original_calendar_id, uid=uid,
    )
    return await events_router.put_event(uid, body, _entry(ctx), db)


@router.delete("/events/{uid:path}")
async def share_delete_event(
    uid: str,
    calendar_id: int,
    scope: str = "all",
    recurrence_id: str | None = None,
    ctx: ShareContext = Depends(get_share_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _authorize_write(ctx, calendar_id=calendar_id, uid=uid)
    return await events_router.delete_event_route(
        uid, calendar_id, scope, recurrence_id, _entry(ctx), db
    )


@router.post("/tasks")
async def share_post_task(
    body: tasks_router.TaskUpdate,
    ctx: ShareContext = Depends(get_share_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _authorize_write(ctx, calendar_id=body.calendar_id)
    return await tasks_router.post_task(body, _entry(ctx), db)


@router.put("/tasks/{uid:path}")
async def share_put_task(
    uid: str,
    body: tasks_router.TaskUpdate,
    ctx: ShareContext = Depends(get_share_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _authorize_write(
        ctx, calendar_id=body.calendar_id,
        original_calendar_id=body.original_calendar_id, uid=uid,
    )
    return await tasks_router.put_task(uid, body, _entry(ctx), db)


@router.post("/tasks/{uid:path}/status")
async def share_task_status(
    uid: str,
    body: tasks_router.StatusToggle,
    ctx: ShareContext = Depends(get_share_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _authorize_write(ctx, calendar_id=body.calendar_id, uid=uid)
    return await tasks_router.toggle_task_status(uid, body, _entry(ctx), db)


@router.delete("/tasks/{uid:path}")
async def share_delete_task(
    uid: str,
    calendar_id: int,
    scope: str = "all",
    recurrence_id: str | None = None,
    ctx: ShareContext = Depends(get_share_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _authorize_write(ctx, calendar_id=calendar_id, uid=uid)
    return await tasks_router.delete_task_route(
        uid, calendar_id, scope, recurrence_id, _entry(ctx), db
    )


@router.post("/journals")
async def share_post_journal(
    body: journals_router.JournalUpdate,
    ctx: ShareContext = Depends(get_share_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _authorize_write(ctx, calendar_id=body.calendar_id)
    return await journals_router.post_journal(body, _entry(ctx), db)


@router.put("/journals/{uid:path}")
async def share_put_journal(
    uid: str,
    body: journals_router.JournalUpdate,
    ctx: ShareContext = Depends(get_share_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _authorize_write(
        ctx, calendar_id=body.calendar_id,
        original_calendar_id=body.original_calendar_id, uid=uid,
    )
    return await journals_router.put_journal(uid, body, _entry(ctx), db)


@router.delete("/journals/{uid:path}")
async def share_delete_journal(
    uid: str,
    calendar_id: int,
    ctx: ShareContext = Depends(get_share_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _authorize_write(ctx, calendar_id=calendar_id, uid=uid)
    return await journals_router.delete_journal_route(uid, calendar_id, _entry(ctx), db)


# --------------------------------------------------------------------------- #
# .ics export (share-secret authed)
# --------------------------------------------------------------------------- #
@router.get("/{share_id}/export.ics")
async def export_ics(
    share_id: int,
    ctx: ShareContext = Depends(get_share_context),
    db: AsyncSession = Depends(get_db),
) -> Response:
    if ctx.share_id != share_id:
        raise HTTPException(status_code=404, detail="Share not found")
    cals = await _readable_calendars(ctx, db)
    by_id = {c.id: (c, a) for c, a in cals}

    if ctx.kind == "item":
        if ctx.item_calendar_id not in by_id:
            raise HTTPException(status_code=404, detail="Item not found")
        cal, account = by_id[ctx.item_calendar_id]
        ics = await export_item_ics(
            account_url=account.url,
            username=account.username,
            password=_password(account, ctx),
            calendar_url=cal.caldav_id,
            uid=ctx.item_uid or "",
            item_kind=ctx.item_kind or "event",
        )
        filename = f"{(ctx.item_uid or 'item').split('@')[0]}.ics"
    else:
        from_dt, to_dt = _clamp_window(ctx)
        sources = [
            {
                "account_url": a.url,
                "username": a.username,
                "password": _password(a, ctx),
                "calendar_url": c.caldav_id,
            }
            for c, a in cals
        ]
        ics = await export_range_ics(sources, from_dt, to_dt)
        filename = f"share-{share_id}.ics"

    return Response(
        content=ics,
        media_type="text/calendar",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
