from typing import Any

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from .models import Base

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_engine(url: str) -> AsyncEngine:
    global _engine, _session_factory
    _engine = create_async_engine(url, echo=False)

    @event.listens_for(_engine.sync_engine, "connect")
    def set_wal_mode(dbapi_conn: Any, _record: Any) -> None:
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

# Columns added to user_settings after initial release. create_all won't alter
# an existing table, so add missing columns explicitly for pre-migration DBs.
_USER_SETTINGS_MIGRATION = {
    "notifications_enabled": ("BOOLEAN", 0),
    # TEXT columns: the legacy default is interpolated raw, so quote it.
    "completed_task_display": ("TEXT", "'hidden'"),
    "undated_task_display": ("TEXT", "'agenda'"),
    "theme": ("TEXT", "'system'"),
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
        settings_existing = {
            row[1]
            for row in (
                await conn.execute(text("PRAGMA table_info(user_settings)"))
            ).fetchall()
        }
        for column, (sql_type, settings_default) in _USER_SETTINGS_MIGRATION.items():
            if column not in settings_existing:
                await conn.execute(
                    text(
                        f"ALTER TABLE user_settings ADD COLUMN {column} {sql_type} "
                        f"NOT NULL DEFAULT {settings_default}"
                    )
                )
