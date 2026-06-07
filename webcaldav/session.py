import secrets
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable

# Sentinel: entry should fall back to the store's global idle timeout.
_USE_DEFAULT: Any = object()


@dataclass
class SessionEntry:
    user_id: int
    dek: bytes
    last_seen: datetime
    restricted: bool
    # int -> seconds; None -> auto-logout disabled (never expires);
    # _USE_DEFAULT -> use the store's global idle timeout.
    idle_timeout: int | None | Any = _USE_DEFAULT


@dataclass
class SessionStatus:
    enabled: bool
    timeout_seconds: int | None
    remaining_seconds: int | None


class SessionStore:
    def __init__(
        self,
        idle_timeout_seconds: int = 3600,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._sessions: dict[str, SessionEntry] = {}
        self._lock = threading.Lock()
        self._idle_timeout = idle_timeout_seconds
        self._clock = clock or (lambda: datetime.now(UTC))

    def _effective_timeout(self, entry: SessionEntry) -> int | None:
        """Resolve an entry's timeout: None means disabled (no expiry)."""
        if entry.idle_timeout is _USE_DEFAULT:
            return self._idle_timeout
        return entry.idle_timeout

    def create(
        self,
        user_id: int,
        dek: bytes,
        restricted: bool,
        idle_timeout: int | None | Any = _USE_DEFAULT,
    ) -> str:
        session_id = secrets.token_urlsafe(32)
        with self._lock:
            self._sessions[session_id] = SessionEntry(
                user_id=user_id,
                dek=dek,
                last_seen=self._clock(),
                restricted=restricted,
                idle_timeout=idle_timeout,
            )
        return session_id

    def get(self, session_id: str) -> SessionEntry | None:
        with self._lock:
            entry = self._sessions.get(session_id)
            if entry is None:
                return None
            now = self._clock()
            timeout = self._effective_timeout(entry)
            if timeout is not None and (now - entry.last_seen).total_seconds() > timeout:
                del self._sessions[session_id]
                return None
            entry.last_seen = now
            return entry

    def peek(self, session_id: str) -> SessionEntry | None:
        """Like get(), but does NOT refresh last_seen. For the idle countdown."""
        with self._lock:
            entry = self._sessions.get(session_id)
            if entry is None:
                return None
            now = self._clock()
            timeout = self._effective_timeout(entry)
            if timeout is not None and (now - entry.last_seen).total_seconds() > timeout:
                del self._sessions[session_id]
                return None
            return entry

    def status(self, session_id: str) -> SessionStatus | None:
        """Non-refreshing snapshot of the idle-logout state for the countdown."""
        with self._lock:
            entry = self._sessions.get(session_id)
            if entry is None:
                return None
            now = self._clock()
            timeout = self._effective_timeout(entry)
            if timeout is None:
                return SessionStatus(enabled=False, timeout_seconds=None, remaining_seconds=None)
            elapsed = (now - entry.last_seen).total_seconds()
            if elapsed > timeout:
                del self._sessions[session_id]
                return None
            remaining = int(timeout - elapsed)
            return SessionStatus(
                enabled=True,
                timeout_seconds=timeout,
                remaining_seconds=max(0, remaining),
            )

    def update(self, session_id: str, **kwargs: object) -> None:
        with self._lock:
            entry = self._sessions.get(session_id)
            if entry:
                for k, v in kwargs.items():
                    setattr(entry, k, v)

    def delete(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self._sessions)
