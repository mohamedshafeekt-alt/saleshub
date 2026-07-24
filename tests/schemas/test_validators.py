"""app.schemas.validators: shared field validators."""

import pytest

from app.schemas.validators import validate_linkedin_url


def test_validate_linkedin_url_accepts_full_url():
    assert validate_linkedin_url("https://linkedin.com/in/jane") == "https://linkedin.com/in/jane"


def test_validate_linkedin_url_treats_empty_string_as_none():
    assert validate_linkedin_url("") is None


def test_validate_linkedin_url_treats_none_as_none():
    assert validate_linkedin_url(None) is None


@pytest.mark.parametrize("value", ["linkedin.com/in/jane", "not-a-url", "https://example.com/in/jane"])
def test_validate_linkedin_url_rejects_non_linkedin_or_missing_scheme(value: str):
    with pytest.raises(ValueError):
        validate_linkedin_url(value)
