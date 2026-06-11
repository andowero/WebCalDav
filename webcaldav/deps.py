from typing import AsyncGenerator

from fastapi import Cookie, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_session_factory
from .ratelimit import LoginRateLimiter
from .session import SessionEntry, SessionStore

_store: SessionStore | None = None
_login_rate_limiter: LoginRateLimiter | None = None


def init_session_store(idle_timeout_seconds: int = 3600) -> SessionStore:
    global _store
    _store = SessionStore(idle_timeout_seconds=idle_timeout_seconds)
    return _store


def get_session_store() -> SessionStore:
    assert _store is not None, "Session store not initialised"
    return _store


def init_login_rate_limiter(max_attempts: int, window_seconds: int) -> LoginRateLimiter:
    global _login_rate_limiter
    _login_rate_limiter = LoginRateLimiter(max_attempts=max_attempts, window_seconds=window_seconds)
    return _login_rate_limiter


def get_login_rate_limiter() -> LoginRateLimiter:
    assert _login_rate_limiter is not None, "Login rate limiter not initialised"
    return _login_rate_limiter


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with get_session_factory()() as session:
        yield session


async def get_current_session(
    session_id: str | None = Cookie(default=None),
    store: SessionStore = Depends(get_session_store),
) -> SessionEntry:
    if not session_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    entry = store.get(session_id)
    if entry is None:
        raise HTTPException(status_code=401, detail="Session expired or invalid")
    return entry


async def get_unrestricted_session(
    entry: SessionEntry = Depends(get_current_session),
) -> SessionEntry:
    if entry.restricted:
        raise HTTPException(status_code=403, detail="Password change required")
    return entry
