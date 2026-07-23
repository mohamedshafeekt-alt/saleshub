"""DealDocument business logic: upload/list/delete a proposal/NDA/contract
file against a Deal, gated by the same existence/ownership check as the rest
of the Deal API (delete uses the same get_deal gate as delete_deal itself --
DEALS_VIEW_ALL or ownership -- rather than an owner-only rule, for
consistency with how the Deal record itself may be deleted)."""

from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.deal_document import DealDocument
from app.models.user import User
from app.services.deal_service import get_deal
from app.services.file_upload_service import FileUploadService

__all__ = [
    "DealDocumentNotFoundError",
    "upload_deal_document",
    "list_deal_documents",
    "delete_deal_document",
]

# B2B sales CRM: deal documents are proposals/NDAs/contracts (per the UI
# mockup), so beyond images this needs PDFs and Word docs -- a broader set
# than the avatar upload's images-only allowlist.
_deal_document_upload_service = FileUploadService(
    base_dir=Path("media/deal_documents"),
    allowed_content_types={
        "application/pdf": ".pdf",
        "application/msword": ".doc",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "image/png": ".png",
        "image/jpeg": ".jpg",
    },
)


class DealDocumentNotFoundError(Exception):
    """Raised when a document id does not exist on the given deal."""


async def upload_deal_document(
    db: AsyncSession,
    deal_id: int,
    *,
    content: bytes,
    filename: str,
    content_type: str,
    requester: User,
) -> DealDocument:
    await get_deal(db, deal_id, requester)

    # Unique stem per upload so multiple documents on the same deal don't
    # collide/overwrite each other on disk.
    file_url = _deal_document_upload_service.save(
        content, content_type, filename_stem=f"{deal_id}_{uuid4().hex}"
    )

    document = DealDocument(
        deal_id=deal_id,
        file_name=filename,
        file_url=file_url,
        content_type=content_type,
        uploaded_by=requester.id,
    )
    db.add(document)
    await db.flush()
    return document


async def list_deal_documents(db: AsyncSession, deal_id: int, requester: User) -> list[DealDocument]:
    await get_deal(db, deal_id, requester)

    result = await db.execute(
        select(DealDocument)
        .where(DealDocument.deal_id == deal_id)
        .order_by(DealDocument.created_at.desc(), DealDocument.id.desc())
    )
    return list(result.scalars().all())


async def delete_deal_document(db: AsyncSession, deal_id: int, document_id: int, requester: User) -> None:
    await get_deal(db, deal_id, requester)

    result = await db.execute(
        select(DealDocument).where(DealDocument.id == document_id, DealDocument.deal_id == deal_id)
    )
    document = result.scalar_one_or_none()
    if document is None:
        raise DealDocumentNotFoundError(f"Document not found: {document_id}")

    _deal_document_upload_service.delete(document.file_url)
    await db.delete(document)
    await db.flush()
