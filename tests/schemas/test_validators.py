"""app.schemas.validators: shared field validators."""

import pytest

from app.schemas.validators import validate_linkedin_url


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
