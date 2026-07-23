"""Shared local-disk file upload helper, used by avatar upload and deal
document upload. Class-based by deliberate exception (every other service in
this codebase is flat functions) since two call sites need the same
validate-then-write-then-return-url behaviour parameterised by directory and
allowed content types."""

from pathlib import Path

__all__ = ["FileUploadService", "UnsupportedFileTypeError"]


class UnsupportedFileTypeError(Exception):
    """Raised when a file's content-type isn't in the allowed set."""


class FileUploadService:
    def __init__(self, base_dir: Path, allowed_content_types: dict[str, str]):
        self.base_dir = base_dir
        self.allowed_content_types = allowed_content_types  # content_type -> extension

    def save(self, content: bytes, content_type: str, filename_stem: str) -> str:
        """Validates content_type, writes content to base_dir/<filename_stem><ext>,
        returns the public-facing relative url (e.g. '/media/...')."""
        extension = self.allowed_content_types.get(content_type)
        if extension is None:
            raise UnsupportedFileTypeError(f"Unsupported file type: {content_type}")

        self.base_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{filename_stem}{extension}"
        (self.base_dir / filename).write_bytes(content)

        return f"/{self.base_dir}/{filename}"

    def delete(self, file_url: str) -> None:
        """Removes the file referenced by a url previously returned by save().
        Silently no-ops if it's already gone."""
        path = Path(file_url.lstrip("/"))
        path.unlink(missing_ok=True)
