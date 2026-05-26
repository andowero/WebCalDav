import secrets
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Callable


@dataclass
class SessionEntry:
    user_id: int
    dek: bytes
    last_seen: datetime
    restricted: bool


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

    def create(self, user_id: int, dek: bytes, restricted: bool) -> str:
        session_id = secrets.token_urlsafe(32)
        with self._lock:
            self._sessions[session_id] = SessionEntry(
                user_id=user_id,
                dek=dek,
                last_seen=self._clock(),
                restricted=restricted,
            )
        return session_id

    def get(self, session_id: str) -> SessionEntry | None:
        with self._lock:
            entry = self._sessions.get(session_id)
            if entry is None:
                return None
            now = self._clock()
            if (now - entry.last_seen).total_seconds() > self._idle_timeout:
                del self._sessions[session_id]
                return None
            entry.last_seen = now
            return entry

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
