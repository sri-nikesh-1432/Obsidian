"""Cryptography: AES-256-GCM envelope encryption with KMS-managed DEK wrapping.

Flow (upload):
    plaintext --AES-256-GCM(DEK, nonce, aad=document_id)--> ciphertext
    DEK --KMS Encrypt--> wrapped_dek
    ciphertext --> S3 (private bucket)
    wrapped_dek + nonce + hashes --> DynamoDB metadata

Keys never leave the backend. Keys are never stored in vector storage,
never placed in prompts, and never returned to the frontend.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from . import aws

ALGORITHM = "AES-256-GCM"


@dataclass
class EncryptedPayload:
    ciphertext: bytes
    nonce: bytes
    wrapped_dek: bytes
    key_id: str
    ciphertext_sha256: str
    plaintext_sha256: str


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encrypt_bytes(plaintext: bytes, document_id: str) -> EncryptedPayload:
    """Generate a fresh DEK, encrypt content, wrap the DEK with KMS."""
    kms = aws.get_client("kms")
    key_id = aws.kms_key_id()
    dek = AESGCM.generate_key(bit_length=256)
    nonce = __import__("os").urandom(12)
    aad = document_id.encode("utf-8")
    ciphertext = AESGCM(dek).encrypt(nonce, plaintext, aad)
    wrapped = kms.encrypt(KeyId=key_id, Plaintext=dek)["CiphertextBlob"]
    return EncryptedPayload(
        ciphertext=ciphertext,
        nonce=nonce,
        wrapped_dek=wrapped,
        key_id=key_id,
        ciphertext_sha256=sha256_hex(ciphertext),
        plaintext_sha256=sha256_hex(plaintext),
    )


def decrypt_bytes(*, ciphertext: bytes, nonce: bytes, wrapped_dek: bytes,
                  document_id: str, expected_ciphertext_sha256: str | None = None) -> bytes:
    """Unwrap the DEK with KMS and authenticate/decrypt with AES-256-GCM.

    Fails closed: any tampering (ciphertext, nonce, tag) raises.
    """
    if expected_ciphertext_sha256:
        actual = sha256_hex(ciphertext)
        if actual != expected_ciphertext_sha256:
            raise ValueError("integrity check failed")
    kms = aws.get_client("kms")
    dek = kms.decrypt(CiphertextBlob=wrapped_dek)["Plaintext"]
    aad = document_id.encode("utf-8")
    return AESGCM(dek).decrypt(nonce, ciphertext, aad)
