"""Shared Pydantic field validators reused across schema modules."""


def validate_linkedin_url(value: str | None) -> str | None:
    """Empty string is treated as unset; a non-empty value must reference
    linkedin.com. The scheme is optional -- a bare "linkedin.com/in/..."
    is normalized to "https://linkedin.com/in/...".
    """
    if value is None or value == "":
        return None
    if "linkedin.com" not in value.lower():
        raise ValueError("linkedin_url must be a linkedin.com URL")
    if not value.lower().startswith(("http://", "https://")):
        value = f"https://{value}"
    return value
