"""app.models.deal_document: DealDocument ORM model construction + constraints."""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.deal_document import DealDocument
from app.models.user import User
from tests.support.roles import UserRole, role_id_for


async def _make_deal_and_user(db_session: AsyncSession, make_account, make_deal):
    user = User(
        email="deal-document-user@example.com",
        hashed_password="x",
        first_name="Rep",
        role_id=await role_id_for(db_session, UserRole.SALES_REP),
    )
    db_session.add(user)
    await db_session.flush()

    account = await make_account(owner_id=user.id, company="Acme Doc Co")
    deal = await make_deal(account_id=account.id, owner_id=user.id, deal_name="Doc Deal")
    return deal, user


async def test_deal_document_persists_with_all_fields_and_inherits_timestamps(
    db_session: AsyncSession, make_account, make_deal
):
    deal, user = await _make_deal_and_user(db_session, make_account, make_deal)

    document = DealDocument(
        deal_id=deal.id,
        file_name="proposal.pdf",
        file_url="/media/deal_documents/abc.pdf",
        content_type="application/pdf",
        uploaded_by=user.id,
    )
    db_session.add(document)
    await db_session.flush()
    await db_session.refresh(document)

    assert document.id is not None
    assert document.deal_id == deal.id
    assert document.file_name == "proposal.pdf"
    assert document.file_url == "/media/deal_documents/abc.pdf"
    assert document.content_type == "application/pdf"
    assert document.uploaded_by == user.id
    assert document.created_at is not None


async def test_deal_id_is_required(db_session: AsyncSession, make_account, make_deal):
    _, user = await _make_deal_and_user(db_session, make_account, make_deal)

    db_session.add(
        DealDocument(
            deal_id=None,
            file_name="x.pdf",
            file_url="/media/deal_documents/x.pdf",
            content_type="application/pdf",
            uploaded_by=user.id,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_uploaded_by_is_required(db_session: AsyncSession, make_account, make_deal):
    deal, _ = await _make_deal_and_user(db_session, make_account, make_deal)

    db_session.add(
        DealDocument(
            deal_id=deal.id,
            file_name="x.pdf",
            file_url="/media/deal_documents/x.pdf",
            content_type="application/pdf",
            uploaded_by=None,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
