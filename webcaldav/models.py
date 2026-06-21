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
    api_tokens: Mapped[list["APIToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    shares: Mapped[list["Share"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
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


class APIToken(Base):
    """An MCP API token. The token plaintext (WebCalDav{RO,RW}<secret>) is shown
    to the user once and never stored. ``sealed_blob`` is an AES-GCM ciphertext,
    keyed by a key derived from the secret, holding the AUTHORITATIVE
    {dek, mode, all_calendars, calendar_ids, expires_at}. The plaintext ``mode``,
    ``all_calendars``, ``expires_at`` columns and the ``api_token_calendars`` rows
    are a display-only mirror for the settings UI — they are never trusted for
    authorization, so DB tampering cannot widen a token's scope or mode without
    the secret (which would only break the token, not escalate it)."""

    __tablename__ = "api_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    # SHA-256 of the random secret, for O(1) lookup + constant-time compare.
    token_sha256: Mapped[bytes] = mapped_column(LargeBinary(32), unique=True, nullable=False)
    # AES-GCM blob (authoritative): {dek, mode, all_calendars, calendar_ids, expires_at}.
    sealed_blob: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    blob_nonce: Mapped[bytes] = mapped_column(LargeBinary(12), nullable=False)
    # --- display-only mirror (never used for enforcement) ---
    mode: Mapped[str] = mapped_column(String, nullable=False)  # "ro" | "rw"
    all_calendars: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship(back_populates="api_tokens")
    calendars: Mapped[list["APITokenCalendar"]] = relationship(
        back_populates="token", cascade="all, delete-orphan"
    )


class APITokenCalendar(Base):
    """Display-only scope rows for a calendar-scoped token (all_calendars=False).
    Authoritative scope lives in APIToken.sealed_blob; these only render the UI."""

    __tablename__ = "api_token_calendars"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    api_token_id: Mapped[int] = mapped_column(
        ForeignKey("api_tokens.id", ondelete="CASCADE"), nullable=False
    )
    calendar_id: Mapped[int] = mapped_column(
        ForeignKey("calendars.id", ondelete="CASCADE"), nullable=False
    )

    token: Mapped["APIToken"] = relationship(back_populates="calendars")


class Share(Base):
    """A share link for an item, a grid period, or an agenda slice. The URL
    carries only a random secret in its fragment (``/s/<id>#<secret>``), shown to
    the sharer once and never stored. ``sealed_blob`` is an AES-GCM ciphertext,
    keyed by a key derived from the secret, holding the AUTHORITATIVE
    {dek, kind, mode, scope, bounds, expires_at}. All plaintext columns below and
    the ``share_calendars`` rows are a display-only mirror for the settings UI —
    never trusted for authorization, so DB tampering cannot widen a share's scope
    or mode without the secret (which would only break the share, not escalate
    it). Mirrors the APIToken design."""

    __tablename__ = "shares"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    # SHA-256 of the random secret, for O(1) lookup + constant-time compare.
    token_sha256: Mapped[bytes] = mapped_column(LargeBinary(32), unique=True, nullable=False)
    # AES-GCM blob (authoritative): {dek, kind, mode, scope, bounds, expires_at}.
    sealed_blob: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    blob_nonce: Mapped[bytes] = mapped_column(LargeBinary(12), nullable=False)
    # --- display-only mirror (never used for enforcement) ---
    kind: Mapped[str] = mapped_column(String, nullable=False)  # "item"|"grid"|"agenda"
    mode: Mapped[str] = mapped_column(String, nullable=False)  # "ro"|"rw"
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # item-kind mirror
    item_uid: Mapped[str | None] = mapped_column(String, nullable=True)
    item_kind: Mapped[str | None] = mapped_column(String, nullable=True)  # event|task|journal
    item_calendar_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # grid-kind mirror
    grid_view: Mapped[str | None] = mapped_column(String, nullable=True)
    grid_anchor: Mapped[str | None] = mapped_column(String, nullable=True)  # ISO date
    # agenda-kind mirror
    agenda_from: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    agenda_to: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # default target calendar for sharee-created items (grid/agenda RW)
    default_calendar_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship(back_populates="shares")
    calendars: Mapped[list["ShareCalendar"]] = relationship(
        back_populates="share", cascade="all, delete-orphan"
    )


class ShareCalendar(Base):
    """Display-only scope rows for a grid/agenda share. Authoritative scope lives
    in Share.sealed_blob; these only render the UI. ``writable`` mirrors whether
    the sharee may create/edit items on this calendar."""

    __tablename__ = "share_calendars"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    share_id: Mapped[int] = mapped_column(
        ForeignKey("shares.id", ondelete="CASCADE"), nullable=False
    )
    calendar_id: Mapped[int] = mapped_column(
        ForeignKey("calendars.id", ondelete="CASCADE"), nullable=False
    )
    writable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    share: Mapped["Share"] = relationship(back_populates="calendars")


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
    # Browser reminder notifications. Off by default; enabling forces
    # auto_logout off (the tab must stay logged in to keep resyncing events).
    notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # How completed VTODO tasks are shown: "hidden" (default) or "grayed".
    completed_task_display: Mapped[str] = mapped_column(String, default="hidden", nullable=False)
    # Where tasks with no DTSTART/DUE appear: "agenda" (agenda list only, default)
    # or "today" (pinned to the current day in grid views as well as the agenda).
    undated_task_display: Mapped[str] = mapped_column(String, default="agenda", nullable=False)
    # UI color theme: "system" (follow OS prefers-color-scheme, default),
    # "light", or "dark".
    theme: Mapped[str] = mapped_column(String, default="system", nullable=False)
    # UI language: "autodetect" (use the browser Accept-Language, default),
    # "english", or "czech". Resolved to a concrete code by webcaldav.i18n.
    language: Mapped[str] = mapped_column(String, default="autodetect", nullable=False)
    # When True, a single click on empty calendar space only highlights the
    # day/slot and a double click opens the create modal. Off by default
    # (single click opens the create modal immediately).
    double_click_to_create_events: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    # Default bounds for the agenda search window, as day offsets from today.
    # "from" = today minus this many days (past), "to" = today plus this many
    # days (future). Used only when a search is active in the agenda view.
    agenda_search_from_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    agenda_search_to_days: Mapped[int] = mapped_column(Integer, default=365, nullable=False)

    user: Mapped["User"] = relationship(back_populates="settings")
