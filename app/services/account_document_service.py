"""AccountDocument business logic: upload/list/delete a supporting file
against an Account, gated by the same existence/ownership check as the rest
of the Account API (delete uses the same get_account gate as delete_account
itself -- ACCOUNTS_VIEW_ALL or ownership -- rather than an owner-only rule,
for consistency with how the Account record itself may be deleted)."""

from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account_document import AccountDocument
from app.models.user import User
from app.services.account_service import get_account
from app.services.file_upload_service import FileUploadService

__all__ = [
    "AccountDocumentNotFoundError",
    "upload_account_document",
    "list_account_documents",
    "delete_account_document",
]

# Same broader allowlist as deal documents (proposals/NDAs/contracts, plus
# images) rather than the avatar upload's images-only allowlist.
_account_document_upload_service = FileUploadService(
    base_dir=Path("media/account_documents"),
    allowed_content_types={
        "application/pdf": ".pdf",
        "application/msword": ".doc",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "image/png": ".png",
        "image/jpeg": ".jpg",
    },
)


class AccountDocumentNotFoundError(Exception):
    """Raised when a document id does not exist on the given account."""


async def upload_account_document(
    db: AsyncSession,
    account_id: int,
    *,
    content: bytes,
    filename: str,
    content_type: str,
    requester: User,
) -> AccountDocument:
    await get_account(db, account_id, requester)

    # Unique stem per upload so multiple documents on the same account don't
    # collide/overwrite each other on disk.
    file_url = _account_document_upload_service.save(
        content, content_type, filename_stem=f"{account_id}_{uuid4().hex}"
    )

    document = AccountDocument(
        account_id=account_id,
        file_name=filename,
        file_url=file_url,
        content_type=content_type,
        uploaded_by=requester.id,
    )
    db.add(document)
    await db.flush()
    return document


async def list_account_documents(db: AsyncSession, account_id: int, requester: User) -> list[AccountDocument]:
    await get_account(db, account_id, requester)

    result = await db.execute(
        select(AccountDocument)
        .where(AccountDocument.account_id == account_id)
        .order_by(AccountDocument.created_at.desc(), AccountDocument.id.desc())
    )
    return list(result.scalars().all())


async def delete_account_document(db: AsyncSession, account_id: int, document_id: int, requester: User) -> None:
    await get_account(db, account_id, requester)

    result = await db.execute(
        select(AccountDocument).where(
            AccountDocument.id == document_id, AccountDocument.account_id == account_id
        )
    )
    document = result.scalar_one_or_none()
    if document is None:
        raise AccountDocumentNotFoundError(f"Document not found: {document_id}")

    _account_document_upload_service.delete(document.file_url)
    await db.delete(document)
    await db.flush()
