"""Shared Pydantic field validators reused across schema modules."""


def validate_linkedin_url(value: str | None) -> str | None:
    """Empty string is treated as unset; a non-empty value must be a
    LinkedIn http(s) URL."""
    if value is None or value == "":
        return None
    if not value.lower().startswith(("http://", "https://")) or "linkedin.com" not in value.lower():
        raise ValueError("linkedin_url must be a full https://linkedin.com/... URL")
    return value
