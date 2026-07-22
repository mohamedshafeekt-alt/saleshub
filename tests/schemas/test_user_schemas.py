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
    change = PasswordChange(current_password="whatever", new_password="longenoughpassword")

    assert change.new_password == "longenoughpassword"
