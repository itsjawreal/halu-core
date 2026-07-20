"""Tests for token generation, hashing, and verification."""

from __future__ import annotations

from halu_core.services.token_service import generate_raw_token, hash_token, verify_token


def test_generate_raw_token_is_random_and_unpredictable() -> None:
    a = generate_raw_token(32)
    b = generate_raw_token(32)
    assert a != b
    assert len(a) > 32


def test_hash_token_is_deterministic() -> None:
    raw = "some-raw-token"
    assert hash_token(raw) == hash_token(raw)


def test_hash_token_never_equals_raw_token() -> None:
    raw = "some-raw-token"
    assert hash_token(raw) != raw


def test_verify_token_accepts_correct_pair() -> None:
    raw = generate_raw_token(32)
    assert verify_token(raw, hash_token(raw)) is True


def test_verify_token_rejects_wrong_token() -> None:
    raw = generate_raw_token(32)
    other = generate_raw_token(32)
    assert verify_token(other, hash_token(raw)) is False


def test_verify_token_rejects_tampered_hash() -> None:
    raw = generate_raw_token(32)
    tampered_hash = hash_token(raw)[:-1] + ("0" if hash_token(raw)[-1] != "0" else "1")
    assert verify_token(raw, tampered_hash) is False
