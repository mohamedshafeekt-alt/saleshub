"""Account business logic: role-scoped listing/search, ownership-checked
get/update/delete, and Lead -> Account conversion."""

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.enums import LeadTier
from app.models.user import User, UserRole
from app.schemas.account import AccountCreate, AccountUpdate
from app.services.lead_service import get_lead


class AccountNotFoundError(Exception):
    """Raised when an account id does not exist."""


class AccountAccessForbiddenError(Exception):
    """Raised when a Sales Rep tries to access an account they don't own."""


class LeadAlreadyConvertedError(Exception):
    """Raised when attempting to convert a lead that was already converted."""


class LeadMissingFieldsForConversionError(Exception):
    """Raised when a lead has no tier and/or owner and none was supplied at conversion time."""


async def create_account(db: AsyncSession, data: AccountCreate) -> Account:
    account = Account(**data.model_dump())
    db.add(account)
    await db.flush()
    return account


async def list_accounts(
    db: AsyncSession,
    *,
    requester: User,
    owner_id: int | None = None,
    tier: LeadTier | None = None,
    search: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[Account]:
    if requester.role == UserRole.SALES_REP:
        owner_id = requester.id

    query = select(Account)
    if search is not None:
        query = query.join(User, Account.owner_id == User.id)

    if owner_id is not None:
        query = query.where(Account.owner_id == owner_id)
    if tier is not None:
        query = query.where(Account.tier == tier)
    if search is not None:
        pattern = f"%{search}%"
        query = query.where(
            or_(
                Account.company.ilike(pattern),
                User.first_name.ilike(pattern),
                User.last_name.ilike(pattern),
            )
        )

    query = query.order_by(Account.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(query)
    return list(result.scalars().all())


async def _get_account_or_raise(db: AsyncSession, account_id: int, requester: User) -> Account:
    result = await db.execute(select(Account).where(Account.id == account_id))
    account = result.scalar_one_or_none()
    if account is None:
        raise AccountNotFoundError(f"Account not found: {account_id}")
    if requester.role == UserRole.SALES_REP and account.owner_id != requester.id:
        raise AccountAccessForbiddenError(f"Not permitted to access account: {account_id}")
    return account


async def get_account(db: AsyncSession, account_id: int, requester: User) -> Account:
    return await _get_account_or_raise(db, account_id, requester)


async def update_account(db: AsyncSession, account_id: int, data: AccountUpdate, requester: User) -> Account:
    account = await _get_account_or_raise(db, account_id, requester)

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(account, field, value)

    await db.flush()
    return account


async def delete_account(db: AsyncSession, account_id: int, requester: User) -> None:
    account = await _get_account_or_raise(db, account_id, requester)
    await db.delete(account)
    await db.flush()


async def convert_lead_to_account(
    db: AsyncSession,
    lead_id: int,
    requester: User,
    tier: LeadTier | None = None,
    owner_id: int | None = None,
) -> Account:
    lead = await get_lead(db, lead_id, requester)

    if lead.is_converted:
        raise LeadAlreadyConvertedError(f"Lead already converted: {lead_id}")

    resolved_tier = tier or lead.tier
    resolved_owner_id = owner_id or lead.owner_id
    missing = [
        name
        for name, value in (("tier", resolved_tier), ("owner_id", resolved_owner_id))
        if value is None
    ]
    if missing:
        raise LeadMissingFieldsForConversionError(
            f"Lead {lead_id} is missing required field(s) for conversion: {', '.join(missing)}"
        )

    account = Account(
        company=lead.company,
        domain=lead.domain,
        tier=resolved_tier,
        owner_id=resolved_owner_id,
        source_lead_id=lead.id,
    )
    db.add(account)
    lead.is_converted = True
    await db.flush()
    return account
