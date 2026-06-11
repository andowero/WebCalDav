"""SSRF guard for CalDAV account URLs (BLOCK_PRIVATE_CALDAV_URLS).

Unit tests for validate_caldav_url plus an API test that POST /caldav-accounts
rejects a private URL with a generic 400 when the guard is enabled.
"""
import socket

import pytest
from httpx import AsyncClient

from webcaldav import caldav_client
from webcaldav.admin import _provision_user
from webcaldav.caldav_client import UnsafeURLError, validate_caldav_url
from webcaldav.config import settings
from webcaldav.db import get_session_factory


async def _login_unrestricted(client: AsyncClient, email: str) -> None:
    async with get_session_factory()() as db:
        await _provision_user(email, "initial", db)
    await client.post("/auth/login", json={"email": email, "password": "initial"})
    await client.post(
        "/auth/change-password",
        json={"old_password": "initial", "new_password": "new-secure-password"},
    )


def _fake_getaddrinfo(addr: str):
    def _inner(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (addr, port or 0))]
    return _inner


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://169.254.169.254/",  # cloud metadata
        "http://10.0.0.1/",
        "http://[::1]/",
        "file:///etc/passwd",
        "ftp://example.com/",
    ],
)
def test_validate_rejects_unsafe(url):
    with pytest.raises(UnsafeURLError):
        validate_caldav_url(url)


def test_validate_allows_public(monkeypatch):
    # Pin DNS to a public address so the test never hits the network.
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("93.184.216.34"))
    validate_caldav_url("https://caldav.example.com/dav/")


def test_validate_rejects_hostname_resolving_private(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("192.168.1.50"))
    with pytest.raises(UnsafeURLError):
        validate_caldav_url("https://sneaky.example.com/")


def test_validate_rejects_ipv4_mapped_loopback():
    with pytest.raises(UnsafeURLError):
        validate_caldav_url("http://[::ffff:127.0.0.1]/")


@pytest.mark.asyncio
async def test_create_account_rejects_private_url_when_enabled(
    client: AsyncClient, db_engine, monkeypatch
):
    monkeypatch.setattr(settings, "block_private_caldav_urls", True)
    await _login_unrestricted(client, "ssrf1@example.com")
    r = await client.post(
        "/caldav-accounts",
        json={"url": "http://127.0.0.1/", "username": "u", "password": "p"},
    )
    assert r.status_code == 400
    body = r.json()
    # Generic message — no internal address/exception detail leaked.
    assert body["detail"] == "Invalid CalDAV server URL"
    assert "127.0.0.1" not in str(body)


@pytest.mark.asyncio
async def test_create_account_allows_private_url_when_disabled(
    client: AsyncClient, db_engine, monkeypatch
):
    # Guard off (default): the URL is not pre-validated. Stub discovery so no
    # real network call happens; assert the request passes the SSRF gate.
    monkeypatch.setattr(settings, "block_private_caldav_urls", False)

    async def _fake_discover(url, username, password):
        return []

    monkeypatch.setattr(caldav_client, "discover_calendars", _fake_discover)
    # The router imported the name directly, so patch it there too.
    from webcaldav.routers import caldav_accounts as ca_router
    monkeypatch.setattr(ca_router, "discover_calendars", _fake_discover)

    await _login_unrestricted(client, "ssrf2@example.com")
    r = await client.post(
        "/caldav-accounts",
        json={"url": "http://127.0.0.1/", "username": "u", "password": "p"},
    )
    assert r.status_code == 201
