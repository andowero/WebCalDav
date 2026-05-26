from typing import AsyncGenerator

from fastapi import Cookie, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_session_factory
from .session import SessionEntry, SessionStore

_store: SessionStore | None = None


def init_session_store(idle_timeout_seconds: int = 3600) -> SessionStore:
    global _store
    _store = SessionStore(idle_timeout_seconds=idle_timeout_seconds)
    return _store


def get_session_store() -> SessionStore:
    assert _store is not None, "Session store not initialised"
    return _store


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
