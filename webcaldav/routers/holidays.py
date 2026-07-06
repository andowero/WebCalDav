"""Out-of-work-day coloring data for the calendar UI.

Returns the holidays and weekend days for the active user's selected country
over a date range. Pure local computation (see ``webcaldav.holidays``) — no
CalDAV access, no DEK, no network. Same session auth as ``/settings``.
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..deps import get_db, get_unrestricted_session
from ..holidays import (
    WEEKEND_NAME_KEY,
    holidays_for_range,
    weekend_days,
)
from ..models import UserSettings
from ..session import SessionEntry

router = APIRouter(prefix="/holidays", tags=["holidays"])


@router.get("")
async def get_holidays(
    from_: str = Query(..., alias="from"),
    to: str = Query(...),
    entry: SessionEntry = Depends(get_unrestricted_session),
    db: AsyncSession = Depends(get_db),
) -> dict[str, list[dict[str, str]]]:
    """Holidays + weekend days for the user's country in ``[from, to]``.

    ``days`` is sorted by date. Each entry: ``{date, kind, name_key}`` where
    ``kind`` is ``holiday`` or ``weekend`` and ``name_key`` resolves to a
    localized label client-side via the i18n catalog. When the feature is off
    or the country is ``none``, ``days`` is empty.
    """
    result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == entry.user_id)
    )
    s = result.scalar_one_or_none()
    enabled = bool(s and s.holidays_enabled)
    country = (s.holidays_country if s else "none") or "none"

    if not enabled or country == "none":
        return {"days": []}

    try:
        start = date.fromisoformat(from_)
        end = date.fromisoformat(to)
    except ValueError:
        return {"days": []}

    if end < start:
        return {"days": []}

    holidays = holidays_for_range(country, start.isoformat(), end.isoformat())
    wknd = weekend_days(country)

    out: list[dict[str, str]] = []
    cur = start
    while cur <= end:
        # Python weekday(): Mon=0..Sun=6. Convert to JS/FC 0=Sun..6=Sat.
        js_dow = (cur.weekday() + 1) % 7
        iso = cur.isoformat()
        if iso in holidays:
            out.append({"date": iso, "kind": "holiday", "name_key": holidays[iso]})
        elif js_dow in wknd:
            out.append({"date": iso, "kind": "weekend", "name_key": WEEKEND_NAME_KEY})
        cur += timedelta(days=1)
    return {"days": out}
