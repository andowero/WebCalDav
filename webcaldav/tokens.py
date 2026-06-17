"""MCP API tokens: minting and resolution.

A token's plaintext is ``WebCalDav`` + ``RO``/``RW`` + a random secret, shown to
the user once and never stored. The DEK and the AUTHORITATIVE scope/mode/expiry
are sealed together in an AES-GCM blob keyed by a key derived from the secret
(see :func:`webcaldav.crypto.derive_token_key`). Authorization always reads the
decrypted blob, never the plaintext mirror columns, so tampering with the DB
rows cannot widen a token's scope or mode without the secret.
"""
import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .crypto import derive_token_key, unwrap_dek, wrap_dek
from .models import APIToken

PREFIX = "WebCalDav"
_MODES = {"ro": "RO", "rw": "RW"}


@dataclass
class TokenContext:
    """Resolved, authenticated state for an MCP request, built from the sealed
    blob only (never from the plaintext mirror columns)."""

    user_id: int
    dek: bytes
    mode: str  # "ro" | "rw"
    all_calendars: bool
    calendar_ids: list[int] | None  # None when all_calendars is True
    token_id: int


def mint_token(
    dek: bytes,
    mode: str,
    all_calendars: bool,
    calendar_ids: list[int] | None,
    expires_at: datetime | None,
) -> tuple[str, bytes, bytes, bytes]:
    """Return (full_token_plaintext, token_sha256, sealed_blob, blob_nonce).

    The caller persists the last three and shows the plaintext to the user once.
    """
    if mode not in _MODES:
        raise ValueError(f"invalid mode: {mode}")
    secret = secrets.token_urlsafe(32)
    full = f"{PREFIX}{_MODES[mode]}{secret}"
    payload = json.dumps(
        {
            "dek": base64.b64encode(dek).decode("ascii"),
            "mode": mode,
            "all_calendars": all_calendars,
            "calendar_ids": sorted(calendar_ids or []),
            "expires_at": expires_at.isoformat() if expires_at else None,
        }
    ).encode("utf-8")
    key = derive_token_key(secret)
    sealed_blob, blob_nonce = wrap_dek(payload, key)
    token_sha256 = hashlib.sha256(secret.encode("utf-8")).digest()
    return full, token_sha256, sealed_blob, blob_nonce


def _parse(token: str) -> tuple[str, str] | None:
    """Split a token plaintext into (mode, secret), or None if malformed."""
    if not token.startswith(PREFIX):
        return None
    rest = token[len(PREFIX):]
    for mode, label in _MODES.items():
        if rest.startswith(label):
            secret = rest[len(label):]
            return (mode, secret) if secret else None
    return None


async def resolve_token(token: str, db: AsyncSession) -> TokenContext | None:
    """Authenticate a token plaintext and return its context, or None if the
    token is malformed, unknown, tampered, or expired. Bumps ``last_used_at``."""
    parsed = _parse(token)
    if parsed is None:
        return None
    prefix_mode, secret = parsed
    token_sha256 = hashlib.sha256(secret.encode("utf-8")).digest()

    row = (
        await db.execute(select(APIToken).where(APIToken.token_sha256 == token_sha256))
    ).scalar_one_or_none()
    if row is None:
        return None
    # Defensive constant-time confirm of the lookup match.
    if not hmac.compare_digest(row.token_sha256, token_sha256):
        return None

    key = derive_token_key(secret)
    try:
        payload = json.loads(unwrap_dek(row.sealed_blob, row.blob_nonce, key))
    except Exception:
        return None

    # The mode in the presented prefix must match the sealed (authoritative) mode.
    if payload.get("mode") != prefix_mode:
        return None

    expires_raw = payload.get("expires_at")
    if expires_raw:
        try:
            expires_at = datetime.fromisoformat(expires_raw)
        except ValueError:
            return None
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if datetime.now(UTC) >= expires_at:
            return None

    try:
        dek = base64.b64decode(payload["dek"])
    except Exception:
        return None

    all_calendars = bool(payload.get("all_calendars", True))
    calendar_ids = None if all_calendars else list(payload.get("calendar_ids") or [])

    row.last_used_at = datetime.now(UTC)
    await db.commit()

    return TokenContext(
        user_id=row.user_id,
        dek=dek,
        mode=payload["mode"],
        all_calendars=all_calendars,
        calendar_ids=calendar_ids,
        token_id=row.id,
    )
