from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..deps import get_db, get_unrestricted_session
from ..models import UserSettings
from ..session import SessionEntry

router = APIRouter(prefix="/settings", tags=["settings"])


class SettingsOut(BaseModel):
    timezone: str
    first_day_of_week: int
    time_format: str
    date_format: str


class SettingsIn(BaseModel):
    timezone: str | None = None
    first_day_of_week: int | None = None
    time_format: str | None = None
    date_format: str | None = None


@router.get("")
async def get_settings(
    entry: SessionEntry = Depends(get_unrestricted_session),
    db: AsyncSession = Depends(get_db),
) -> SettingsOut:
    result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == entry.user_id)
    )
    s = result.scalar_one_or_none()
    if s is None:
        return SettingsOut(
            timezone="UTC",
            first_day_of_week=1,
            time_format="24h",
            date_format="YYYY-MM-DD",
        )
    return SettingsOut(
        timezone=s.timezone,
        first_day_of_week=s.first_day_of_week,
        time_format=s.time_format,
        date_format=s.date_format,
    )


@router.put("")
async def put_settings(
    body: SettingsIn,
    entry: SessionEntry = Depends(get_unrestricted_session),
    db: AsyncSession = Depends(get_db),
) -> SettingsOut:
    result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == entry.user_id)
    )
    s = result.scalar_one_or_none()
    if s is None:
        s = UserSettings(
            user_id=entry.user_id,
            timezone="UTC",
            first_day_of_week=1,
            time_format="24h",
            date_format="YYYY-MM-DD",
        )
        db.add(s)

    if body.timezone is not None:
        s.timezone = body.timezone
    if body.first_day_of_week is not None:
        s.first_day_of_week = body.first_day_of_week
    if body.time_format is not None:
        s.time_format = body.time_format
    if body.date_format is not None:
        s.date_format = body.date_format

    await db.commit()
    return SettingsOut(
        timezone=s.timezone,
        first_day_of_week=s.first_day_of_week,
        time_format=s.time_format,
        date_format=s.date_format,
    )
