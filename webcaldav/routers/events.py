import asyncio
import re
import uuid
from datetime import date, timedelta, timezone
from datetime import datetime as dt_type
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..caldav_client import (
    EventNotFoundError,
    create_event,
    delete_event,
    fetch_events,
    preview_recurrence,
    update_event,
)
from ..crypto import decrypt_bytes
from ..deps import get_db, get_unrestricted_session
from ..models import Calendar, CalDAVAccount
from ..session import SessionEntry

logger = structlog.get_logger()

router = APIRouter(prefix="/events", tags=["events"])

_today = date.today


def _dummy_events() -> list[dict[str, Any]]:
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
) -> list[dict[str, Any]]:
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

    events: list[dict[str, Any]] = []
    for i, res in enumerate(results):
        cal, account = rows[i]
        if isinstance(res, BaseException):
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


_RECUR_SCOPES = {"all", "this", "thisfuture"}


class RecurrenceRule(BaseModel):
    freq: str  # yearly|monthly|weekly|daily|hourly
    interval: int = 1
    monthly_mode: str | None = None  # "monthday" | "weekday"
    ordinal: int | None = None  # Nth weekday of month; -1 = last
    until: str | None = None  # ISO date/datetime; mutually exclusive with count
    count: int | None = None


_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class Reminder(BaseModel):
    value: int = Field(ge=0, le=10000)
    unit: Literal["minutes", "hours", "days", "weeks"]
    time: str | None = None  # "HH:MM"; required for all-day events
    # Where the offset is measured from and on which side. Defaults reproduce the
    # original "N before the start" behavior, so old payloads round-trip intact.
    anchor: Literal["start", "end"] = "start"
    direction: Literal["before", "after"] = "before"


class EventUpdate(BaseModel):
    calendar_id: int
    # Set on edit when the user moves the event to a different calendar; the
    # event is recreated on calendar_id and deleted from original_calendar_id.
    original_calendar_id: int | None = None
    title: str = Field(default="", max_length=8000)
    all_day: bool = False
    start: str
    end: str | None = None
    location: str | None = Field(default=None, max_length=8000)
    description: str | None = Field(default=None, max_length=8000)
    timezone: str | None = None
    # Recurring-event controls. scope selects which occurrences a write touches;
    # recurrence_id is the pivot occurrence's original start (the client's
    # rawStart); recurrence is the rule to (re)build on create / scoped edits.
    scope: str = "all"
    recurrence_id: str | None = None
    recurrence: RecurrenceRule | None = None
    # None/absent = leave the event's alarms untouched (drag/resize updates);
    # [] = remove all editable alarms; otherwise the full replacement set.
    reminders: list[Reminder] | None = Field(default=None, max_length=10)

    @model_validator(mode="after")
    def _check_reminders(self) -> "EventUpdate":
        for r in self.reminders or []:
            if self.all_day:
                if r.unit not in ("days", "weeks"):
                    raise ValueError("all-day reminders must use days or weeks")
                if r.time is None or not _TIME_RE.match(r.time):
                    raise ValueError("all-day reminders need a time (HH:MM)")
            elif r.time is not None:
                raise ValueError("timed-event reminders must not set a time")
        return self


_UNIT_MINUTES = {"minutes": 1, "hours": 60, "days": 1440, "weeks": 10080}


def _reminder_deltas(
    reminders: list[Reminder] | None, all_day: bool
) -> list[tuple[timedelta, str]] | None:
    """Reminder rows -> (offset, RELATED) VALARM triggers (deduped, ordered).

    The offset sign encodes direction (before = negative, after = positive) and
    RELATED encodes the anchor (START/END). Timed events use a plain offset.
    All-day events carry a time of day: DTSTART/DTEND are dates (midnight), so
    "N days before at HH:MM" collapses to HH:MM minus N days (and "after" adds
    them) measured from the anchor.
    """
    if reminders is None:
        return None
    deltas: list[tuple[timedelta, str]] = []
    for r in reminders:
        if all_day:
            hours, minutes = (int(p) for p in r.time.split(":"))  # type: ignore[union-attr]
            day = timedelta(days=r.value * (7 if r.unit == "weeks" else 1))
            delta = (day if r.direction == "after" else -day) + timedelta(
                hours=hours, minutes=minutes
            )
        else:
            mag = timedelta(minutes=r.value * _UNIT_MINUTES[r.unit])
            delta = mag if r.direction == "after" else -mag
        related = "END" if r.anchor == "end" else "START"
        if (delta, related) not in deltas:
            deltas.append((delta, related))
    return deltas


