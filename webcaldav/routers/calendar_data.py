import asyncio
from datetime import timezone
from datetime import datetime as dt_type
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..caldav_client import CalendarRef, fetch_account_data
from ..crypto import decrypt_bytes
from ..deps import get_db, get_unrestricted_session
from ..models import Calendar, CalDAVAccount
from ..session import SessionEntry
from .events import _dummy_events, _parse_dt

logger = structlog.get_logger()

router = APIRouter(prefix="/calendar-data", tags=["calendar-data"])

_ALL_KINDS = ("events", "tasks", "journals")


@router.get("")
async def get_calendar_data(
    entry: SessionEntry = Depends(get_unrestricted_session),
    db: AsyncSession = Depends(get_db),
    from_: str | None = Query(None, alias="from"),
    to: str | None = None,
    kinds: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Events, tasks and journals for the user's enabled calendars in one shot.

    Replaces the three separate /events + /tasks + /journals view-load requests:
    calendars are grouped by account so a single keep-alive connection serves all
    of that account's calendars and all requested item kinds.
    """
    requested = frozenset(
        k for k in (kinds.split(",") if kinds else _ALL_KINDS) if k in _ALL_KINDS
    )

    result = await db.execute(
        select(Calendar, CalDAVAccount)
        .join(CalDAVAccount, Calendar.caldav_account_id == CalDAVAccount.id)
        .where(CalDAVAccount.user_id == entry.user_id, Calendar.enabled == True)  # noqa: E712
    )
    rows = result.all()

    out: dict[str, list[dict[str, Any]]] = {"events": [], "tasks": [], "journals": []}
    if not rows:
        # Preserve the welcome screen the standalone /events endpoint shows.
        if "events" in requested:
            out["events"] = _dummy_events()
        return out

    from_dt = _parse_dt(from_)
    to_dt = _parse_dt(to)
    if from_dt is None or to_dt is None:
        now = dt_type.now(timezone.utc)
        from_dt = from_dt or now.replace(day=1)
        to_dt = to_dt or now

    # Group calendars by account so each account opens exactly one client.
    by_account: dict[int, tuple[CalDAVAccount, list[CalendarRef]]] = {}
    for cal, account in rows:
        if account.id not in by_account:
            by_account[account.id] = (account, [])
        by_account[account.id][1].append(
            CalendarRef(calendar_url=cal.caldav_id, color=cal.color, calendar_id=cal.id)
        )

    jobs = []
    accounts: list[CalDAVAccount] = []
    for account, refs in by_account.values():
        password = decrypt_bytes(account.encrypted_password, account.nonce, entry.dek).decode()
        accounts.append(account)
        jobs.append(fetch_account_data(
            account_url=account.url,
            username=account.username,
            password=password,
            calendars=refs,
            from_dt=from_dt,
            to_dt=to_dt,
            kinds=requested,
        ))

    results = await asyncio.gather(*jobs, return_exceptions=True)
    for account, res in zip(accounts, results):
        if isinstance(res, BaseException):
            logger.warning("calendar_data_fetch_failed", account_id=account.id, error=repr(res))
            continue
        for kind in _ALL_KINDS:
            out[kind].extend(res.get(kind, []))

    logger.info(
        "calendar_data_done",
        user_id=entry.user_id,
        accounts=len(accounts),
        events=len(out["events"]),
        tasks=len(out["tasks"]),
        journals=len(out["journals"]),
    )
    return out
