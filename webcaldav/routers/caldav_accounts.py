import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..crypto import decrypt_bytes, encrypt_bytes
from ..deps import get_db, get_unrestricted_session
from ..models import CalDAVAccount, Calendar
from ..session import SessionEntry

logger = structlog.get_logger()

router = APIRouter(prefix="/caldav-accounts", tags=["caldav-accounts"])


class CalDAVAccountIn(BaseModel):
    url: str
    username: str
    password: str
    display_name: str | None = None


class CalDAVAccountOut(BaseModel):
    id: int
    url: str
    username: str
    created_at: str


@router.get("")
async def list_accounts(
    entry: SessionEntry = Depends(get_unrestricted_session),
    db: AsyncSession = Depends(get_db),
) -> list[CalDAVAccountOut]:
    result = await db.execute(
        select(CalDAVAccount).where(CalDAVAccount.user_id == entry.user_id)
    )
    accounts = result.scalars().all()
    return [
        CalDAVAccountOut(
            id=a.id,
            url=a.url,
            username=a.username,
            created_at=a.created_at.isoformat(),
        )
        for a in accounts
    ]


@router.post("", status_code=201)
async def create_account(
    body: CalDAVAccountIn,
    entry: SessionEntry = Depends(get_unrestricted_session),
    db: AsyncSession = Depends(get_db),
) -> CalDAVAccountOut:
    encrypted_pw, nonce = encrypt_bytes(body.password.encode("utf-8"), entry.dek)
    account = CalDAVAccount(
        user_id=entry.user_id,
        url=body.url.rstrip("/"),
        username=body.username,
        encrypted_password=encrypted_pw,
        nonce=nonce,
    )
    db.add(account)
    await db.flush()

    display = body.display_name or body.url
    calendar = Calendar(
        caldav_account_id=account.id,
        caldav_id="default",
        display_name=display,
        color="#3788d8",
        enabled=True,
    )
    db.add(calendar)
    await db.commit()
    await db.refresh(account)

    logger.info("caldav_account_created", user_id=entry.user_id, account_id=account.id)
    return CalDAVAccountOut(
        id=account.id,
        url=account.url,
        username=account.username,
        created_at=account.created_at.isoformat(),
    )


@router.delete("/{account_id}", status_code=204)
async def delete_account(
    account_id: int,
    entry: SessionEntry = Depends(get_unrestricted_session),
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(
        select(CalDAVAccount).where(
            CalDAVAccount.id == account_id,
            CalDAVAccount.user_id == entry.user_id,
        )
    )
    account = result.scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    await db.delete(account)
    await db.commit()
