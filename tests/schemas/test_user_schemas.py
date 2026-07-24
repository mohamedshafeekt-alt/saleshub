"""app.schemas.user: UserRead/UserUpdate/PasswordChange shape."""

import pytest
from pydantic import ValidationError

from app.schemas.user import PasswordChange, UserUpdate


def test_user_update_allows_optional_last_name_and_phone():
    update = UserUpdate(first_name="Sarah")

    assert update.last_name is None
    assert update.phone_number is None


def test_password_change_rejects_short_new_password():
    with pytest.raises(ValidationError):
        PasswordChange(current_password="whatever", new_password="short")


def test_password_change_accepts_valid_new_password():
    change = PasswordChange(current_password="whatever", new_password="Longenough1")

    assert change.new_password == "Longenough1"


@pytest.mark.parametrize(
    "new_password",
    ["alllowercase1", "ALLUPPERCASE1", "NoDigitsHere"],
)
def test_password_change_rejects_missing_character_class(new_password: str):
    with pytest.raises(ValidationError):
        PasswordChange(current_password="whatever", new_password=new_password)
