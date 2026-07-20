"""Temporary token generation, hashing, and verification (spec §11, §21).

The raw token is only ever held in memory long enough to return it to the
caller once, at creation time. Only its SHA-256 hash is persisted.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets


def generate_raw_token(byte_length: int) -> str:
    """Generate a URL-safe opaque token. Never stored; returned to the caller once."""
    return secrets.token_urlsafe(byte_length)


def hash_token(raw_token: str) -> str:
    """Deterministically hash a raw token for storage/comparison."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def verify_token(raw_token: str, token_hash: str) -> bool:
    """Constant-time comparison of a raw token against a stored hash."""
    return hmac.compare_digest(hash_token(raw_token), token_hash)
