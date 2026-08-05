from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from app.core.config import settings
from app.services.file_upload_service import UnsupportedFileTypeError
from app.services.s3_storage_service import S3StorageService, StorageError, generate_presigned_url


@patch("app.services.s3_storage_service.boto3.client")
def test_save_uploads_to_s3_and_returns_key(mock_boto_client):
    mock_client = MagicMock()
    mock_boto_client.return_value = mock_client
    service = S3StorageService(prefix="avatars", allowed_content_types={"image/png": ".png"})

    key = service.save(b"fake-bytes", "image/png", filename_stem="7")

    assert key == "avatars/7.png"
    mock_client.put_object.assert_called_once_with(
        Bucket=settings.s3_bucket_name, Key="avatars/7.png", Body=b"fake-bytes", ContentType="image/png"
    )


@patch("app.services.s3_storage_service.boto3.client")
def test_save_rejects_unsupported_content_type(mock_boto_client):
    service = S3StorageService(prefix="avatars", allowed_content_types={"image/png": ".png"})

    with pytest.raises(UnsupportedFileTypeError):
        service.save(b"x", "application/pdf", filename_stem="7")

    mock_boto_client.return_value.put_object.assert_not_called()


@patch("app.services.s3_storage_service.boto3.client")
def test_save_wraps_client_error(mock_boto_client):
    mock_client = MagicMock()
    mock_client.put_object.side_effect = ClientError({"Error": {"Code": "500", "Message": "boom"}}, "PutObject")
    mock_boto_client.return_value = mock_client
    service = S3StorageService(prefix="avatars", allowed_content_types={"image/png": ".png"})

    with pytest.raises(StorageError):
        service.save(b"x", "image/png", filename_stem="7")


@patch("app.services.s3_storage_service.boto3.client")
def test_delete_calls_delete_object(mock_boto_client):
    mock_client = MagicMock()
    mock_boto_client.return_value = mock_client
    service = S3StorageService(prefix="avatars", allowed_content_types={})

    service.delete("avatars/7.png")

    mock_client.delete_object.assert_called_once_with(Bucket=settings.s3_bucket_name, Key="avatars/7.png")


@patch("app.services.s3_storage_service.boto3.client")
def test_delete_wraps_client_error(mock_boto_client):
    mock_client = MagicMock()
    mock_client.delete_object.side_effect = ClientError({"Error": {"Code": "500", "Message": "boom"}}, "DeleteObject")
    mock_boto_client.return_value = mock_client
    service = S3StorageService(prefix="avatars", allowed_content_types={})

    with pytest.raises(StorageError):
        service.delete("avatars/7.png")


@patch("app.services.s3_storage_service.boto3.client")
def test_generate_presigned_url_calls_boto(mock_boto_client):
    mock_client = MagicMock()
    mock_client.generate_presigned_url.return_value = "https://example.com/signed"
    mock_boto_client.return_value = mock_client

    url = generate_presigned_url("avatars/7.png")

    assert url == "https://example.com/signed"
    mock_client.generate_presigned_url.assert_called_once_with(
        "get_object", Params={"Bucket": settings.s3_bucket_name, "Key": "avatars/7.png"}, ExpiresIn=900
    )


@patch("app.services.s3_storage_service.boto3.client")
def test_generate_presigned_url_wraps_client_error(mock_boto_client):
    mock_client = MagicMock()
    mock_client.generate_presigned_url.side_effect = ClientError(
        {"Error": {"Code": "500", "Message": "boom"}}, "GeneratePresignedUrl"
    )
    mock_boto_client.return_value = mock_client

    with pytest.raises(StorageError):
        generate_presigned_url("avatars/7.png")
