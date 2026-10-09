"""Picks local-disk vs S3 vs GCS storage by which credentials are configured
(GCS wins if both are set), and resolves a stored file reference back to a
URL a client can fetch.

Legacy DB rows (uploaded before the cloud-storage switch) hold local paths
starting with '/media/'; new rows hold bare object keys like 'avatars/2.png'.
That shape is the discriminator -- no new DB column, and unmigrated legacy
files keep working indefinitely. Keys don't record which cloud they live in,
so switching between S3 and GCS needs the objects copied across."""

from pathlib import Path
from typing import Literal

from app.core.config import settings
from app.services import gcs_storage_service, s3_storage_service
from app.services.file_upload_service import FileUploadService
from app.services.gcs_storage_service import GCSStorageService
from app.services.s3_storage_service import S3StorageService

__all__ = ["get_storage_service", "resolve_file_url", "storage_backend"]


def storage_backend() -> Literal["gcs", "s3", "local"]:
    if settings.gcs_bucket_name and settings.gcs_credentials:
        return "gcs"
    if settings.s3_bucket_name and settings.aws_access_key_id and settings.aws_secret_access_key:
        return "s3"
    return "local"


def get_storage_service(
    base_dir: Path, allowed_content_types: dict[str, str]
) -> FileUploadService | S3StorageService | GCSStorageService:
    backend = storage_backend()
    if backend == "gcs":
        return GCSStorageService(prefix=base_dir.name, allowed_content_types=allowed_content_types)
    if backend == "s3":
        return S3StorageService(prefix=base_dir.name, allowed_content_types=allowed_content_types)
    return FileUploadService(base_dir=base_dir, allowed_content_types=allowed_content_types)


def resolve_file_url(file_ref: str) -> str:
    if file_ref.startswith("/media/"):
        return file_ref
    if storage_backend() == "gcs":
        return gcs_storage_service.generate_presigned_url(file_ref)
    return s3_storage_service.generate_presigned_url(file_ref)
