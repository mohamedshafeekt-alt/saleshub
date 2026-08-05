"""app.schemas.user: UserRead/UserUpdate/PasswordChange shape."""

from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from app.schemas.user import PasswordChange, UserUpdate

_USER_READ_BASE = {
    "id": 1,
    "email": "a@example.com",
    "first_name": "A",
    "last_name": None,
    "phone_number": None,
    "role": {"id": 1, "name": "Admin", "description": None, "permissions": []},
    "is_active": True,
    "status": "active",
    "created_at": "2026-01-01T00:00:00",
    "last_login_at": None,
}


def test_user_read_resolves_legacy_avatar_url_unchanged():
    from app.schemas.user import UserRead

    user = UserRead.model_validate({**_USER_READ_BASE, "avatar_url": "/media/avatars/1.png"})
    assert user.avatar_url == "/media/avatars/1.png"


@patch("app.services.s3_storage_service.boto3.client")
def test_user_read_resolves_s3_key_to_presigned_url(mock_boto_client):
    from app.schemas.user import UserRead

    mock_client = MagicMock()
    mock_client.generate_presigned_url.return_value = "https://example.com/signed"
    mock_boto_client.return_value = mock_client

    user = UserRead.model_validate({**_USER_READ_BASE, "avatar_url": "avatars/1.png"})
    assert user.avatar_url == "https://example.com/signed"


def test_user_read_avatar_url_none_stays_none():
    from app.schemas.user import UserRead

    user = UserRead.model_validate({**_USER_READ_BASE, "avatar_url": None})
    assert user.avatar_url is None


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
