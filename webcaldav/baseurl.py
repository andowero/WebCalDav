"""External base-URL detection for building share links behind a reverse proxy.

The reverse proxy terminates TLS and forwards the original scheme/host in
``X-Forwarded-Proto`` / ``X-Forwarded-Host`` (Immich-style). A
``public_base_url`` config value overrides detection when those headers are
unreliable.
"""
from fastapi import Request

from .config import settings


def base_url(request: Request) -> str:
    """Return the external origin (scheme://host, no trailing slash) the app is
    reached at, honouring the reverse proxy's forwarded headers."""
    if settings.public_base_url:
        return settings.public_base_url.rstrip("/")
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    # X-Forwarded-Host may carry a comma-separated chain; the first is the
    # original client-facing host.
    fwd_host = request.headers.get("x-forwarded-host")
    if fwd_host:
        host = fwd_host.split(",")[0].strip()
    else:
        host = request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}"
