"""app.services.deal_document_service: upload/list/delete a deal document.

Covers: successful upload (persists row, writes file to disk); rejecting an
unsupported content type; not-found/forbidden gating reuses Deal's own
existence/ownership check; list returns newest-first; delete removes both the
row and the file on disk; deleting a missing document id raises.
"""

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services.deal_document_service import (
    DealDocumentNotFoundError,
    delete_deal_document,
    list_deal_documents,
    upload_deal_document,
)
from app.services.deal_service import DealAccessForbiddenError, DealNotFoundError
from app.services.file_upload_service import UnsupportedFileTypeError
from tests.support.roles import UserRole, role_id_for


async def _make_user(db_session: AsyncSession, email: str, role: UserRole) -> User:
    user = User(email=email, hashed_password="x", first_name="Test", role_id=await role_id_for(db_session, role))
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user, attribute_names=["role"])
    return user


async def _make_deal(make_account, make_deal, owner):
    account = await make_account(owner_id=owner.id, company=f"Acme {owner.email}")
    return await make_deal(account_id=account.id, owner_id=owner.id, deal_name=f"Deal for {owner.email}")


async def test_upload_deal_document_succeeds_and_writes_file(
    db_session: AsyncSession, make_account, make_deal
):
    owner = await _make_user(db_session, "owner-upload-doc@example.com", UserRole.SALES_REP)
    deal = await _make_deal(make_account, make_deal, owner)

    document = await upload_deal_document(
        db_session,
        deal.id,
        content=b"%PDF-1.4 fake",
        filename="proposal.pdf",
        content_type="application/pdf",
        requester=owner,
    )

    assert document.id is not None
    assert document.deal_id == deal.id
    assert document.file_name == "proposal.pdf"
    assert document.content_type == "application/pdf"
    assert document.uploaded_by == owner.id
    assert document.file_url.startswith("/media/deal_documents/")
    assert Path(document.file_url.lstrip("/")).read_bytes() == b"%PDF-1.4 fake"

    Path(document.file_url.lstrip("/")).unlink()


async def test_upload_deal_document_rejects_unsupported_content_type(
    db_session: AsyncSession, make_account, make_deal
):
    owner = await _make_user(db_session, "owner-upload-doc-bad-type@example.com", UserRole.SALES_REP)
    deal = await _make_deal(make_account, make_deal, owner)

    with pytest.raises(UnsupportedFileTypeError):
        await upload_deal_document(
            db_session,
            deal.id,
            content=b"whatever",
            filename="virus.exe",
            content_type="application/x-msdownload",
            requester=owner,
        )


async def test_upload_deal_document_raises_not_found_for_missing_deal(db_session: AsyncSession):
    requester = await _make_user(db_session, "upload-doc-requester@example.com", UserRole.SALES_MANAGER)

    with pytest.raises(DealNotFoundError):
        await upload_deal_document(
            db_session,
            999_999,
            content=b"x",
            filename="x.pdf",
            content_type="application/pdf",
            requester=requester,
        )


async def test_upload_deal_document_raises_forbidden_for_non_owning_sales_rep(
    db_session: AsyncSession, make_account, make_deal
):
    owner = await _make_user(db_session, "owner-upload-doc-forbidden@example.com", UserRole.SALES_REP)
    other_rep = await _make_user(db_session, "other-rep-upload-doc@example.com", UserRole.SALES_REP)
    deal = await _make_deal(make_account, make_deal, owner)

    with pytest.raises(DealAccessForbiddenError):
        await upload_deal_document(
            db_session,
            deal.id,
            content=b"x",
            filename="x.pdf",
            content_type="application/pdf",
            requester=other_rep,
        )


async def test_list_deal_documents_returns_newest_first(db_session: AsyncSession, make_account, make_deal):
    owner = await _make_user(db_session, "owner-list-doc@example.com", UserRole.SALES_REP)
    deal = await _make_deal(make_account, make_deal, owner)

    first = await upload_deal_document(
        db_session, deal.id, content=b"1", filename="a.pdf", content_type="application/pdf", requester=owner
    )
    second = await upload_deal_document(
        db_session, deal.id, content=b"2", filename="b.pdf", content_type="application/pdf", requester=owner
    )

    results = await list_deal_documents(db_session, deal.id, owner)

    assert [doc.id for doc in results] == [second.id, first.id]

    for doc in (first, second):
        Path(doc.file_url.lstrip("/")).unlink()


async def test_delete_deal_document_removes_row_and_file(db_session: AsyncSession, make_account, make_deal):
    owner = await _make_user(db_session, "owner-delete-doc@example.com", UserRole.SALES_REP)
    deal = await _make_deal(make_account, make_deal, owner)
    document = await upload_deal_document(
        db_session, deal.id, content=b"x", filename="x.pdf", content_type="application/pdf", requester=owner
    )
    file_path = Path(document.file_url.lstrip("/"))
    assert file_path.exists()

    await delete_deal_document(db_session, deal.id, document.id, requester=owner)

    assert not file_path.exists()
    with pytest.raises(DealDocumentNotFoundError):
        await delete_deal_document(db_session, deal.id, document.id, requester=owner)
