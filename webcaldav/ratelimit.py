import threading
from datetime import UTC, datetime
from typing import Callable


class LoginRateLimiter:
    """Sliding-window per-IP throttle for login attempts.

    In-memory only — counters reset on restart, which is acceptable for the
    CPU-amplification threat this guards against. max_attempts=0 disables.
    """

    def __init__(
        self,
        max_attempts: int = 5,
        window_seconds: int = 300,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._max_attempts = max_attempts
        self._window = window_seconds
        self._clock = clock or (lambda: datetime.now(UTC))
        self._attempts: dict[str, list[datetime]] = {}
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self._max_attempts > 0

    def _prune(self, ip: str, now: datetime) -> list[datetime]:
        cutoff_ts = [
            t for t in self._attempts.get(ip, []) if (now - t).total_seconds() < self._window
        ]
        if cutoff_ts:
            self._attempts[ip] = cutoff_ts
        else:
            self._attempts.pop(ip, None)
        return cutoff_ts

    def check(self, ip: str) -> int | None:
        """Return None if the IP may attempt a login, else seconds until it may retry."""
        if not self.enabled:
            return None
        with self._lock:
            now = self._clock()
            attempts = self._prune(ip, now)
            if len(attempts) < self._max_attempts:
                return None
            oldest = min(attempts)
            return max(1, int(self._window - (now - oldest).total_seconds()) + 1)

    def record(self, ip: str) -> None:
        if not self.enabled:
            return
        with self._lock:
            now = self._clock()
            self._prune(ip, now)
            self._attempts.setdefault(ip, []).append(now)

    def reset(self, ip: str) -> None:
        with self._lock:
            self._attempts.pop(ip, None)
