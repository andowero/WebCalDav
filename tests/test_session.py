from datetime import UTC, datetime, timedelta

from webcaldav.session import SessionStore


class FakeClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 1, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now += timedelta(seconds=seconds)


def test_global_default_expiry():
    clock = FakeClock()
    store = SessionStore(idle_timeout_seconds=100, clock=clock)
    sid = store.create(1, b"dek", False)  # no explicit timeout -> global default
    clock.advance(50)
    assert store.get(sid) is not None  # refreshed
    clock.advance(99)
    assert store.get(sid) is not None  # within window after refresh
    clock.advance(101)
    assert store.get(sid) is None  # expired


def test_per_session_timeout_overrides_global():
    clock = FakeClock()
    store = SessionStore(idle_timeout_seconds=3600, clock=clock)
    sid = store.create(1, b"dek", False, idle_timeout=10)
    clock.advance(11)
    assert store.get(sid) is None


def test_disabled_never_expires():
    clock = FakeClock()
    store = SessionStore(idle_timeout_seconds=10, clock=clock)
    sid = store.create(1, b"dek", False, idle_timeout=None)
    clock.advance(10_000)
    assert store.get(sid) is not None


def test_peek_does_not_refresh():
    clock = FakeClock()
    store = SessionStore(idle_timeout_seconds=100, clock=clock)
    sid = store.create(1, b"dek", False, idle_timeout=100)
    # Repeated peeks must NOT keep the session alive.
    for _ in range(20):
        clock.advance(10)
        store.peek(sid)
    # 200s elapsed, last_seen never advanced -> expired on next access.
    assert store.peek(sid) is None
    assert store.get(sid) is None


def test_peek_expires_past_window():
    clock = FakeClock()
    store = SessionStore(idle_timeout_seconds=100, clock=clock)
    sid = store.create(1, b"dek", False, idle_timeout=100)
    clock.advance(101)
    assert store.peek(sid) is None


def test_status_enabled_remaining():
    clock = FakeClock()
    store = SessionStore(idle_timeout_seconds=100, clock=clock)
    sid = store.create(1, b"dek", False, idle_timeout=100)
    clock.advance(30)
    st = store.status(sid)
    assert st is not None
    assert st.enabled is True
    assert st.timeout_seconds == 100
    assert st.remaining_seconds == 70


def test_status_disabled():
    clock = FakeClock()
    store = SessionStore(idle_timeout_seconds=100, clock=clock)
    sid = store.create(1, b"dek", False, idle_timeout=None)
    st = store.status(sid)
    assert st is not None
    assert st.enabled is False
    assert st.timeout_seconds is None
    assert st.remaining_seconds is None


def test_status_unknown_session():
    store = SessionStore(idle_timeout_seconds=100)
    assert store.status("nope") is None


def test_update_idle_timeout_live():
    clock = FakeClock()
    store = SessionStore(idle_timeout_seconds=3600, clock=clock)
    sid = store.create(1, b"dek", False, idle_timeout=3600)
    store.update(sid, idle_timeout=None)  # disable mid-session
    clock.advance(10_000)
    assert store.get(sid) is not None