async def _calendar_for(
    calendar_id: int, entry: SessionEntry, db: AsyncSession
) -> tuple[Calendar, CalDAVAccount]:
    result = await db.execute(
        select(Calendar, CalDAVAccount)
        .join(CalDAVAccount, Calendar.caldav_account_id == CalDAVAccount.id)
        .where(Calendar.id == calendar_id, CalDAVAccount.user_id == entry.user_id)
    )
    row = result.first()
    if row is None:
        raise HTTPException(status_code=404, detail="Calendar not found")
    return row.tuple()


def _resolve_span(body: EventUpdate) -> tuple[date | dt_type, date | dt_type]:
    """Parse the request's start/end into the date/datetime pair stored on the
    server (all-day DTEND is made exclusive)."""
    if body.all_day:
        try:
            start: date = date.fromisoformat(body.start[:10])
            end_src = body.end[:10] if body.end else body.start[:10]
            # iCal all-day DTEND is exclusive; the client sends the inclusive
            # last day, so advance one day here.
            end: date = date.fromisoformat(end_src) + timedelta(days=1)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid all-day dates")
        return start, end

    try:
        tz = ZoneInfo(body.timezone) if body.timezone else timezone.utc
    except ZoneInfoNotFoundError:
        tz = timezone.utc
    if not body.end:
        raise HTTPException(status_code=400, detail="End is required for timed events")
    try:
        start_dt = dt_type.fromisoformat(body.start)
        end_dt = dt_type.fromisoformat(body.end)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid datetime")
    # Naive input: stamp the request timezone. Tz-aware input (e.g. a drag sends
    # "...+02:00") carries only a numeric offset, which icalendar would serialize
    # as a bogus TZID="UTC+02:00" with no VTIMEZONE — the server then reads it
    # back as floating/UTC, shifting the event by the offset on every move. So
    # normalize tz-aware values onto the named ZoneInfo (same instant, proper
    # TZID) so the round-trip is stable.
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=tz)
    else:
        start_dt = start_dt.astimezone(tz)
    if end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=tz)
    else:
        end_dt = end_dt.astimezone(tz)
    if end_dt <= start_dt:
        raise HTTPException(status_code=400, detail="End must be after start")
    return start_dt, end_dt


