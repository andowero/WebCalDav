import os

import pytest
from cryptography.exceptions import InvalidTag

from webcaldav.crypto import (
    decrypt_bytes,
    derive_kek,
    encrypt_bytes,
    generate_dek,
    make_verifier,
    unwrap_dek,
    verify_kek,
    wrap_dek,
)

_PARAMS = dict(time_cost=1, memory_cost=1024, parallelism=1)


def test_kek_derivation_is_deterministic():
    salt = os.urandom(32)
    k1 = derive_kek("password", salt, **_PARAMS)
    k2 = derive_kek("password", salt, **_PARAMS)
    assert k1 == k2
    assert len(k1) == 32


def test_kek_different_passwords():
    salt = os.urandom(32)
    k1 = derive_kek("password1", salt, **_PARAMS)
    k2 = derive_kek("password2", salt, **_PARAMS)
    assert k1 != k2


def test_kek_different_salts():
    k1 = derive_kek("password", os.urandom(32), **_PARAMS)
    k2 = derive_kek("password", os.urandom(32), **_PARAMS)
    assert k1 != k2


def test_dek_wrap_unwrap_roundtrip():
    dek = generate_dek()
    kek = derive_kek("secret", os.urandom(32), **_PARAMS)
    ct, nonce = wrap_dek(dek, kek)
    recovered = unwrap_dek(ct, nonce, kek)
    assert recovered == dek


def test_dek_unwrap_wrong_kek_fails():
    dek = generate_dek()
    kek = derive_kek("secret", os.urandom(32), **_PARAMS)
    ct, nonce = wrap_dek(dek, kek)
    bad_kek = derive_kek("wrong", os.urandom(32), **_PARAMS)
    with pytest.raises(InvalidTag):
        unwrap_dek(ct, nonce, bad_kek)


def test_verifier_correct_password():
    salt = os.urandom(32)
    kek = derive_kek("correct", salt, **_PARAMS)
    verifier = make_verifier(kek)
    assert verify_kek(kek, verifier) is True


def test_verifier_wrong_password():
    salt = os.urandom(32)
    kek_good = derive_kek("correct", salt, **_PARAMS)
    kek_bad = derive_kek("wrong", salt, **_PARAMS)
    verifier = make_verifier(kek_good)
    assert verify_kek(kek_bad, verifier) is False


def test_encrypt_decrypt_roundtrip():
    dek = generate_dek()
    plaintext = b"secret caldav password"
    ct, nonce = encrypt_bytes(plaintext, dek)
    recovered = decrypt_bytes(ct, nonce, dek)
    assert recovered == plaintext


def test_encrypt_tampered_fails():
    dek = generate_dek()
    ct, nonce = encrypt_bytes(b"data", dek)
    tampered = bytes([ct[0] ^ 0xFF]) + ct[1:]
    with pytest.raises(InvalidTag):
        decrypt_bytes(tampered, nonce, dek)


def test_nonces_are_unique():
    dek = generate_dek()
    nonces = {encrypt_bytes(b"x", dek)[1] for _ in range(50)}
    assert len(nonces) == 50
