"""User-facing CRUD for MCP API tokens (settings panel).

Creating a token requires the MCP server to be enabled and an active session
(the session's DEK is sealed into the token). Listing and revoking always work,
so a user can clean up tokens even after the server is turned off.
"""
from datetime import UTC, datetime
from typing import Any, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..deps import get_db, get_unrestricted_session
from ..models import APIToken, APITokenCalendar, Calendar, CalDAVAccount
from ..session import SessionEntry
from ..tokens import mint_token

logger = structlog.get_logger()

router = APIRouter(prefix="/api-tokens", tags=["api-tokens"])


class TokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    mode: Literal["ro", "rw"]
    all_calendars: bool = True
    calendar_ids: list[int] | None = None
    expires_at: str | None = None  # ISO 8601; None = never expires


class TokenOut(BaseModel):
    id: int
    name: str
    mode: str
    all_calendars: bool
    calendar_ids: list[int]
    expires_at: str | None
    created_at: str
    last_used_at: str | None


async def _user_calendar_ids(user_id: int, db: AsyncSession) -> set[int]:
    rows = (
        await db.execute(
            select(Calendar.id)
            .join(CalDAVAccount, Calendar.caldav_account_id == CalDAVAccount.id)
            .where(CalDAVAccount.user_id == user_id)
        )
    ).all()
    return {r[0] for r in rows}


def _to_out(token: APIToken, calendar_ids: list[int]) -> TokenOut:
    return TokenOut(
        id=token.id,
        name=token.name,
        mode=token.mode,
        all_calendars=token.all_calendars,
        calendar_ids=calendar_ids,
        expires_at=token.expires_at.isoformat() if token.expires_at else None,
        created_at=token.created_at.isoformat(),
        last_used_at=token.last_used_at.isoformat() if token.last_used_at else None,
    )


@router.get("")
async def list_tokens(
    entry: SessionEntry = Depends(get_unrestricted_session),
    db: AsyncSession = Depends(get_db),
) -> list[TokenOut]:
    rows = (
        await db.execute(
            select(APIToken)
            .where(APIToken.user_id == entry.user_id)
            .order_by(APIToken.created_at.desc())
        )
    ).scalars().all()
    # Fetch scope rows explicitly (lazy relationship access isn't awaitable).
    out = []
    for t in rows:
        cals = (
            await db.execute(
                select(APITokenCalendar.calendar_id).where(
                    APITokenCalendar.api_token_id == t.id
                )
            )
        ).all()
        out.append(_to_out(t, [c[0] for c in cals]))
    return out


@router.post("")
async def create_token(
    body: TokenCreate,
    entry: SessionEntry = Depends(get_unrestricted_session),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if not settings.mcp_server_enabled:
        raise HTTPException(status_code=403, detail="MCP server is disabled")

    expires_at: datetime | None = None
    if body.expires_at:
        try:
            expires_at = datetime.fromisoformat(body.expires_at)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid expires_at")
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at <= datetime.now(UTC):
            raise HTTPException(status_code=400, detail="expires_at must be in the future")

    scoped_ids: list[int] = []
    if not body.all_calendars:
        scoped_ids = sorted(set(body.calendar_ids or []))
        if not scoped_ids:
            raise HTTPException(
                status_code=400, detail="A scoped token needs at least one calendar"
            )
        owned = await _user_calendar_ids(entry.user_id, db)
        if not set(scoped_ids).issubset(owned):
            raise HTTPException(status_code=400, detail="Unknown calendar in scope")

    full, token_sha256, sealed_blob, blob_nonce = mint_token(
        dek=entry.dek,
        mode=body.mode,
        all_calendars=body.all_calendars,
        calendar_ids=scoped_ids,
        expires_at=expires_at,
    )

    token = APIToken(
        user_id=entry.user_id,
        name=body.name,
        token_sha256=token_sha256,
        sealed_blob=sealed_blob,
        blob_nonce=blob_nonce,
        mode=body.mode,
        all_calendars=body.all_calendars,
        expires_at=expires_at,
    )
    db.add(token)
    await db.flush()
    for cid in scoped_ids:
        db.add(APITokenCalendar(api_token_id=token.id, calendar_id=cid))
    await db.commit()
    await db.refresh(token)

    logger.info(
        "api_token_created",
        user_id=entry.user_id,
        token_id=token.id,
        mode=body.mode,
        all_calendars=body.all_calendars,
    )
    # The plaintext token is returned exactly once and never stored.
    return {"token": full, "info": _to_out(token, scoped_ids).model_dump()}


@router.delete("/{token_id}")
async def revoke_token(
    token_id: int,
    entry: SessionEntry = Depends(get_unrestricted_session),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    token = (
        await db.execute(
            select(APIToken).where(
                APIToken.id == token_id, APIToken.user_id == entry.user_id
            )
        )
    ).scalar_one_or_none()
    if token is None:
        raise HTTPException(status_code=404, detail="Token not found")
    await db.delete(token)
    await db.commit()
    logger.info("api_token_revoked", user_id=entry.user_id, token_id=token_id)
    return {"status": "ok"}
