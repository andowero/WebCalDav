"""Admin CLI: python -m webcaldav.admin <command>"""
import asyncio
import os
import secrets
import string
import sys

import typer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .crypto import derive_kek, generate_dek, make_verifier, wrap_dek
from .db import create_tables, init_engine, get_session_factory
from .models import CalDAVAccount, User

cli = typer.Typer(help="WebCalDav admin CLI")


def _rand_password(length: int = 20) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


async def _provision_user(email: str, password: str, db: AsyncSession) -> User:
    kdf_salt = os.urandom(32)
    dek = generate_dek()
    kek = derive_kek(
        password,
        kdf_salt,
        time_cost=settings.argon2_time_cost,
        memory_cost=settings.argon2_memory_cost,
        parallelism=settings.argon2_parallelism,
    )
    wrapped_dek, dek_nonce = wrap_dek(dek, kek)
    verifier = make_verifier(kek)
    user = User(
        email=email,
        kdf_salt=kdf_salt,
        wrapped_dek=wrapped_dek,
        dek_nonce=dek_nonce,
        password_verifier=verifier,
        must_change_password=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


def _setup_db() -> None:
    init_engine(settings.database_url)


@cli.command()
def create_user(email: str = typer.Option(..., help="User email address")) -> None:
    """Create a new user and print a one-off password."""
    _setup_db()

    async def _run() -> str:
        await create_tables()
        async with get_session_factory()() as db:
            existing = (
                await db.execute(select(User).where(User.email == email))
            ).scalar_one_or_none()
            if existing:
                typer.echo(f"Error: user {email} already exists", err=True)
                raise typer.Exit(1)
            password = _rand_password()
            await _provision_user(email, password, db)
            return password

    password = asyncio.run(_run())
    typer.echo(f"Created user: {email}")
    typer.echo(f"One-off password: {password}")


@cli.command()
def list_users() -> None:
    """List all users."""
    _setup_db()

    async def _run() -> list[User]:
        async with get_session_factory()() as db:
            return list((await db.execute(select(User))).scalars().all())

    users = asyncio.run(_run())
    if not users:
        typer.echo("No users.")
        return
    typer.echo(f"{'ID':<6} {'EMAIL':<40} {'MUST_CHANGE_PW'}")
    for u in users:
        typer.echo(f"{u.id:<6} {u.email:<40} {u.must_change_password}")


@cli.command()
def reset_password(email: str = typer.Option(..., help="User email address")) -> None:
    """Issue new one-off password and rotate DEK (invalidates stored CalDAV credentials)."""
    _setup_db()

    async def _run() -> str:
        async with get_session_factory()() as db:
            user = (
                await db.execute(select(User).where(User.email == email))
            ).scalar_one_or_none()
            if user is None:
                typer.echo(f"Error: user {email} not found", err=True)
                raise typer.Exit(1)

            # Wipe CalDAV credentials (DEK rotation makes them unrecoverable)
            await db.execute(
                select(CalDAVAccount).where(CalDAVAccount.user_id == user.id)
            )
            result = await db.execute(
                select(CalDAVAccount).where(CalDAVAccount.user_id == user.id)
            )
            for account in result.scalars().all():
                await db.delete(account)

            password = _rand_password()
            kdf_salt = os.urandom(32)
            dek = generate_dek()
            kek = derive_kek(
                password,
                kdf_salt,
                time_cost=settings.argon2_time_cost,
                memory_cost=settings.argon2_memory_cost,
                parallelism=settings.argon2_parallelism,
            )
            wrapped_dek, dek_nonce = wrap_dek(dek, kek)
            verifier = make_verifier(kek)

            user.kdf_salt = kdf_salt
            user.wrapped_dek = wrapped_dek
            user.dek_nonce = dek_nonce
            user.password_verifier = verifier
            user.must_change_password = True
            await db.commit()
            return password

    password = asyncio.run(_run())
    typer.echo(f"Password reset for: {email}")
    typer.echo(f"New one-off password: {password}")
    typer.echo("WARNING: all stored CalDAV credentials have been deleted.")


@cli.command()
def delete_user(email: str = typer.Option(..., help="User email address")) -> None:
    """Permanently delete a user and all their data."""
    _setup_db()

    async def _run() -> None:
        async with get_session_factory()() as db:
            user = (
                await db.execute(select(User).where(User.email == email))
            ).scalar_one_or_none()
            if user is None:
                typer.echo(f"Error: user {email} not found", err=True)
                raise typer.Exit(1)
            await db.delete(user)
            await db.commit()

    asyncio.run(_run())
    typer.echo(f"Deleted user: {email}")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
