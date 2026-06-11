import hmac
import logging
import os

import structlog
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..crypto import derive_kek, generate_dek, make_verifier, unwrap_dek, verify_kek, wrap_dek
from ..deps import get_current_session, get_db, get_login_rate_limiter, get_session_store
from ..metrics import active_sessions
from ..models import User, UserSettings
from ..ratelimit import LoginRateLimiter
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


def _client_ip(request: Request) -> str:
    # Behind the reverse proxy the socket peer is the proxy itself; the real
    # client is the rightmost X-Forwarded-For entry (the one our proxy added).
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


@router.post("/login")
async def login(
    req: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    store: SessionStore = Depends(get_session_store),
    limiter: LoginRateLimiter = Depends(get_login_rate_limiter),
) -> dict:
    # Throttle before the argon2 derivation — each unauthenticated request
    # otherwise costs a full memory-hard hash (CPU/RAM amplification).
    ip = _client_ip(request)
    retry_after = limiter.check(ip)
    if retry_after is not None:
        logger.warning("login_rate_limited", ip=ip)
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts, try again later",
            headers={"Retry-After": str(retry_after)},
        )
    limiter.record(ip)

    result = await db.execute(select(User).where(User.email == req.email))
    user = result.scalar_one_or_none()

    kdf_salt = user.kdf_salt if user else _DUMMY_SALT
    kek = derive_kek(
        req.password,
        kdf_salt,
        time_cost=user.kdf_time_cost if user else settings.argon2_time_cost,
        memory_cost=user.kdf_memory_cost if user else settings.argon2_memory_cost,
        parallelism=user.kdf_parallelism if user else settings.argon2_parallelism,
    )

    stored_verifier = user.password_verifier if user else _DUMMY_VERIFIER
    candidate_verifier = make_verifier(kek)

    if not hmac.compare_digest(candidate_verifier, stored_verifier) or user is None:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    try:
        dek = unwrap_dek(user.wrapped_dek, user.dek_nonce, kek)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    s = (
        await db.execute(select(UserSettings).where(UserSettings.user_id == user.id))
    ).scalar_one_or_none()
    if s is not None and not s.auto_logout_enabled:
        idle_timeout: int | None = None
    elif s is not None:
        idle_timeout = s.auto_logout_timeout_seconds
    else:
        idle_timeout = settings.session_idle_timeout

    limiter.reset(ip)
    session_id = store.create(user.id, dek, user.must_change_password, idle_timeout)
    active_sessions.set(store.active_count)

    logger.info("login", user_id=user.id, restricted=user.must_change_password)

    response.set_cookie(
        "session_id",
        session_id,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
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


@router.get("/session")
async def session_status(
    session_id: str | None = Cookie(default=None),
    store: SessionStore = Depends(get_session_store),
) -> dict:
    """Idle-logout countdown state. Non-refreshing: does NOT reset the timer."""
    if not session_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    status = store.status(session_id)
    if status is None:
        raise HTTPException(status_code=401, detail="Session expired or invalid")
    return {
        "enabled": status.enabled,
        "timeout_seconds": status.timeout_seconds,
        "remaining_seconds": status.remaining_seconds,
    }


@router.post("/change-password")
async def change_password(
    req: ChangePasswordRequest,
    response: Response,
    session_id: str | None = Cookie(default=None),
    entry: SessionEntry = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
    store: SessionStore = Depends(get_session_store),
) -> dict:
    if len(req.new_password) < settings.min_password_length:
        raise HTTPException(
            status_code=400,
            detail=f"New password must be at least {settings.min_password_length} characters",
        )

    result = await db.execute(select(User).where(User.id == entry.user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    old_kek = derive_kek(
        req.old_password,
        user.kdf_salt,
        time_cost=user.kdf_time_cost,
        memory_cost=user.kdf_memory_cost,
        parallelism=user.kdf_parallelism,
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
    user.kdf_time_cost = settings.argon2_time_cost
    user.kdf_memory_cost = settings.argon2_memory_cost
    user.kdf_parallelism = settings.argon2_parallelism
    user.wrapped_dek = new_wrapped_dek
    user.dek_nonce = new_dek_nonce
    user.password_verifier = new_verifier
    user.must_change_password = False
    await db.commit()

    if session_id:
        store.update(session_id, dek=dek, restricted=False)

    logger.info("password_changed", user_id=user.id)
    return {"ok": True}
