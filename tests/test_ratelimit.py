from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from webcaldav.ratelimit import LoginRateLimiter

from .test_auth import _create_user


class FakeClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 1, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def test_limiter_blocks_after_max_attempts():
    clock = FakeClock()
    limiter = LoginRateLimiter(max_attempts=3, window_seconds=60, clock=clock)
    for _ in range(3):
        assert limiter.check("1.2.3.4") is None
        limiter.record("1.2.3.4")
    retry_after = limiter.check("1.2.3.4")
    assert retry_after is not None
    assert 1 <= retry_after <= 61


def test_limiter_window_expiry():
    clock = FakeClock()
    limiter = LoginRateLimiter(max_attempts=2, window_seconds=60, clock=clock)
    limiter.record("1.2.3.4")
    limiter.record("1.2.3.4")
    assert limiter.check("1.2.3.4") is not None
    clock.advance(61)
    assert limiter.check("1.2.3.4") is None


def test_limiter_is_per_ip():
    limiter = LoginRateLimiter(max_attempts=1, window_seconds=60)
    limiter.record("1.2.3.4")
    assert limiter.check("1.2.3.4") is not None
    assert limiter.check("5.6.7.8") is None


def test_limiter_reset():
    limiter = LoginRateLimiter(max_attempts=1, window_seconds=60)
    limiter.record("1.2.3.4")
    assert limiter.check("1.2.3.4") is not None
    limiter.reset("1.2.3.4")
    assert limiter.check("1.2.3.4") is None


def test_limiter_disabled_with_zero_attempts():
    limiter = LoginRateLimiter(max_attempts=0, window_seconds=60)
    for _ in range(20):
        limiter.record("1.2.3.4")
    assert limiter.check("1.2.3.4") is None


@pytest.mark.asyncio
async def test_login_rate_limited_after_failures(client: AsyncClient, db_engine):
    await _create_user("ratelimited@example.com", "correct-password")
    for _ in range(5):
        r = await client.post(
            "/auth/login",
            json={"email": "ratelimited@example.com", "password": "wrong"},
        )
        assert r.status_code == 401
    r = await client.post(
        "/auth/login",
        json={"email": "ratelimited@example.com", "password": "wrong"},
    )
    assert r.status_code == 429
    assert "retry-after" in r.headers
    # Even the correct password is rejected while throttled.
    r = await client.post(
        "/auth/login",
        json={"email": "ratelimited@example.com", "password": "correct-password"},
    )
    assert r.status_code == 429


@pytest.mark.asyncio
async def test_successful_login_resets_limit(client: AsyncClient, db_engine):
    await _create_user("resets@example.com", "correct-password")
    for _ in range(4):
        r = await client.post(
            "/auth/login",
            json={"email": "resets@example.com", "password": "wrong"},
        )
        assert r.status_code == 401
    r = await client.post(
        "/auth/login",
        json={"email": "resets@example.com", "password": "correct-password"},
    )
    assert r.status_code == 200
    # Bucket was reset: failed attempts start counting from zero again.
    for _ in range(5):
        r = await client.post(
            "/auth/login",
            json={"email": "resets@example.com", "password": "wrong"},
        )
        assert r.status_code == 401
