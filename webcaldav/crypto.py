import hmac
import os

from argon2.low_level import Type, hash_secret_raw
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

_VERIFIER_INFO = b"webcaldav:password-verifier:v1"
_NONCE_LEN = 12
_KEY_LEN = 32


def derive_kek(
    password: str,
    kdf_salt: bytes,
    *,
    time_cost: int = 3,
    memory_cost: int = 65536,
    parallelism: int = 1,
) -> bytes:
    return hash_secret_raw(
        secret=password.encode("utf-8"),
        salt=kdf_salt,
        time_cost=time_cost,
        memory_cost=memory_cost,
        parallelism=parallelism,
        hash_len=_KEY_LEN,
        type=Type.ID,
    )


def make_verifier(kek: bytes) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(),
        length=_KEY_LEN,
        salt=None,
        info=_VERIFIER_INFO,
    ).derive(kek)


def verify_kek(kek: bytes, stored_verifier: bytes) -> bool:
    candidate = make_verifier(kek)
    return hmac.compare_digest(candidate, stored_verifier)


def generate_dek() -> bytes:
    return os.urandom(_KEY_LEN)


def wrap_dek(dek: bytes, kek: bytes) -> tuple[bytes, bytes]:
    nonce = os.urandom(_NONCE_LEN)
    ct = AESGCM(kek).encrypt(nonce, dek, None)
    return ct, nonce


def unwrap_dek(ciphertext: bytes, nonce: bytes, kek: bytes) -> bytes:
    return AESGCM(kek).decrypt(nonce, ciphertext, None)


def encrypt_bytes(plaintext: bytes, dek: bytes) -> tuple[bytes, bytes]:
    nonce = os.urandom(_NONCE_LEN)
    ct = AESGCM(dek).encrypt(nonce, plaintext, None)
    return ct, nonce


def decrypt_bytes(ciphertext: bytes, nonce: bytes, dek: bytes) -> bytes:
    return AESGCM(dek).decrypt(nonce, ciphertext, None)
