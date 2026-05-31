import asyncio
from datetime import date, timedelta, timezone
from datetime import datetime as dt_type
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..caldav_client import (
    EventNotFoundError,
    RecurringEventError,
    fetch_events,
    update_event,
)
from ..crypto import decrypt_bytes
from ..deps import get_db, get_unrestricted_session
from ..models import Calendar, CalDAVAccount
from ..session import SessionEntry

logger = structlog.get_logger()

router = APIRouter(prefix="/events", tags=["events"])

_today = date.today


def _dummy_events() -> list[dict]:
    today = _today()
    return [
        {
            "id": "demo-welcome",
            "title": "Welcome to WebCalDav!",
            "start": today.isoformat(),
            "allDay": True,
            "color": "#3788d8",
            "extendedProps": {
                "description": "Connect a CalDAV server via the Settings panel to see real events."
            },
        },
        {
            "id": "demo-setup",
            "title": "Add a CalDAV account",
            "start": (today + timedelta(days=1)).isoformat(),
            "allDay": True,
            "color": "#22c55e",
        },
        {
            "id": "demo-explore",
            "title": "Explore month / week / day views",
            "start": (today + timedelta(days=2)).isoformat(),
            "end": (today + timedelta(days=4)).isoformat(),
            "color": "#f59e0b",
        },
        {
            "id": "demo-notify",
            "title": "Browser reminders coming in v4",
            "start": f"{(today + timedelta(days=3)).isoformat()}T10:00:00",
            "end": f"{(today + timedelta(days=3)).isoformat()}T11:00:00",
            "color": "#8b5cf6",
        },
    ]


def _parse_dt(s: str | None) -> dt_type | None:
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return dt_type.fromisoformat(s)
        except ValueError:
            pass
    return None


@router.get("")
async def get_events(
    entry: SessionEntry = Depends(get_unrestricted_session),
    db: AsyncSession = Depends(get_db),
    from_: str | None = Query(None, alias="from"),
    to: str | None = None,
    calendar_ids: str | None = None,
) -> list[dict]:
    result = await db.execute(
        select(Calendar, CalDAVAccount)
        .join(CalDAVAccount, Calendar.caldav_account_id == CalDAVAccount.id)
        .where(CalDAVAccount.user_id == entry.user_id, Calendar.enabled == True)  # noqa: E712
    )
    rows = result.all()

    if not rows:
        logger.info("events_no_enabled_calendars", user_id=entry.user_id)
        return _dummy_events()

    from_dt = _parse_dt(from_)
    to_dt = _parse_dt(to)
    if from_dt is None or to_dt is None:
        from datetime import timezone
        now = dt_type.now(timezone.utc)
        from_dt = from_dt or now.replace(day=1)
        to_dt = to_dt or now

    logger.info(
        "events_fetch_start",
        user_id=entry.user_id,
        calendars=len(rows),
        from_raw=from_,
        to_raw=to,
        from_dt=from_dt.isoformat(),
        to_dt=to_dt.isoformat(),
    )

    tasks = []
    for cal, account in rows:
        password = decrypt_bytes(account.encrypted_password, account.nonce, entry.dek).decode()
        tasks.append(fetch_events(
            account_url=account.url,
            username=account.username,
            password=password,
            calendar_url=cal.caldav_id,
            from_dt=from_dt,
            to_dt=to_dt,
            color=cal.color,
            calendar_id=cal.id,
        ))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    events: list[dict] = []
    for i, res in enumerate(results):
        cal, account = rows[i]
        if isinstance(res, Exception):
            logger.warning(
                "caldav_fetch_failed",
                account_id=account.id,
                calendar_id=cal.id,
                calendar_url=cal.caldav_id,
                error=repr(res),
            )
        else:
            logger.info(
                "caldav_fetch_ok",
                calendar_id=cal.id,
                calendar_url=cal.caldav_id,
                count=len(res),
            )
            events.extend(res)

    logger.info("events_fetch_done", user_id=entry.user_id, total=len(events))
    return events


class EventUpdate(BaseModel):
    calendar_id: int
    title: str = ""
    all_day: bool = False
    start: str
    end: str | None = None
    location: str | None = None
    description: str | None = None
    timezone: str | None = None


@router.put("/{uid:path}")
async def put_event(
    uid: str,
    body: EventUpdate,
    entry: SessionEntry = Depends(get_unrestricted_session),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(Calendar, CalDAVAccount)
        .join(CalDAVAccount, Calendar.caldav_account_id == CalDAVAccount.id)
        .where(Calendar.id == body.calendar_id, CalDAVAccount.user_id == entry.user_id)
    )
    row = result.first()
    if row is None:
        raise HTTPException(status_code=404, detail="Calendar not found")
    cal, account = row

    if body.all_day:
        try:
            start: date = date.fromisoformat(body.start[:10])
            end_src = body.end[:10] if body.end else body.start[:10]
            # iCal all-day DTEND is exclusive; the client sends the inclusive
            # last day, so advance one day here.
            end: date = date.fromisoformat(end_src) + timedelta(days=1)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid all-day dates")
    else:
        try:
            tz = ZoneInfo(body.timezone) if body.timezone else timezone.utc
        except ZoneInfoNotFoundError:
            tz = timezone.utc
        if not body.end:
            raise HTTPException(status_code=400, detail="End is required for timed events")
        try:
            start = dt_type.fromisoformat(body.start)
            end = dt_type.fromisoformat(body.end)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid datetime")
        if start.tzinfo is None:
            start = start.replace(tzinfo=tz)
        if end.tzinfo is None:
            end = end.replace(tzinfo=tz)
        if end <= start:
            raise HTTPException(status_code=400, detail="End must be after start")

    password = decrypt_bytes(account.encrypted_password, account.nonce, entry.dek).decode()
    try:
        await update_event(
            account_url=account.url,
            username=account.username,
            password=password,
            calendar_url=cal.caldav_id,
            uid=uid,
            title=body.title,
            all_day=body.all_day,
            start=start,
            end=end,
            location=body.location,
            description=body.description,
        )
    except RecurringEventError:
        raise HTTPException(
            status_code=422, detail="Editing recurring events is not supported yet"
        )
    except EventNotFoundError:
        raise HTTPException(status_code=404, detail="Event not found")
    except Exception as e:
        logger.warning("event_update_failed", uid=uid, error=repr(e))
        raise HTTPException(status_code=502, detail="Failed to update event on CalDAV server")

    logger.info("event_updated", user_id=entry.user_id, uid=uid, calendar_id=cal.id)
    return {"status": "ok"}
