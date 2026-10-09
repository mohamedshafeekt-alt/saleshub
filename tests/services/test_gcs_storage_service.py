from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from google.api_core.exceptions import InternalServerError

from app.core.config import settings
from app.services.file_upload_service import UnsupportedFileTypeError
from app.services.gcs_storage_service import GCSStorageService, StorageError, generate_presigned_url


def _mock_blob(mock_client_cls) -> MagicMock:
    bucket = mock_client_cls.from_service_account_info.return_value.bucket.return_value
    return bucket.blob.return_value


@patch("app.services.gcs_storage_service.storage.Client")
def test_save_uploads_to_gcs_and_returns_key(mock_client_cls):
    blob = _mock_blob(mock_client_cls)
    service = GCSStorageService(prefix="avatars", allowed_content_types={"image/png": ".png"})

    key = service.save(b"fake-bytes", "image/png", filename_stem="7")

    assert key == "avatars/7.png"
    client = mock_client_cls.from_service_account_info.return_value
    client.bucket.assert_called_once_with(settings.gcs_bucket_name)
    client.bucket.return_value.blob.assert_called_once_with("avatars/7.png")
    blob.upload_from_string.assert_called_once_with(b"fake-bytes", content_type="image/png")


@patch("app.services.gcs_storage_service.storage.Client")
def test_save_rejects_unsupported_content_type(mock_client_cls):
    service = GCSStorageService(prefix="avatars", allowed_content_types={"image/png": ".png"})

    with pytest.raises(UnsupportedFileTypeError):
        service.save(b"x", "application/pdf", filename_stem="7")

    _mock_blob(mock_client_cls).upload_from_string.assert_not_called()


@patch("app.services.gcs_storage_service.storage.Client")
def test_save_wraps_api_error(mock_client_cls):
    _mock_blob(mock_client_cls).upload_from_string.side_effect = InternalServerError("boom")
    service = GCSStorageService(prefix="avatars", allowed_content_types={"image/png": ".png"})

    with pytest.raises(StorageError):
        service.save(b"x", "image/png", filename_stem="7")


@patch("app.services.gcs_storage_service.storage.Client")
def test_delete_deletes_blob(mock_client_cls):
    blob = _mock_blob(mock_client_cls)
    service = GCSStorageService(prefix="avatars", allowed_content_types={})

    service.delete("avatars/7.png")

    mock_client_cls.from_service_account_info.return_value.bucket.return_value.blob.assert_called_once_with(
        "avatars/7.png"
    )
    blob.delete.assert_called_once_with()


@patch("app.services.gcs_storage_service.storage.Client")
def test_delete_wraps_api_error(mock_client_cls):
    _mock_blob(mock_client_cls).delete.side_effect = InternalServerError("boom")
    service = GCSStorageService(prefix="avatars", allowed_content_types={})

    with pytest.raises(StorageError):
        service.delete("avatars/7.png")


@patch("app.services.gcs_storage_service.storage.Client")
def test_generate_presigned_url_signs_v4_get(mock_client_cls):
    blob = _mock_blob(mock_client_cls)
    blob.generate_signed_url.return_value = "https://example.com/signed"

    url = generate_presigned_url("avatars/7.png")

    assert url == "https://example.com/signed"
    mock_client_cls.from_service_account_info.assert_called_once_with(settings.gcs_credentials)
    blob.generate_signed_url.assert_called_once_with(
        version="v4", expiration=timedelta(seconds=900), method="GET"
    )


@patch("app.services.gcs_storage_service.storage.Client")
def test_generate_presigned_url_wraps_error(mock_client_cls):
    _mock_blob(mock_client_cls).generate_signed_url.side_effect = ValueError("no private key")

    with pytest.raises(StorageError):
        generate_presigned_url("avatars/7.png")
