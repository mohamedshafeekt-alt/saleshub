"""Picks local-disk vs S3 storage per settings.storage_backend, and resolves
a stored file reference back to a URL a client can fetch.

Legacy DB rows (uploaded before the S3 switch) hold local paths starting
with '/media/'; new rows hold bare S3 keys like 'avatars/2.png'. That shape
is the discriminator -- no new DB column, and unmigrated legacy files keep
working indefinitely."""

from pathlib import Path

from app.core.config import settings
from app.services.file_upload_service import FileUploadService
from app.services.s3_storage_service import S3StorageService, generate_presigned_url

__all__ = ["get_storage_service", "resolve_file_url"]


def get_storage_service(
    base_dir: Path, allowed_content_types: dict[str, str]
) -> FileUploadService | S3StorageService:
    if settings.storage_backend == "s3":
        return S3StorageService(prefix=base_dir.name, allowed_content_types=allowed_content_types)
    return FileUploadService(base_dir=base_dir, allowed_content_types=allowed_content_types)


def resolve_file_url(file_ref: str) -> str:
    if file_ref.startswith("/media/"):
        return file_ref
    return generate_presigned_url(file_ref)
