from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..deps import get_db, get_unrestricted_session
from ..models import Calendar, CalDAVAccount
from ..session import SessionEntry

router = APIRouter(prefix="/calendars", tags=["calendars"])


class CalendarOut(BaseModel):
    id: int
    caldav_account_id: int
    caldav_id: str
    display_name: str
    color: str
    enabled: bool


class CalendarPatch(BaseModel):
    color: str | None = None
    enabled: bool | None = None


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
        )
        for c in calendars
    ]


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
    await db.commit()

    return CalendarOut(
        id=cal.id,
        caldav_account_id=cal.caldav_account_id,
        caldav_id=cal.caldav_id,
        display_name=cal.display_name,
        color=cal.color,
        enabled=cal.enabled,
    )