@router.post("")
async def post_event(
    body: EventUpdate,
    entry: SessionEntry = Depends(get_unrestricted_session),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    cal, account = await _calendar_for(body.calendar_id, entry, db)
    start, end = _resolve_span(body)
    uid = f"{uuid.uuid4()}@webcaldav"

    rrule = body.recurrence.model_dump() if body.recurrence else None
    password = decrypt_bytes(account.encrypted_password, account.nonce, entry.dek).decode()
    try:
        await create_event(
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
            rrule=rrule,
            reminders=_reminder_deltas(body.reminders, body.all_day),
        )
    except Exception as e:
        logger.warning("event_create_failed", error=repr(e))
        raise HTTPException(status_code=502, detail="Failed to create event on CalDAV server")

    logger.info("event_created", user_id=entry.user_id, uid=uid, calendar_id=cal.id)
    return {"status": "ok", "id": uid}


class RecurrencePreview(BaseModel):
    start: str
    all_day: bool = False
    timezone: str | None = None
    recurrence: RecurrenceRule


@router.post("/recurrence-preview")
async def recurrence_preview(
    body: RecurrencePreview,
    entry: SessionEntry = Depends(get_unrestricted_session),
) -> dict[str, Any]:
    """Compute the last occurrence + total count for a recurrence rule."""
    try:
        if body.all_day:
            start: date | dt_type = date.fromisoformat(body.start[:10])
        else:
            try:
                tz = ZoneInfo(body.timezone) if body.timezone else timezone.utc
            except ZoneInfoNotFoundError:
                tz = timezone.utc
            start = dt_type.fromisoformat(body.start)
            if start.tzinfo is None:
                start = start.replace(tzinfo=tz)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid start")
    try:
        last, count = preview_recurrence(start, body.recurrence.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"last": last, "count": count}


@router.put("/{uid:path}")
async def put_event(
    uid: str,
    body: EventUpdate,
    entry: SessionEntry = Depends(get_unrestricted_session),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if body.scope not in _RECUR_SCOPES:
        raise HTTPException(status_code=400, detail="Invalid scope")
    cal, account = await _calendar_for(body.calendar_id, entry, db)
    start, end = _resolve_span(body)
    password = decrypt_bytes(account.encrypted_password, account.nonce, entry.dek).decode()

    moved = (
        body.original_calendar_id is not None
        and body.original_calendar_id != body.calendar_id
    )
    # A calendar move recreates a single VEVENT, so it can't carry a series; only
    # whole-event ("all") edits may move.
    if moved and body.scope != "all":
        raise HTTPException(
            status_code=400, detail="Moving an event is only supported for the whole series"
        )
    # Rule (re)builds apply to the whole series or the future split only.
    rrule = (
        body.recurrence.model_dump()
        if body.recurrence and body.scope in ("all", "thisfuture")
        else None
    )

    try:
        if moved:
            # Move across calendars: recreate on the target (same UID) then drop
            # the original. Create first so a failure leaves the source intact.
            assert body.original_calendar_id is not None  # implied by `moved`
            src_cal, src_account = await _calendar_for(body.original_calendar_id, entry, db)
            src_password = decrypt_bytes(
                src_account.encrypted_password, src_account.nonce, entry.dek
            ).decode()
            await create_event(
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
                reminders=_reminder_deltas(body.reminders, body.all_day),
            )
            await delete_event(
                account_url=src_account.url,
                username=src_account.username,
                password=src_password,
                calendar_url=src_cal.caldav_id,
                uid=uid,
            )
        else:
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
                scope=body.scope,
                recurrence_id=body.recurrence_id,
                rrule=rrule,
                reminders=_reminder_deltas(body.reminders, body.all_day),
            )
    except EventNotFoundError:
        raise HTTPException(status_code=404, detail="Event not found")
    except Exception as e:
        logger.warning("event_update_failed", uid=uid, error=repr(e))
        raise HTTPException(status_code=502, detail="Failed to update event on CalDAV server")

    logger.info("event_updated", user_id=entry.user_id, uid=uid, calendar_id=cal.id, moved=moved)
    return {"status": "ok"}


@router.delete("/{uid:path}")
async def delete_event_route(
    uid: str,
    calendar_id: int = Query(...),
    scope: str = Query("all"),
    recurrence_id: str | None = Query(None),
    entry: SessionEntry = Depends(get_unrestricted_session),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if scope not in _RECUR_SCOPES:
        raise HTTPException(status_code=400, detail="Invalid scope")
    cal, account = await _calendar_for(calendar_id, entry, db)

    password = decrypt_bytes(account.encrypted_password, account.nonce, entry.dek).decode()
    try:
        await delete_event(
            account_url=account.url,
            username=account.username,
            password=password,
            calendar_url=cal.caldav_id,
            uid=uid,
            scope=scope,
            recurrence_id=recurrence_id,
        )
    except EventNotFoundError:
        raise HTTPException(status_code=404, detail="Event not found")
    except Exception as e:
        logger.warning("event_delete_failed", uid=uid, error=repr(e))
        raise HTTPException(status_code=502, detail="Failed to delete event on CalDAV server")

    logger.info("event_deleted", user_id=entry.user_id, uid=uid, calendar_id=cal.id)
    return {"status": "ok"}
