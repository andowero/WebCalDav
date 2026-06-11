import pytest

from webcaldav.admin import _provision_user, _rand_password
from webcaldav.crypto import derive_kek, unwrap_dek, verify_kek
from webcaldav.db import get_session_factory


@pytest.mark.asyncio
async def test_provision_user_creates_record(db_engine):
    async with get_session_factory()() as db:
        user = await _provision_user("test@example.com", "password123", db)
    assert user.id is not None
    assert user.email == "test@example.com"
    assert user.must_change_password is True
    assert len(user.kdf_salt) == 32
    assert len(user.dek_nonce) == 12


@pytest.mark.asyncio
async def test_provision_user_verifier_accepts_correct_password(db_engine):
    password = "test-password"
    async with get_session_factory()() as db:
        user = await _provision_user("v@example.com", password, db)

    kek = derive_kek(password, user.kdf_salt, time_cost=1, memory_cost=1024, parallelism=1)
    assert verify_kek(kek, user.password_verifier) is True


@pytest.mark.asyncio
async def test_provision_user_verifier_rejects_wrong_password(db_engine):
    async with get_session_factory()() as db:
        user = await _provision_user("w@example.com", "correct", db)

    kek = derive_kek("wrong", user.kdf_salt, time_cost=1, memory_cost=1024, parallelism=1)
    assert verify_kek(kek, user.password_verifier) is False


@pytest.mark.asyncio
async def test_provision_user_dek_roundtrip(db_engine):
    password = "wrap-test"
    async with get_session_factory()() as db:
        user = await _provision_user("dek@example.com", password, db)

    kek = derive_kek(password, user.kdf_salt, time_cost=1, memory_cost=1024, parallelism=1)
    dek = unwrap_dek(user.wrapped_dek, user.dek_nonce, kek)
    assert len(dek) == 32


def test_rand_password_uniqueness():
    passwords = {_rand_password() for _ in range(100)}
    assert len(passwords) == 100


def test_rand_password_length():
    assert len(_rand_password()) == 20
    assert len(_rand_password(8)) == 8
