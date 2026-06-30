import hmac
import os
from dataclasses import dataclass

import structlog
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .crypto import derive_kek, generate_dek, make_verifier, unwrap_dek, wrap_dek
from .models import User, UserSettings

logger = structlog.get_logger()


@dataclass
class HeaderAuthAttempt:
    principal: str | None
    user: User | None
    dek: bytes | None
    created_user: bool
    reason: str | None


def get_header_principal(request: Request) -> str | None:
    raw = request.headers.get(settings.header_auth_header_name)
    if raw is None:
        return None
    principal = raw.strip().lower()
    return principal or None


def _password_material(principal: str) -> str:
    secret = settings.header_auth_secret
    if not secret:
        raise RuntimeError(
            "HEADER_AUTHENTICATION is enabled but HEADER_AUTH_SECRET is not set"
        )
    return f"header-auth:{principal}:{secret}"


def _derive_user_kek(user: User, principal: str) -> bytes:
    return derive_kek(
        _password_material(principal),
        user.kdf_salt,
        time_cost=user.kdf_time_cost,
        memory_cost=user.kdf_memory_cost,
        parallelism=user.kdf_parallelism,
    )


async def get_or_create_header_user(principal: str, db: AsyncSession) -> tuple[User, bool]:
    user = (await db.execute(select(User).where(User.email == principal))).scalar_one_or_none()
    if user is not None:
        return user, False

    kdf_salt = os.urandom(32)
    dek = generate_dek()
    kek = derive_kek(
        _password_material(principal),
        kdf_salt,
        time_cost=settings.argon2_time_cost,
        memory_cost=settings.argon2_memory_cost,
        parallelism=settings.argon2_parallelism,
    )
    wrapped_dek, dek_nonce = wrap_dek(dek, kek)
    user = User(
        email=principal,
        kdf_salt=kdf_salt,
        kdf_time_cost=settings.argon2_time_cost,
        kdf_memory_cost=settings.argon2_memory_cost,
        kdf_parallelism=settings.argon2_parallelism,
        wrapped_dek=wrapped_dek,
        dek_nonce=dek_nonce,
        password_verifier=make_verifier(kek),
        must_change_password=False,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user, True


async def resolve_idle_timeout_for_user(user_id: int, db: AsyncSession) -> int | None:
    s = (await db.execute(select(UserSettings).where(UserSettings.user_id == user_id))).scalar_one_or_none()
    if s is not None and not s.auto_logout_enabled:
        return None
    if s is not None:
        return s.auto_logout_timeout_seconds
    return settings.session_idle_timeout


async def try_header_auth(request: Request, db: AsyncSession) -> HeaderAuthAttempt:
    if not settings.header_authentication:
        return HeaderAuthAttempt(
            principal=None,
            user=None,
            dek=None,
            created_user=False,
            reason="disabled",
        )

    principal = get_header_principal(request)
    if principal is None:
        return HeaderAuthAttempt(
            principal=None,
            user=None,
            dek=None,
            created_user=False,
            reason="missing_header",
        )

    user, created_user = await get_or_create_header_user(principal, db)
    kek = _derive_user_kek(user, principal)
    verifier = make_verifier(kek)
    if not hmac.compare_digest(verifier, user.password_verifier):
        logger.warning("header_auth_user_incompatible", user_id=user.id)
        return HeaderAuthAttempt(
            principal=principal,
            user=user,
            dek=None,
            created_user=created_user,
            reason="incompatible_user",
        )

    try:
        dek = unwrap_dek(user.wrapped_dek, user.dek_nonce, kek)
    except Exception:
        logger.warning("header_auth_dek_unwrap_failed", user_id=user.id)
        return HeaderAuthAttempt(
            principal=principal,
            user=user,
            dek=None,
            created_user=created_user,
            reason="incompatible_user",
        )

    return HeaderAuthAttempt(
        principal=principal,
        user=user,
        dek=dek,
        created_user=created_user,
        reason=None,
    )
