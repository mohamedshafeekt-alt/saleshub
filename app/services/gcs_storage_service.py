"""GCS-backed storage: same save()/delete() shape as FileUploadService, plus
generate_presigned_url() for reads (buckets stay private; clients get a
short-lived signed link instead of a public URL)."""

from datetime import timedelta

from google.api_core.exceptions import GoogleAPIError
from google.cloud import storage  # type: ignore[import-untyped]

from app.core.config import settings
from app.services.file_upload_service import UnsupportedFileTypeError

__all__ = ["GCSStorageService", "StorageError", "generate_presigned_url"]

_PRESIGNED_URL_EXPIRY = timedelta(seconds=900)


class StorageError(Exception):
    """Raised when a GCS call fails (wraps google.api_core.exceptions.GoogleAPIError)."""


def _bucket() -> storage.Bucket:
    # Service-account key (not ADC) because signing URLs needs a private key.
    client = storage.Client.from_service_account_info(settings.gcs_credentials)
    return client.bucket(settings.gcs_bucket_name)


def generate_presigned_url(key: str) -> str:
    try:
        return _bucket().blob(key).generate_signed_url(
            version="v4", expiration=_PRESIGNED_URL_EXPIRY, method="GET"
        )
    except (GoogleAPIError, ValueError) as exc:
        raise StorageError(f"Failed to generate url for {key}") from exc


class GCSStorageService:
    def __init__(self, prefix: str, allowed_content_types: dict[str, str]):
        self.prefix = prefix
        self.allowed_content_types = allowed_content_types  # content_type -> extension

    def save(self, content: bytes, content_type: str, filename_stem: str) -> str:
        """Validates content_type, uploads to GCS under '{prefix}/{filename_stem}{ext}',
        returns that key (stored in the DB in place of a local file path)."""
        extension = self.allowed_content_types.get(content_type)
        if extension is None:
            raise UnsupportedFileTypeError(f"Unsupported file type: {content_type}")

        key = f"{self.prefix}/{filename_stem}{extension}"
        try:
            _bucket().blob(key).upload_from_string(content, content_type=content_type)
        except GoogleAPIError as exc:
            raise StorageError(f"Failed to upload {key}") from exc
        return key

    def delete(self, key: str) -> None:
        try:
            _bucket().blob(key).delete()
        except GoogleAPIError as exc:
            raise StorageError(f"Failed to delete {key}") from exc
