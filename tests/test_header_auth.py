import pytest

from webcaldav.app import app, lifespan
from webcaldav.config import settings


@pytest.mark.asyncio
async def test_header_auth_requires_secret() -> None:
    old_enabled = settings.header_authentication
    old_secret = settings.header_auth_secret
    try:
        settings.header_authentication = True
        settings.header_auth_secret = None
        with pytest.raises(RuntimeError, match="HEADER_AUTH_SECRET"):
            async with lifespan(app):
                pass
    finally:
        settings.header_authentication = old_enabled
        settings.header_auth_secret = old_secret
