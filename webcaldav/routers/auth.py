import hmac
import logging
import os

import structlog
from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..crypto import derive_kek, generate_dek, make_verifier, unwrap_dek, verify_kek, wrap_dek
from ..deps import get_current_session, get_db, get_session_store
from ..metrics import active_sessions
from ..models import User
from ..session import SessionEntry, SessionStore

logger = structlog.get_logger()

router = APIRouter(prefix="/auth", tags=["auth"])

_DUMMY_SALT = bytes(32)
_DUMMY_VERIFIER = bytes(32)


class LoginRequest(BaseModel):
    email: str
    password: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


@router.post("/login")
async def login(
    req: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    store: SessionStore = Depends(get_session_store),
) -> dict:
    result = await db.execute(select(User).where(User.email == req.email))
    user = result.scalar_one_or_none()

    kdf_salt = user.kdf_salt if user else _DUMMY_SALT
    kek = derive_kek(
        req.password,
        kdf_salt,
        time_cost=settings.argon2_time_cost,
        memory_cost=settings.argon2_memory_cost,
        parallelism=settings.argon2_parallelism,
    )

    stored_verifier = user.password_verifier if user else _DUMMY_VERIFIER
    candidate_verifier = make_verifier(kek)

    if not hmac.compare_digest(candidate_verifier, stored_verifier) or user is None:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    try:
        dek = unwrap_dek(user.wrapped_dek, user.dek_nonce, kek)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    session_id = store.create(user.id, dek, user.must_change_password)
    active_sessions.set(store.active_count)

    logger.info("login", user_id=user.id, restricted=user.must_change_password)

    response.set_cookie(
        "session_id",
        session_id,
        httponly=True,
        samesite="lax",
        secure=False,
    )
    return {"must_change_password": user.must_change_password}


@router.post("/logout")
async def logout(
    response: Response,
    session_id: str | None = Cookie(default=None),
    store: SessionStore = Depends(get_session_store),
) -> dict:
    if session_id:
        store.delete(session_id)
        active_sessions.set(store.active_count)
    response.delete_cookie("session_id")
    return {"ok": True}


@router.post("/change-password")
async def change_password(
    req: ChangePasswordRequest,
    response: Response,
    session_id: str | None = Cookie(default=None),
    entry: SessionEntry = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
    store: SessionStore = Depends(get_session_store),
) -> dict:
    result = await db.execute(select(User).where(User.id == entry.user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    old_kek = derive_kek(
        req.old_password,
        user.kdf_salt,
        time_cost=settings.argon2_time_cost,
        memory_cost=settings.argon2_memory_cost,
        parallelism=settings.argon2_parallelism,
    )
    if not verify_kek(old_kek, user.password_verifier):
        raise HTTPException(status_code=401, detail="Current password is incorrect")

    try:
        dek = unwrap_dek(user.wrapped_dek, user.dek_nonce, old_kek)
    except Exception:
        raise HTTPException(status_code=401, detail="Current password is incorrect")

    new_kdf_salt = os.urandom(32)
    new_kek = derive_kek(
        req.new_password,
        new_kdf_salt,
        time_cost=settings.argon2_time_cost,
        memory_cost=settings.argon2_memory_cost,
        parallelism=settings.argon2_parallelism,
    )
    new_wrapped_dek, new_dek_nonce = wrap_dek(dek, new_kek)
    new_verifier = make_verifier(new_kek)

    user.kdf_salt = new_kdf_salt
    user.wrapped_dek = new_wrapped_dek
    user.dek_nonce = new_dek_nonce
    user.password_verifier = new_verifier
    user.must_change_password = False
    await db.commit()

    if session_id:
        store.update(session_id, dek=dek, restricted=False)

    logger.info("password_changed", user_id=user.id)
    return {"ok": True}
