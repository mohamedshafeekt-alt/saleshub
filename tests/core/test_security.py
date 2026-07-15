"""app.core.security: password hashing + JWT create/decode."""

from datetime import timedelta

import pytest
from jose.exceptions import JWTError

from app.core.security import create_access_token, decode_access_token, hash_password, verify_password


def test_hash_password_does_not_return_plaintext():
    # a hash must not simply echo the input back
    assert hash_password("hunter2") != "hunter2"


def test_verify_password_correct_password_returns_true():
    hashed = hash_password("hunter2")
    assert verify_password("hunter2", hashed) is True


def test_verify_password_wrong_password_returns_false():
    hashed = hash_password("hunter2")
    assert verify_password("wrong-password", hashed) is False


def test_hash_password_same_input_produces_different_hashes():
    # bcrypt salts each hash; two hashes of the same password must differ
    assert hash_password("hunter2") != hash_password("hunter2")


def test_create_and_decode_access_token_roundtrip_returns_subject():
    token = create_access_token(subject="42")
    payload = decode_access_token(token)
    assert payload["sub"] == "42"


def test_decode_access_token_expired_raises():
    token = create_access_token(subject="42", expires_delta=timedelta(seconds=-1))
    with pytest.raises(JWTError):
        decode_access_token(token)


def test_decode_access_token_tampered_raises():
    token = create_access_token(subject="42")
    # Flip a character in the middle of the signature, not the last character
    # of the whole token: base64's final character can carry unused padding
    # bits, so flipping *it* occasionally decodes to the same bytes and the
    # signature spuriously still matches. A middle character has no such gap.
    signature = token.rsplit(".", 1)[1]
    mid = len(signature) // 2
    flipped_char = "A" if signature[mid] != "A" else "B"
    tampered_signature = signature[:mid] + flipped_char + signature[mid + 1 :]
    tampered = token.rsplit(".", 1)[0] + "." + tampered_signature
    with pytest.raises(JWTError):
        decode_access_token(tampered)


def test_decode_access_token_wrong_secret_raises():
    from jose import jwt

    from app.core.config import settings

    bad_token = jwt.encode({"sub": "42"}, "a-completely-different-secret", algorithm=settings.jwt_algorithm)
    with pytest.raises(JWTError):
        decode_access_token(bad_token)
