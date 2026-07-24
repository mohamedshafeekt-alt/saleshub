"""AccountActivity business logic: create/list/update/delete a
Note/Meeting/Call/Comment/Follow-up against an Account, gated by the same
existence/ownership check as the rest of the Account API."""

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.permission_codes import ACCOUNTS_DELETE_ANY_ACTIVITY
from app.models.account import Account
from app.models.account_activity import AccountActivity
from app.models.enums import AccountActivityType
from app.models.user import User
from app.schemas.account_activity import AccountActivityCreate, AccountActivityUpdate
from app.services.account_service import AccountAccessForbiddenError, get_account


class AccountActivityNotFoundError(Exception):
    """Raised when an activity id does not exist on the given account."""


async def create_account_activity(
    db: AsyncSession, account_id: int, data: AccountActivityCreate, requester: User
) -> AccountActivity:
    await get_account(db, account_id, requester)

    activity = AccountActivity(
        account_id=account_id, type=data.type, note=data.note, created_by=requester.id
    )
    db.add(activity)
    await db.flush()
    return activity


async def list_account_activities(
    db: AsyncSession,
    account_id: int,
    requester: User,
    *,
    types: list[AccountActivityType] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[AccountActivity]:
    await get_account(db, account_id, requester)

    query = select(AccountActivity).where(AccountActivity.account_id == account_id)
    if types:
        query = query.where(AccountActivity.type.in_(types))
    if date_from is not None:
        query = query.where(AccountActivity.created_at >= date_from)
    if date_to is not None:
        query = query.where(AccountActivity.created_at < date_to)
    query = query.order_by(AccountActivity.created_at.desc())

    result = await db.execute(query)
    return list(result.scalars().all())


async def _get_account_and_activity_or_raise(
    db: AsyncSession, account_id: int, activity_id: int, requester: User
) -> tuple[Account, AccountActivity]:
    account = await get_account(db, account_id, requester)

    result = await db.execute(
        select(AccountActivity)
        .where(AccountActivity.id == activity_id, AccountActivity.account_id == account_id)
        .options(selectinload(AccountActivity.creator), selectinload(AccountActivity.updater))
    )
    activity = result.scalar_one_or_none()
    if activity is None:
        raise AccountActivityNotFoundError(f"Activity not found: {activity_id}")
    return account, activity


async def update_account_activity(
    db: AsyncSession, account_id: int, activity_id: int, data: AccountActivityUpdate, requester: User
) -> AccountActivity:
    account, activity = await _get_account_and_activity_or_raise(db, account_id, activity_id, requester)
    if account.owner_id != requester.id:
        raise AccountAccessForbiddenError(
            f"Only the account owner can edit its activities: account {account_id}"
        )

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(activity, field, value)
    activity.updated_by = requester.id

    await db.flush()
    # updated_at's onupdate is server-computed (func.now() on Base), so after
    # an UPDATE SQLAlchemy marks it expired rather than refetching it --
    # accessing it later outside an async context would raise MissingGreenlet.
    # Refresh now, while still awaitable, and reload updater for updated_by_name.
    await db.refresh(activity)
    await db.refresh(activity, attribute_names=["updater"])
    return activity


async def delete_account_activity(
    db: AsyncSession, account_id: int, activity_id: int, requester: User
) -> None:
    if ACCOUNTS_DELETE_ANY_ACTIVITY not in requester.permission_codes:
        raise AccountAccessForbiddenError(f"Not permitted to delete activities on account: {account_id}")

    _, activity = await _get_account_and_activity_or_raise(db, account_id, activity_id, requester)
    await db.delete(activity)
    await db.flush()
