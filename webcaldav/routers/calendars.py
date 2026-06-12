import asyncio

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..caldav_client import fetch_sync_token
from ..crypto import decrypt_bytes
from ..deps import get_db, get_unrestricted_session
from ..models import Calendar, CalDAVAccount
from ..session import SessionEntry

logger = structlog.get_logger()

router = APIRouter(prefix="/calendars", tags=["calendars"])


class CalendarOut(BaseModel):
    id: int
    caldav_account_id: int
    caldav_id: str
    display_name: str
    color: str
    enabled: bool
    is_default: bool


class CalendarPatch(BaseModel):
    color: str | None = None
    enabled: bool | None = None
    is_default: bool | None = None


@router.get("")
async def list_calendars(
    entry: SessionEntry = Depends(get_unrestricted_session),
    db: AsyncSession = Depends(get_db),
) -> list[CalendarOut]:
    result = await db.execute(
        select(Calendar)
        .join(CalDAVAccount, Calendar.caldav_account_id == CalDAVAccount.id)
        .where(CalDAVAccount.user_id == entry.user_id)
    )
    calendars = result.scalars().all()
    return [
        CalendarOut(
            id=c.id,
            caldav_account_id=c.caldav_account_id,
            caldav_id=c.caldav_id,
            display_name=c.display_name,
            color=c.color,
            enabled=c.enabled,
            is_default=c.is_default,
        )
        for c in calendars
    ]


@router.get("/ctags")
async def calendar_ctags(
    entry: SessionEntry = Depends(get_unrestricted_session),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Per-calendar change-detection tokens for enabled calendars.

    The browser-notification scheduler polls this and only refetches events for
    calendars whose token changed. Calendars that error out are omitted so the
    client treats them as "changed" and refetches. Keys are calendar ids (str).
    """
    result = await db.execute(
        select(Calendar, CalDAVAccount)
        .join(CalDAVAccount, Calendar.caldav_account_id == CalDAVAccount.id)
        .where(CalDAVAccount.user_id == entry.user_id, Calendar.enabled == True)  # noqa: E712
    )
    rows = result.all()

    tasks = []
    for cal, account in rows:
        password = decrypt_bytes(account.encrypted_password, account.nonce, entry.dek).decode()
        tasks.append(
            fetch_sync_token(
                account_url=account.url,
                username=account.username,
                password=password,
                calendar_url=cal.caldav_id,
            )
        )

    results = await asyncio.gather(*tasks, return_exceptions=True)

    tokens: dict[str, str] = {}
    for (cal, account), res in zip(rows, results):
        if isinstance(res, BaseException):
            logger.warning(
                "caldav_ctag_failed", calendar_id=cal.id, error=repr(res)
            )
        else:
            tokens[str(cal.id)] = res
    return tokens


@router.patch("/{calendar_id}")
async def patch_calendar(
    calendar_id: int,
    body: CalendarPatch,
    entry: SessionEntry = Depends(get_unrestricted_session),
    db: AsyncSession = Depends(get_db),
) -> CalendarOut:
    result = await db.execute(
        select(Calendar)
        .join(CalDAVAccount, Calendar.caldav_account_id == CalDAVAccount.id)
        .where(Calendar.id == calendar_id, CalDAVAccount.user_id == entry.user_id)
    )
    cal = result.scalar_one_or_none()
    if cal is None:
        raise HTTPException(status_code=404, detail="Calendar not found")

    if body.color is not None:
        cal.color = body.color
    if body.enabled is not None:
        cal.enabled = body.enabled
    if body.is_default is not None:
        if body.is_default:
            # At most one default per user; clear the others.
            others = await db.execute(
                select(Calendar)
                .join(CalDAVAccount, Calendar.caldav_account_id == CalDAVAccount.id)
                .where(
                    CalDAVAccount.user_id == entry.user_id,
                    Calendar.id != cal.id,
                    Calendar.is_default == True,  # noqa: E712
                )
            )
            for other in others.scalars().all():
                other.is_default = False
        cal.is_default = body.is_default
    await db.commit()

    return CalendarOut(
        id=cal.id,
        caldav_account_id=cal.caldav_account_id,
        caldav_id=cal.caldav_id,
        display_name=cal.display_name,
        color=cal.color,
        enabled=cal.enabled,
        is_default=cal.is_default,
    )
