from pathlib import Path
from unittest.mock import MagicMock, patch

from app.core.config import settings
from app.services.file_upload_service import FileUploadService
from app.services.s3_storage_service import S3StorageService
from app.services.storage import get_storage_service, resolve_file_url


def test_get_storage_service_returns_local_by_default(monkeypatch):
    monkeypatch.setattr(settings, "storage_backend", "local")
    service = get_storage_service(Path("media/avatars"), {"image/png": ".png"})
    assert isinstance(service, FileUploadService)
    assert service.base_dir == Path("media/avatars")


def test_get_storage_service_returns_s3_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "storage_backend", "s3")
    service = get_storage_service(Path("media/avatars"), {"image/png": ".png"})
    assert isinstance(service, S3StorageService)
    assert service.prefix == "avatars"
    assert service.allowed_content_types == {"image/png": ".png"}


def test_resolve_file_url_passes_through_legacy_media_path():
    assert resolve_file_url("/media/avatars/2.png") == "/media/avatars/2.png"


@patch("app.services.s3_storage_service.boto3.client")
def test_resolve_file_url_generates_presigned_url_for_s3_key(mock_boto_client):
    mock_client = MagicMock()
    mock_client.generate_presigned_url.return_value = "https://example.com/signed"
    mock_boto_client.return_value = mock_client

    assert resolve_file_url("avatars/2.png") == "https://example.com/signed"
