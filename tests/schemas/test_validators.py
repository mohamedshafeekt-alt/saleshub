"""app.schemas.validators: shared field validators."""

import pytest

from app.schemas.validators import validate_linkedin_url, validate_phone


def test_validate_linkedin_url_accepts_full_url():
    assert validate_linkedin_url("https://linkedin.com/in/jane") == "https://linkedin.com/in/jane"


def test_validate_linkedin_url_treats_empty_string_as_none():
    assert validate_linkedin_url("") is None


def test_validate_linkedin_url_treats_none_as_none():
    assert validate_linkedin_url(None) is None


def test_validate_linkedin_url_normalizes_missing_scheme():
    assert validate_linkedin_url("linkedin.com/in/jane") == "https://linkedin.com/in/jane"


@pytest.mark.parametrize("value", ["not-a-url", "https://example.com/in/jane"])
def test_validate_linkedin_url_rejects_non_linkedin(value: str):
    with pytest.raises(ValueError):
        validate_linkedin_url(value)


def test_validate_phone_treats_none_and_empty_as_none():
    assert validate_phone(None) is None
    assert validate_phone("") is None
    assert validate_phone("   ") is None


@pytest.mark.parametrize(
    "value,expected",
    [
        ("+1 (800) 555-0199", "+18005550199"),
        ("800-555-0199", "8005550199"),
        ("80055501", "80055501"),
    ],
)
def test_validate_phone_strips_formatting_punctuation(value: str, expected: str):
    assert validate_phone(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "897 9898",  # too few digits
        "12345",  # too few digits
        "1" * 16,  # too many digits
        "call me maybe",  # not a phone number at all
        "555-CALL-NOW",  # letters
    ],
)
def test_validate_phone_rejects_bad_length_or_non_numeric(value: str):
    with pytest.raises(ValueError):
        validate_phone(value)
