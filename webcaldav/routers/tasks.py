import asyncio
import uuid
from datetime import date, timezone
from datetime import datetime as dt_type
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..caldav_client import (
    EventNotFoundError,
    create_task,
    delete_task,
    fetch_tasks,
    set_task_status,
    update_task,
)
from ..crypto import decrypt_bytes
from ..deps import get_db, get_unrestricted_session
from ..models import Calendar, CalDAVAccount
from ..session import SessionEntry
# Tasks (VTODO) reuse the event router's recurrence/reminder primitives verbatim
# so both kinds share one validation and conversion path.
from .events import (
    _RECUR_SCOPES,
    _RESET_FIELDS,
    _TIME_RE,
    RecurrenceRule,
    Reminder,
    _calendar_for,
    _parse_dt,
    _reminder_deltas,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/tasks", tags=["tasks"])


class TaskUpdate(BaseModel):
    calendar_id: int
    original_calendar_id: int | None = None
    title: str = Field(default="", max_length=8000)
    all_day: bool = False
    # Both optional: a VTODO may carry DTSTART, DUE, both, or neither (undated).
    start: str | None = None
    due: str | None = None
    location: str | None = Field(default=None, max_length=8000)
    description: str | None = Field(default=None, max_length=8000)
    priority: int | None = Field(default=None, ge=0, le=9)
    timezone: str | None = None
    scope: str = "all"
    recurrence_id: str | None = None
    recurrence: RecurrenceRule | None = None
    reminders: list[Reminder] | None = Field(default=None, max_length=10)
    reset_overrides: bool = False
    reset_fields: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> "TaskUpdate":
        self.reset_fields = [f for f in self.reset_fields if f in _RESET_FIELDS]
        for r in self.reminders or []:
            if self.all_day:
                if r.unit not in ("days", "weeks"):
                    raise ValueError("all-day reminders must use days or weeks")
                if r.time is None or not _TIME_RE.match(r.time):
                    raise ValueError("all-day reminders need a time (HH:MM)")
            elif r.time is not None:
                raise ValueError("timed-task reminders must not set a time")
        if self.recurrence is not None and not (self.start or self.due):
            raise ValueError("a recurring task needs a start or due date")
        return self


class StatusToggle(BaseModel):
    calendar_id: int
    completed: bool
    recurrence_id: str | None = None


def _resolve_task_span(
    body: TaskUpdate,
) -> tuple[date | dt_type | None, date | dt_type | None]:
    """Parse the request's start/due into the date/datetime values stored on the
    server. Either side may be ``None``. Unlike events, an all-day DUE is the
    deadline day itself and is stored as-is (not made exclusive)."""
    if body.all_day:
        try:
            start: date | dt_type | None = (
                date.fromisoformat(body.start[:10]) if body.start else None
            )
            due: date | dt_type | None = (
                date.fromisoformat(body.due[:10]) if body.due else None
            )
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid all-day dates")
        return start, due

    try:
        tz = ZoneInfo(body.timezone) if body.timezone else timezone.utc
    except ZoneInfoNotFoundError:
        tz = timezone.utc

    def _one(raw: str | None) -> dt_type | None:
        if not raw:
            return None
        try:
            d = dt_type.fromisoformat(raw)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid datetime")
        return d.replace(tzinfo=tz) if d.tzinfo is None else d.astimezone(tz)

    return _one(body.start), _one(body.due)


@router.get("")
async def get_tasks(
    entry: SessionEntry = Depends(get_unrestricted_session),
    db: AsyncSession = Depends(get_db),
    from_: str | None = Query(None, alias="from"),
    to: str | None = None,
) -> list[dict[str, Any]]:
    result = await db.execute(
        select(Calendar, CalDAVAccount)
        .join(CalDAVAccount, Calendar.caldav_account_id == CalDAVAccount.id)
        .where(CalDAVAccount.user_id == entry.user_id, Calendar.enabled == True)  # noqa: E712
    )
    rows = result.all()
    if not rows:
        return []

    from_dt = _parse_dt(from_)
    to_dt = _parse_dt(to)
    if from_dt is None or to_dt is None:
        now = dt_type.now(timezone.utc)
        from_dt = from_dt or now.replace(day=1)
        to_dt = to_dt or now

    jobs = []
    for cal, account in rows:
        password = decrypt_bytes(account.encrypted_password, account.nonce, entry.dek).decode()
        jobs.append(fetch_tasks(
            account_url=account.url,
            username=account.username,
            password=password,
            calendar_url=cal.caldav_id,
            from_dt=from_dt,
            to_dt=to_dt,
            color=cal.color,
            calendar_id=cal.id,
        ))

    results = await asyncio.gather(*jobs, return_exceptions=True)
    tasks: list[dict[str, Any]] = []
    for i, res in enumerate(results):
        cal, account = rows[i]
        if isinstance(res, BaseException):
            logger.warning("caldav_fetch_tasks_failed", calendar_id=cal.id, error=repr(res))
        else:
            tasks.extend(res)
    logger.info("tasks_fetch_done", user_id=entry.user_id, total=len(tasks))
    return tasks


@router.post("")
async def post_task(
    body: TaskUpdate,
    entry: SessionEntry = Depends(get_unrestricted_session),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    cal, account = await _calendar_for(body.calendar_id, entry, db)
    start, due = _resolve_task_span(body)
    uid = f"{uuid.uuid4()}@webcaldav"
    rrule = body.recurrence.model_dump() if body.recurrence else None
    password = decrypt_bytes(account.encrypted_password, account.nonce, entry.dek).decode()
    try:
        await create_task(
            account_url=account.url,
            username=account.username,
            password=password,
            calendar_url=cal.caldav_id,
            uid=uid,
            title=body.title,
            start=start,
            due=due,
            location=body.location,
            description=body.description,
            rrule=rrule,
            reminders=_reminder_deltas(body.reminders, body.all_day),
            priority=body.priority,
        )
    except Exception as e:
        logger.warning("task_create_failed", error=repr(e))
        raise HTTPException(status_code=502, detail="Failed to create task on CalDAV server")
    logger.info("task_created", user_id=entry.user_id, uid=uid, calendar_id=cal.id)
    return {"status": "ok", "id": uid}


@router.put("/{uid:path}")
async def put_task(
    uid: str,
    body: TaskUpdate,
    entry: SessionEntry = Depends(get_unrestricted_session),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if body.scope not in _RECUR_SCOPES:
        raise HTTPException(status_code=400, detail="Invalid scope")
    cal, account = await _calendar_for(body.calendar_id, entry, db)
    start, due = _resolve_task_span(body)
    password = decrypt_bytes(account.encrypted_password, account.nonce, entry.dek).decode()

    moved = (
        body.original_calendar_id is not None
        and body.original_calendar_id != body.calendar_id
    )
    if moved and body.scope != "all":
        raise HTTPException(
            status_code=400, detail="Moving a task is only supported for the whole series"
        )
    rrule = (
        body.recurrence.model_dump()
        if body.recurrence and body.scope in ("all", "thisfuture")
        else None
    )
    try:
        if moved:
            assert body.original_calendar_id is not None
            src_cal, src_account = await _calendar_for(body.original_calendar_id, entry, db)
            src_password = decrypt_bytes(
                src_account.encrypted_password, src_account.nonce, entry.dek
            ).decode()
            await create_task(
                account_url=account.url,
                username=account.username,
                password=password,
                calendar_url=cal.caldav_id,
                uid=uid,
                title=body.title,
                start=start,
                due=due,
                location=body.location,
                description=body.description,
                rrule=rrule,
                reminders=_reminder_deltas(body.reminders, body.all_day),
                priority=body.priority,
            )
            await delete_task(
                account_url=src_account.url,
                username=src_account.username,
                password=src_password,
                calendar_url=src_cal.caldav_id,
                uid=uid,
            )
        else:
            await update_task(
                account_url=account.url,
                username=account.username,
                password=password,
                calendar_url=cal.caldav_id,
                uid=uid,
                title=body.title,
                start=start,
                due=due,
                location=body.location,
                description=body.description,
                scope=body.scope,
                recurrence_id=body.recurrence_id,
                rrule=rrule,
                reminders=_reminder_deltas(body.reminders, body.all_day),
                priority=body.priority,
                reset_overrides=body.reset_overrides,
                reset_fields=body.reset_fields,
            )
    except EventNotFoundError:
        raise HTTPException(status_code=404, detail="Task not found")
    except Exception as e:
        logger.warning("task_update_failed", uid=uid, error=repr(e))
        raise HTTPException(status_code=502, detail="Failed to update task on CalDAV server")
    logger.info("task_updated", user_id=entry.user_id, uid=uid, calendar_id=cal.id, moved=moved)
    return {"status": "ok"}


@router.post("/{uid:path}/status")
async def toggle_task_status(
    uid: str,
    body: StatusToggle,
    entry: SessionEntry = Depends(get_unrestricted_session),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    cal, account = await _calendar_for(body.calendar_id, entry, db)
    password = decrypt_bytes(account.encrypted_password, account.nonce, entry.dek).decode()
    try:
        await set_task_status(
            account_url=account.url,
            username=account.username,
            password=password,
            calendar_url=cal.caldav_id,
            uid=uid,
            completed=body.completed,
            recurrence_id=body.recurrence_id,
        )
    except EventNotFoundError:
        raise HTTPException(status_code=404, detail="Task not found")
    except Exception as e:
        logger.warning("task_status_failed", uid=uid, error=repr(e))
        raise HTTPException(status_code=502, detail="Failed to update task on CalDAV server")
    logger.info("task_status_set", user_id=entry.user_id, uid=uid, completed=body.completed)
    return {"status": "ok"}


@router.delete("/{uid:path}")
async def delete_task_route(
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
        await delete_task(
            account_url=account.url,
            username=account.username,
            password=password,
            calendar_url=cal.caldav_id,
            uid=uid,
            scope=scope,
            recurrence_id=recurrence_id,
        )
    except EventNotFoundError:
        raise HTTPException(status_code=404, detail="Task not found")
    except Exception as e:
        logger.warning("task_delete_failed", uid=uid, error=repr(e))
        raise HTTPException(status_code=502, detail="Failed to delete task on CalDAV server")
    logger.info("task_deleted", user_id=entry.user_id, uid=uid, calendar_id=cal.id)
    return {"status": "ok"}
