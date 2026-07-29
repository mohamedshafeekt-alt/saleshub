"""Combined Document listing: unions AccountDocument and DealDocument rows
for the cross-entity Documents view. Read-only -- upload/delete stay on the
per-account/per-deal endpoints (app.services.account_document_service /
deal_document_service); this only answers "show me everything already
uploaded, across accounts and deals, that I have access to", scoped by the
same ownership rule (ACCOUNTS_VIEW_ALL/DEALS_VIEW_ALL vs owner_id) used by
the account and deal list endpoints."""

from typing import Literal, Sequence

from sqlalchemy import Row, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permission_codes import ACCOUNTS_VIEW_ALL, DEALS_VIEW_ALL
from app.models.account import Account
from app.models.account_document import AccountDocument
from app.models.deal import Deal
from app.models.deal_document import DealDocument
from app.models.user import User
from app.schemas.document import DocumentRead

__all__ = ["list_documents"]


async def list_documents(
    db: AsyncSession,
    requester: User,
    *,
    source: Literal["account", "deal"] | None = None,
    search: str | None = None,
) -> list[DocumentRead]:
    account_rows: Sequence[Row[tuple[AccountDocument, str]]] = []
    if source != "deal":
        account_query = select(AccountDocument, Account.company).join(
            Account, Account.id == AccountDocument.account_id
        )
        if ACCOUNTS_VIEW_ALL not in requester.permission_codes:
            account_query = account_query.where(Account.owner_id == requester.id)
        if search:
            account_query = account_query.where(AccountDocument.file_name.ilike(f"%{search}%"))
        account_rows = (await db.execute(account_query)).all()

    deal_rows: Sequence[Row[tuple[DealDocument, str]]] = []
    if source != "account":
        deal_query = select(DealDocument, Deal.deal_name).join(Deal, Deal.id == DealDocument.deal_id)
        if DEALS_VIEW_ALL not in requester.permission_codes:
            deal_query = deal_query.where(Deal.owner_id == requester.id)
        if search:
            deal_query = deal_query.where(DealDocument.file_name.ilike(f"%{search}%"))
        deal_rows = (await db.execute(deal_query)).all()

    documents = [
        DocumentRead(
            id=doc.id,
            source="account",
            entity_id=doc.account_id,
            entity_name=company,
            file_name=doc.file_name,
            file_url=doc.file_url,
            content_type=doc.content_type,
            uploaded_by=doc.uploaded_by,
            created_at=doc.created_at,
        )
        for doc, company in account_rows
    ] + [
        DocumentRead(
            id=doc.id,
            source="deal",
            entity_id=doc.deal_id,
            entity_name=deal_name,
            file_name=doc.file_name,
            file_url=doc.file_url,
            content_type=doc.content_type,
            uploaded_by=doc.uploaded_by,
            created_at=doc.created_at,
        )
        for doc, deal_name in deal_rows
    ]
    documents.sort(key=lambda d: (d.created_at, d.id), reverse=True)
    return documents
