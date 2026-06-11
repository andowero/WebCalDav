from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, LargeBinary, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    kdf_salt: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    # Argon2id params the user's KEK was derived with. Stored per user so the
    # global defaults can be hardened without locking out existing users;
    # users pick up new params on their next password change/reset.
    kdf_time_cost: Mapped[int] = mapped_column(Integer, nullable=False)
    kdf_memory_cost: Mapped[int] = mapped_column(Integer, nullable=False)
    kdf_parallelism: Mapped[int] = mapped_column(Integer, nullable=False)
    wrapped_dek: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    dek_nonce: Mapped[bytes] = mapped_column(LargeBinary(12), nullable=False)
    password_verifier: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC), nullable=False)

    caldav_accounts: Mapped[list["CalDAVAccount"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    settings: Mapped["UserSettings | None"] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )


class CalDAVAccount(Base):
    __tablename__ = "caldav_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    url: Mapped[str] = mapped_column(String, nullable=False)
    username: Mapped[str] = mapped_column(String, nullable=False)
    encrypted_password: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    nonce: Mapped[bytes] = mapped_column(LargeBinary(12), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC), nullable=False)

    user: Mapped["User"] = relationship(back_populates="caldav_accounts")
    calendars: Mapped[list["Calendar"]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )


class Calendar(Base):
    __tablename__ = "calendars"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    caldav_account_id: Mapped[int] = mapped_column(ForeignKey("caldav_accounts.id"), nullable=False)
    caldav_id: Mapped[str] = mapped_column(String, nullable=False)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    color: Mapped[str] = mapped_column(String, default="#3788d8", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    account: Mapped["CalDAVAccount"] = relationship(back_populates="calendars")


class UserSettings(Base):
    __tablename__ = "user_settings"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    timezone: Mapped[str] = mapped_column(String, default="UTC", nullable=False)
    first_day_of_week: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    time_format: Mapped[str] = mapped_column(String, default="24h", nullable=False)
    date_format: Mapped[str] = mapped_column(String, default="YYYY-MM-DD", nullable=False)
    default_view: Mapped[str] = mapped_column(String, default="dayGridMonth", nullable=False)
    auto_logout_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    auto_logout_timeout_seconds: Mapped[int] = mapped_column(Integer, default=3600, nullable=False)

    user: Mapped["User"] = relationship(back_populates="settings")
