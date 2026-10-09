from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.core.config import settings
from app.services.file_upload_service import FileUploadService
from app.services.gcs_storage_service import GCSStorageService
from app.services.s3_storage_service import S3StorageService
from app.services.storage import get_storage_service, resolve_file_url

_GCS_CREDS = {"type": "service_account", "client_email": "x@y.iam.gserviceaccount.com"}


@pytest.fixture
def no_s3(monkeypatch):
    monkeypatch.setattr(settings, "s3_bucket_name", "")
    monkeypatch.setattr(settings, "aws_access_key_id", "")
    monkeypatch.setattr(settings, "aws_secret_access_key", "")


@pytest.fixture
def s3_creds(monkeypatch):
    monkeypatch.setattr(settings, "s3_bucket_name", "bucket")
    monkeypatch.setattr(settings, "aws_access_key_id", "key")
    monkeypatch.setattr(settings, "aws_secret_access_key", "secret")


@pytest.fixture
def gcs_creds(monkeypatch):
    monkeypatch.setattr(settings, "gcs_bucket_name", "bucket")
    monkeypatch.setattr(settings, "gcs_credentials", _GCS_CREDS)


def test_get_storage_service_returns_local_without_creds(no_s3):
    service = get_storage_service(Path("media/avatars"), {"image/png": ".png"})
    assert isinstance(service, FileUploadService)
    assert service.base_dir == Path("media/avatars")


def test_get_storage_service_returns_s3_with_s3_creds(s3_creds):
    service = get_storage_service(Path("media/avatars"), {"image/png": ".png"})
    assert isinstance(service, S3StorageService)
    assert service.prefix == "avatars"
    assert service.allowed_content_types == {"image/png": ".png"}


def test_get_storage_service_returns_gcs_with_gcs_creds(no_s3, gcs_creds):
    service = get_storage_service(Path("media/avatars"), {"image/png": ".png"})
    assert isinstance(service, GCSStorageService)
    assert service.prefix == "avatars"
    assert service.allowed_content_types == {"image/png": ".png"}


def test_get_storage_service_prefers_gcs_when_both_configured(s3_creds, gcs_creds):
    assert isinstance(get_storage_service(Path("media/avatars"), {}), GCSStorageService)


def test_get_storage_service_ignores_partial_s3_creds(no_s3, monkeypatch):
    monkeypatch.setattr(settings, "s3_bucket_name", "bucket")
    assert isinstance(get_storage_service(Path("media/avatars"), {}), FileUploadService)


def test_resolve_file_url_passes_through_legacy_media_path():
    assert resolve_file_url("/media/avatars/2.png") == "/media/avatars/2.png"


@patch("app.services.s3_storage_service.boto3.client")
def test_resolve_file_url_generates_presigned_url_for_s3_key(mock_boto_client, s3_creds):
    mock_client = MagicMock()
    mock_client.generate_presigned_url.return_value = "https://example.com/signed"
    mock_boto_client.return_value = mock_client

    assert resolve_file_url("avatars/2.png") == "https://example.com/signed"


@patch("app.services.gcs_storage_service.storage.Client")
def test_resolve_file_url_generates_signed_url_for_gcs_key(mock_client_cls, gcs_creds):
    blob = mock_client_cls.from_service_account_info.return_value.bucket.return_value.blob.return_value
    blob.generate_signed_url.return_value = "https://example.com/gcs-signed"

    assert resolve_file_url("avatars/2.png") == "https://example.com/gcs-signed"
    blob.generate_signed_url.assert_called_once()
