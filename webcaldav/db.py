from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from .models import Base

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_engine(url: str) -> AsyncEngine:
    global _engine, _session_factory
    _engine = create_async_engine(url, echo=False)

    @event.listens_for(_engine.sync_engine, "connect")
    def set_wal_mode(dbapi_conn, _record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_engine() -> AsyncEngine:
    assert _engine is not None, "Engine not initialised — call init_engine() first"
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    assert _session_factory is not None, "DB not initialised"
    return _session_factory


# Per-user KDF param columns added after initial release. Defaults are the
# argon2 params every pre-migration user was provisioned with.
_USERS_KDF_MIGRATION = {
    "kdf_time_cost": 3,
    "kdf_memory_cost": 65536,
    "kdf_parallelism": 1,
}


async def create_tables() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        existing = {
            row[1] for row in (await conn.execute(text("PRAGMA table_info(users)"))).fetchall()
        }
        for column, legacy_default in _USERS_KDF_MIGRATION.items():
            if column not in existing:
                await conn.execute(
                    text(
                        f"ALTER TABLE users ADD COLUMN {column} INTEGER "
                        f"NOT NULL DEFAULT {legacy_default}"
                    )
                )
