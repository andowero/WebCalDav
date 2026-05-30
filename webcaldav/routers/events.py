import asyncio
import logging
from datetime import date, timedelta
from datetime import datetime as dt_type

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..caldav_client import fetch_events
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
