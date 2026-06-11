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
from webcaldav.deps import get_session_store, init_login_rate_limiter, init_session_store
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
def rate_limiter(db_engine):
    # Fresh limiter per test so failed logins don't leak across tests.
    return init_login_rate_limiter(max_attempts=5, window_seconds=300)


@pytest.fixture(scope="function")
async def client(db_engine, store, rate_limiter) -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        # https so httpx sends the session cookie, which is Secure by default
        base_url="https://test",
        headers={"X-Requested-With": "fetch"},
    ) as c:
        yield c
