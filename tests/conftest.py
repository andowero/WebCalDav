import asyncio
import os

# Weak argon2 params so tests run fast
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("ARGON2_TIME_COST", "1")
os.environ.setdefault("ARGON2_MEMORY_COST", "1024")
os.environ.setdefault("ARGON2_PARALLELISM", "1")
os.environ.setdefault("SESSION_IDLE_TIMEOUT", "3600")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from webcaldav.app import app
from webcaldav.db import create_tables, get_engine, get_session_factory, init_engine
from webcaldav.deps import get_session_store, init_session_store
from webcaldav.models import Base


@pytest.fixture(scope="function")
async def db_engine():
    engine = init_engine("sqlite+aiosqlite:///:memory:")
    await create_tables()
    yield engine
    await engine.dispose()


@pytest.fixture(scope="function")
async def db_session(db_engine) -> AsyncSession:
    async with get_session_factory()() as session:
        yield session


@pytest.fixture(scope="function")
def store(db_engine):
    return init_session_store(idle_timeout_seconds=3600)


@pytest.fixture(scope="function")
async def client(db_engine, store) -> AsyncClient:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
