"""Global search: name-only lookup across leads, accounts, deals, and contacts."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.contact import Contact
from app.models.deal import Deal
from app.models.lead import Lead
from app.schemas.search import SearchResult


async def global_search(db: AsyncSession, q: str, *, limit: int = 5) -> list[SearchResult]:
    term = q.strip()
    if not term:
        return []
    pattern = f"%{term}%"

    person_name = func.concat_ws(" ", Lead.first_name, Lead.last_name)
    lead_rows = (
        await db.execute(
            select(Lead.id, person_name).where(person_name.ilike(pattern)).limit(limit)
        )
    ).all()

    account_rows = (
        await db.execute(
            select(Account.id, Account.company).where(Account.company.ilike(pattern)).limit(limit)
        )
    ).all()

    deal_rows = (
        await db.execute(
            select(Deal.id, Deal.deal_name).where(Deal.deal_name.ilike(pattern)).limit(limit)
        )
    ).all()

    contact_name = func.concat_ws(" ", Contact.first_name, Contact.last_name)
    contact_rows = (
        await db.execute(
            select(Contact.id, contact_name).where(contact_name.ilike(pattern)).limit(limit)
        )
    ).all()

    return [
        *(SearchResult(id=row.id, label="Lead", name=row[1]) for row in lead_rows),
        *(SearchResult(id=row.id, label="Account", name=row[1]) for row in account_rows),
        *(SearchResult(id=row.id, label="Deal", name=row[1]) for row in deal_rows),
        *(SearchResult(id=row.id, label="Contact", name=row[1]) for row in contact_rows),
    ]
