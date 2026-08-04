"""Shared Pydantic field validators reused across schema modules."""

import re

# E.164 allows up to 15 digits; 8 is a reasonable floor -- a bare local
# extension like "897 9898" (7 digits, no area code) isn't a usable CRM
# contact number.
_PHONE_DIGITS_RE = re.compile(r"^\+?\d{8,15}$")


def validate_phone(value: str | None) -> str | None:
    """Empty/whitespace-only is treated as unset. Otherwise strips common
    formatting punctuation (spaces, hyphens, parens, dots) and requires what's
    left to be an optional leading "+" plus 7-15 digits -- rejects both
    too-short input (e.g. "897 9898") and too-long/non-numeric junk.
    """
    if value is None:
        return None
    stripped = re.sub(r"[\s().-]", "", value)
    if stripped == "":
        return None
    if not _PHONE_DIGITS_RE.match(stripped):
        raise ValueError("phone must be 7-15 digits, optionally prefixed with +")
    return stripped


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
