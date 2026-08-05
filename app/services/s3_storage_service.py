"""S3-backed storage: same save()/delete() shape as FileUploadService, plus
generate_presigned_url() for reads (buckets stay private; clients get a
short-lived signed link instead of a public URL)."""

import boto3
from botocore.exceptions import ClientError

from app.core.config import settings
from app.services.file_upload_service import UnsupportedFileTypeError

__all__ = ["S3StorageService", "StorageError", "generate_presigned_url"]

_PRESIGNED_URL_EXPIRY_SECONDS = 900


class StorageError(Exception):
    """Raised when an S3 call fails (wraps botocore.exceptions.ClientError)."""


def _client():
    return boto3.client(
        "s3",
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )


def generate_presigned_url(key: str) -> str:
    try:
        return _client().generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.s3_bucket_name, "Key": key},
            ExpiresIn=_PRESIGNED_URL_EXPIRY_SECONDS,
        )
    except ClientError as exc:
        raise StorageError(f"Failed to generate url for {key}") from exc


class S3StorageService:
    def __init__(self, prefix: str, allowed_content_types: dict[str, str]):
        self.prefix = prefix
        self.allowed_content_types = allowed_content_types  # content_type -> extension

    def save(self, content: bytes, content_type: str, filename_stem: str) -> str:
        """Validates content_type, uploads to S3 under '{prefix}/{filename_stem}{ext}',
        returns that key (stored in the DB in place of a local file path)."""
        extension = self.allowed_content_types.get(content_type)
        if extension is None:
            raise UnsupportedFileTypeError(f"Unsupported file type: {content_type}")

        key = f"{self.prefix}/{filename_stem}{extension}"
        try:
            _client().put_object(
                Bucket=settings.s3_bucket_name, Key=key, Body=content, ContentType=content_type
            )
        except ClientError as exc:
            raise StorageError(f"Failed to upload {key}") from exc
        return key

    def delete(self, key: str) -> None:
        try:
            _client().delete_object(Bucket=settings.s3_bucket_name, Key=key)
        except ClientError as exc:
            raise StorageError(f"Failed to delete {key}") from exc
