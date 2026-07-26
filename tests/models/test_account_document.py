"""app.models.account_document: AccountDocument ORM model construction + constraints."""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account_document import AccountDocument
from app.models.user import User
from tests.support.roles import UserRole, role_id_for


async def _make_account_and_user(db_session: AsyncSession, make_account):
    user = User(
        email="account-document-user@example.com",
        hashed_password="x",
        first_name="Rep",
        role_id=await role_id_for(db_session, UserRole.SALES_REP),
    )
    db_session.add(user)
    await db_session.flush()

    account = await make_account(owner_id=user.id, company="Acme Doc Co")
    return account, user


async def test_account_document_persists_with_all_fields_and_inherits_timestamps(
    db_session: AsyncSession, make_account
):
    account, user = await _make_account_and_user(db_session, make_account)

    document = AccountDocument(
        account_id=account.id,
        file_name="proposal.pdf",
        file_url="/media/account_documents/abc.pdf",
        content_type="application/pdf",
        uploaded_by=user.id,
    )
    db_session.add(document)
    await db_session.flush()
    await db_session.refresh(document)

    assert document.id is not None
    assert document.account_id == account.id
    assert document.file_name == "proposal.pdf"
    assert document.file_url == "/media/account_documents/abc.pdf"
    assert document.content_type == "application/pdf"
    assert document.uploaded_by == user.id
    assert document.created_at is not None


async def test_account_id_is_required(db_session: AsyncSession, make_account):
    _, user = await _make_account_and_user(db_session, make_account)

    db_session.add(
        AccountDocument(
            account_id=None,
            file_name="x.pdf",
            file_url="/media/account_documents/x.pdf",
            content_type="application/pdf",
            uploaded_by=user.id,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_uploaded_by_is_required(db_session: AsyncSession, make_account):
    account, _ = await _make_account_and_user(db_session, make_account)

    db_session.add(
        AccountDocument(
            account_id=account.id,
            file_name="x.pdf",
            file_url="/media/account_documents/x.pdf",
            content_type="application/pdf",
            uploaded_by=None,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
