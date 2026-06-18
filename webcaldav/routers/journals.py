import asyncio
import uuid
from datetime import date, timezone
from datetime import datetime as dt_type
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..caldav_client import (
    EventNotFoundError,
    create_journal,
    delete_journal,
    fetch_journals,
    update_journal,
)
from ..crypto import decrypt_bytes
from ..deps import get_db, get_unrestricted_session
from ..models import Calendar, CalDAVAccount
from ..session import SessionEntry
# Journals (VJOURNAL) reuse the event router's calendar lookup and date parser.
# They carry no recurrence/reminders/end, so the rest of the surface is trimmed.
from .events import _calendar_for, _parse_dt

logger = structlog.get_logger()

router = APIRouter(prefix="/journals", tags=["journals"])


class JournalUpdate(BaseModel):
    calendar_id: int
    # Set on edit when the user moves the journal to a different calendar; the
    # entry is recreated on calendar_id and deleted from original_calendar_id.
    original_calendar_id: int | None = None
    title: str = Field(default="", max_length=8000)
    all_day: bool = True
    # A single anchor date (all-day) or datetime. No end — VJOURNAL has none.
    start: str
    # Markdown body. Generous limit: journal entries can be long.
    description: str | None = Field(default=None, max_length=100000)
    timezone: str | None = None


def _resolve_journal_start(body: JournalUpdate) -> date | dt_type:
    """Parse the request's start into the date/datetime stored on the server."""
    if body.all_day:
        try:
            return date.fromisoformat(body.start[:10])
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid all-day date")
    try:
        tz = ZoneInfo(body.timezone) if body.timezone else timezone.utc
    except ZoneInfoNotFoundError:
        tz = timezone.utc
    try:
        d = dt_type.fromisoformat(body.start)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid datetime")
    return d.replace(tzinfo=tz) if d.tzinfo is None else d.astimezone(tz)


@router.get("")
async def get_journals(
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
        jobs.append(fetch_journals(
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
    journals: list[dict[str, Any]] = []
    for i, res in enumerate(results):
        cal, account = rows[i]
        if isinstance(res, BaseException):
            logger.warning("caldav_fetch_journals_failed", calendar_id=cal.id, error=repr(res))
        else:
            journals.extend(res)
    logger.info("journals_fetch_done", user_id=entry.user_id, total=len(journals))
    return journals


@router.post("")
async def post_journal(
    body: JournalUpdate,
    entry: SessionEntry = Depends(get_unrestricted_session),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    cal, account = await _calendar_for(body.calendar_id, entry, db)
    start = _resolve_journal_start(body)
    uid = f"{uuid.uuid4()}@webcaldav"
    password = decrypt_bytes(account.encrypted_password, account.nonce, entry.dek).decode()
    try:
        await create_journal(
            account_url=account.url,
            username=account.username,
            password=password,
            calendar_url=cal.caldav_id,
            uid=uid,
            title=body.title,
            start=start,
            description=body.description,
        )
    except Exception as e:
        logger.warning("journal_create_failed", error=repr(e))
        raise HTTPException(status_code=502, detail="Failed to create journal on CalDAV server")
    logger.info("journal_created", user_id=entry.user_id, uid=uid, calendar_id=cal.id)
    return {"status": "ok", "id": uid}


@router.put("/{uid:path}")
async def put_journal(
    uid: str,
    body: JournalUpdate,
    entry: SessionEntry = Depends(get_unrestricted_session),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    cal, account = await _calendar_for(body.calendar_id, entry, db)
    start = _resolve_journal_start(body)
    password = decrypt_bytes(account.encrypted_password, account.nonce, entry.dek).decode()

    moved = (
        body.original_calendar_id is not None
        and body.original_calendar_id != body.calendar_id
    )
    try:
        if moved:
            # Move across calendars: recreate on the target (same UID) then drop
            # the original. Create first so a failure leaves the source intact.
            assert body.original_calendar_id is not None
            src_cal, src_account = await _calendar_for(body.original_calendar_id, entry, db)
            src_password = decrypt_bytes(
                src_account.encrypted_password, src_account.nonce, entry.dek
            ).decode()
            await create_journal(
                account_url=account.url,
                username=account.username,
                password=password,
                calendar_url=cal.caldav_id,
                uid=uid,
                title=body.title,
                start=start,
                description=body.description,
            )
            await delete_journal(
                account_url=src_account.url,
                username=src_account.username,
                password=src_password,
                calendar_url=src_cal.caldav_id,
                uid=uid,
            )
        else:
            await update_journal(
                account_url=account.url,
                username=account.username,
                password=password,
                calendar_url=cal.caldav_id,
                uid=uid,
                title=body.title,
                start=start,
                description=body.description,
            )
    except EventNotFoundError:
        raise HTTPException(status_code=404, detail="Journal not found")
    except Exception as e:
        logger.warning("journal_update_failed", uid=uid, error=repr(e))
        raise HTTPException(status_code=502, detail="Failed to update journal on CalDAV server")
    logger.info("journal_updated", user_id=entry.user_id, uid=uid, calendar_id=cal.id, moved=moved)
    return {"status": "ok"}


@router.delete("/{uid:path}")
async def delete_journal_route(
    uid: str,
    calendar_id: int = Query(...),
    entry: SessionEntry = Depends(get_unrestricted_session),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    cal, account = await _calendar_for(calendar_id, entry, db)
    password = decrypt_bytes(account.encrypted_password, account.nonce, entry.dek).decode()
    try:
        await delete_journal(
            account_url=account.url,
            username=account.username,
            password=password,
            calendar_url=cal.caldav_id,
            uid=uid,
        )
    except EventNotFoundError:
        raise HTTPException(status_code=404, detail="Journal not found")
    except Exception as e:
        logger.warning("journal_delete_failed", uid=uid, error=repr(e))
        raise HTTPException(status_code=502, detail="Failed to delete journal on CalDAV server")
    logger.info("journal_deleted", user_id=entry.user_id, uid=uid, calendar_id=cal.id)
    return {"status": "ok"}
