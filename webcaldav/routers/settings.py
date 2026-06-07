from fastapi import APIRouter, Cookie, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..deps import get_db, get_session_store, get_unrestricted_session
from ..models import UserSettings
from ..session import SessionEntry, SessionStore

router = APIRouter(prefix="/settings", tags=["settings"])

# Reject absurdly short timeouts (would log users out mid-action).
MIN_AUTO_LOGOUT_SECONDS = 60


class SettingsOut(BaseModel):
    timezone: str
    first_day_of_week: int
    time_format: str
    date_format: str
    auto_logout_enabled: bool
    auto_logout_timeout_seconds: int


class SettingsIn(BaseModel):
    timezone: str | None = None
    first_day_of_week: int | None = None
    time_format: str | None = None
    date_format: str | None = None
    auto_logout_enabled: bool | None = None
    auto_logout_timeout_seconds: int | None = None


def _to_out(s: UserSettings) -> SettingsOut:
    return SettingsOut(
        timezone=s.timezone,
        first_day_of_week=s.first_day_of_week,
        time_format=s.time_format,
        date_format=s.date_format,
        auto_logout_enabled=s.auto_logout_enabled,
        auto_logout_timeout_seconds=s.auto_logout_timeout_seconds,
    )


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
            auto_logout_enabled=True,
            auto_logout_timeout_seconds=3600,
        )
    return _to_out(s)


@router.put("")
async def put_settings(
    body: SettingsIn,
    session_id: str | None = Cookie(default=None),
    entry: SessionEntry = Depends(get_unrestricted_session),
    db: AsyncSession = Depends(get_db),
    store: SessionStore = Depends(get_session_store),
) -> SettingsOut:
    if (
        body.auto_logout_timeout_seconds is not None
        and body.auto_logout_timeout_seconds < MIN_AUTO_LOGOUT_SECONDS
    ):
        raise HTTPException(
            status_code=422,
            detail=f"auto_logout_timeout_seconds must be >= {MIN_AUTO_LOGOUT_SECONDS}",
        )

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
    if body.auto_logout_enabled is not None:
        s.auto_logout_enabled = body.auto_logout_enabled
    if body.auto_logout_timeout_seconds is not None:
        s.auto_logout_timeout_seconds = body.auto_logout_timeout_seconds

    await db.commit()

    # Apply auto-logout change to the live session immediately (no re-login).
    if session_id:
        idle_timeout = None if not s.auto_logout_enabled else s.auto_logout_timeout_seconds
        store.update(session_id, idle_timeout=idle_timeout)

    return _to_out(s)
