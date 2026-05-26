from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..deps import get_db, get_unrestricted_session
from ..models import Calendar, CalDAVAccount
from ..session import SessionEntry

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


@router.get("")
async def get_events(
    entry: SessionEntry = Depends(get_unrestricted_session),
    db: AsyncSession = Depends(get_db),
    from_: str | None = None,
    to: str | None = None,
    calendar_ids: str | None = None,
) -> list[dict]:
    result = await db.execute(
        select(Calendar)
        .join(CalDAVAccount, Calendar.caldav_account_id == CalDAVAccount.id)
        .where(CalDAVAccount.user_id == entry.user_id, Calendar.enabled == True)  # noqa: E712
    )
    calendars = result.scalars().all()

    if not calendars:
        return _dummy_events()

    # Real CalDAV fetching will be implemented in a later milestone.
    return []
