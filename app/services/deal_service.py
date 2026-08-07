"""Deal business logic: account/stage-existence-gated creation with initial
stage history, role-scoped listing/search/sort (flat or grouped-by-stage
board), ownership-checked get/update/delete, stage-transition history
logging, cold-reason enforcement (driven by the referenced DealStage's
`is_cold` flag, not a hardcoded enum comparison), and xlsx export rows."""

from typing import Any, Literal

from sqlalchemy import ColumnElement, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permission_codes import DEALS_VIEW_ALL
from app.models.account import Account
from app.models.contact import Contact
from app.models.deal import Deal
from app.models.deal_contact import DealContact
from app.models.deal_stage import DealStage
from app.models.deal_stage_history import DealStageHistory
from app.models.enums import AuditAction, LeadTier, NotificationType
from app.models.user import User
from app.schemas.deal import DealCreate, DealUpdate
from app.services.account_service import AccountNotFoundError, get_account
from app.services.audit_service import log_audit
from app.services.contact_service import ContactNotFoundError, get_contact
from app.services.notification_service import create_notification

SortBy = Literal["value", "expected_close_date", "created_at"]
SortDir = Literal["asc", "desc"]

_SORT_COLUMNS: dict[str, ColumnElement[Any]] = {
    "value": Deal.value.expression,
    "expected_close_date": Deal.expected_close_date.expression,
    "created_at": Deal.created_at.expression,
}


class DealNotFoundError(Exception):
    """Raised when a deal id does not exist."""


class DealAccessForbiddenError(Exception):
    """Raised when a Sales Rep tries to access a deal they don't own."""


class ColdReasonRequiredError(Exception):
    """Raised when a deal's stage is cold (DealStage.is_cold) without a cold_reason."""


class DealStageNotFoundError(Exception):
    """Raised when a deal's stage_id does not reference an existing DealStage."""


async def _get_stage_or_raise(db: AsyncSession, stage_id: int) -> DealStage:
    stage = await db.get(DealStage, stage_id)
    if stage is None:
        raise DealStageNotFoundError(f"Deal stage not found: {stage_id}")
    return stage


async def _assert_contacts_exist(db: AsyncSession, contact_ids: list[int]) -> None:
    if not contact_ids:
        return
    result = await db.execute(select(Contact.id).where(Contact.id.in_(contact_ids)))
    found = set(result.scalars().all())
    missing = set(contact_ids) - found
    if missing:
        raise ContactNotFoundError(f"Contact not found: {sorted(missing)}")


async def _set_deal_contacts(db: AsyncSession, deal_id: int, contact_ids: list[int]) -> None:
    """Replace deal_id's contact links entirely with contact_ids."""
    await _assert_contacts_exist(db, contact_ids)
    await db.execute(delete(DealContact).where(DealContact.deal_id == deal_id))
    for contact_id in contact_ids:
        db.add(DealContact(deal_id=deal_id, contact_id=contact_id))
    await db.flush()


_CONTACT_NAME = func.trim(
    func.concat(func.coalesce(Contact.first_name, ""), " ", func.coalesce(Contact.last_name, ""))
)


async def get_deal_contact_ids(db: AsyncSession, deal_id: int) -> list[tuple[int, str, str, str | None]]:
    result = await db.execute(
        select(DealContact.contact_id, _CONTACT_NAME, Contact.email, Contact.phone)
        .join(Contact, Contact.id == DealContact.contact_id)
        .where(DealContact.deal_id == deal_id)
    )
    return [(cid, name, email, phone) for cid, name, email, phone in result.all()]


async def get_deal_contact_ids_by_deal(
    db: AsyncSession, deal_ids: list[int]
) -> dict[int, list[tuple[int, str, str, str | None]]]:
    """Batched contact id+name+email+phone lookup for a list of deal ids, to avoid N+1 in list/board views."""
    if not deal_ids:
        return {}
    result = await db.execute(
        select(DealContact.deal_id, DealContact.contact_id, _CONTACT_NAME, Contact.email, Contact.phone)
        .join(Contact, Contact.id == DealContact.contact_id)
        .where(DealContact.deal_id.in_(deal_ids))
    )
    by_deal: dict[int, list[tuple[int, str, str, str | None]]] = {deal_id: [] for deal_id in deal_ids}
    for deal_id, contact_id, name, email, phone in result.all():
        by_deal[deal_id].append((contact_id, name, email, phone))
    return by_deal


async def create_deal(db: AsyncSession, data: DealCreate, requester: User) -> Deal:
    result = await db.execute(select(Account).where(Account.id == data.account_id))
    if result.scalar_one_or_none() is None:
        raise AccountNotFoundError(f"Account not found: {data.account_id}")

    stage = await _get_stage_or_raise(db, data.stage_id)

    if stage.is_cold and data.cold_reason is None:
        raise ColdReasonRequiredError("cold_reason is required when the stage is cold")

    await _assert_contacts_exist(db, data.contact_ids)

    deal_fields = data.model_dump(exclude={"contact_ids"})
    deal = Deal(**deal_fields)
    db.add(deal)
    await db.flush()

    for contact_id in data.contact_ids:
        db.add(DealContact(deal_id=deal.id, contact_id=contact_id))

    db.add(
        DealStageHistory(
            deal_id=deal.id, from_stage_id=None, to_stage_id=deal.stage_id, changed_by=requester.id
        )
    )
    await db.flush()
    await log_audit(
        db, table_name="deals", record_id=deal.id, action=AuditAction.CREATED,
        actor_id=requester.id, description=f"Deal '{deal.deal_name}' created",
    )
    # deal is a freshly-constructed instance, never loaded via a `select(Deal)`
    # -- account/stage/owner (lazy="joined" only applies to query-time loads)
    # are unpopulated relationship attributes. Accessing them later to build
    # DealRead would trigger an implicit lazy load, which crashes
    # (MissingGreenlet) because that happens outside any awaited call. Whether
    # it accidentally works instead depends on those rows still being
    # strongly referenced elsewhere in the session (e.g. the account/stage
    # lookups above going out of scope) -- not something to rely on.
    await db.refresh(deal, attribute_names=["account", "stage", "owner"])
    return deal


def _deal_filters(
    *,
    requester: User,
    owner_id: int | None,
    account_id: int | None,
    stage_id: int | None,
    tier: list[LeadTier] | None,
    search: str | None,
) -> tuple[list[Any], int | None, bool]:
    if DEALS_VIEW_ALL not in requester.permission_codes:
        owner_id = requester.id

    filters: list[Any] = []
    if owner_id is not None:
        filters.append(Deal.owner_id == owner_id)
    if account_id is not None:
        filters.append(Deal.account_id == account_id)
    if stage_id is not None:
        filters.append(Deal.stage_id == stage_id)
    if tier:
        filters.append(Deal.tier.in_(tier))

    needs_account_join = search is not None
    if search is not None:
        pattern = f"%{search}%"
        filters.append(or_(Deal.deal_name.ilike(pattern), Account.company.ilike(pattern)))

    return filters, owner_id, needs_account_join


def _order_by(sort_by: SortBy, sort_dir: SortDir) -> ColumnElement[Any]:
    column = _SORT_COLUMNS[sort_by]
    return column.desc() if sort_dir == "desc" else column.asc()


async def list_deals(
    db: AsyncSession,
    *,
    requester: User,
    owner_id: int | None = None,
    account_id: int | None = None,
    stage_id: int | None = None,
    tier: list[LeadTier] | None = None,
    search: str | None = None,
    sort_by: SortBy = "created_at",
    sort_dir: SortDir = "desc",
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[Deal], int]:
    filters, _owner_id, needs_account_join = _deal_filters(
        requester=requester,
        owner_id=owner_id,
        account_id=account_id,
        stage_id=stage_id,
        tier=tier,
        search=search,
    )

    count_query = select(func.count(Deal.id))
    items_query = select(Deal)
    if needs_account_join:
        count_query = count_query.join(Account, Deal.account_id == Account.id)
        items_query = items_query.join(Account, Deal.account_id == Account.id)

    count_query = count_query.where(*filters)
    items_query = (
        items_query.where(*filters).order_by(_order_by(sort_by, sort_dir)).limit(limit).offset(offset)
    )

    total = (await db.execute(count_query)).scalar_one()
    items = list((await db.execute(items_query)).scalars().all())
    return items, total


async def list_deals_board(
    db: AsyncSession,
    *,
    requester: User,
    owner_id: int | None = None,
    account_id: int | None = None,
    stage_id: int | None = None,
    tier: list[LeadTier] | None = None,
    search: str | None = None,
    sort_by: SortBy = "created_at",
    sort_dir: SortDir = "desc",
) -> list[tuple[DealStage, list[Deal]]]:
    """Same filtered result set as list_deals, grouped by stage (ordered by
    each stage's sort_order), no pagination -- it's a kanban board, not a
    paged list. Only stages with at least one matching deal are returned."""
    filters, _owner_id, needs_account_join = _deal_filters(
        requester=requester,
        owner_id=owner_id,
        account_id=account_id,
        stage_id=stage_id,
        tier=tier,
        search=search,
    )

    query = select(Deal)
    if needs_account_join:
        query = query.join(Account, Deal.account_id == Account.id)
    query = query.where(*filters).order_by(_order_by(sort_by, sort_dir))
    deals = list((await db.execute(query)).scalars().all())

    stage_ids = {deal.stage_id for deal in deals}
    if not stage_ids:
        return []

    stages_query = (
        select(DealStage).where(DealStage.id.in_(stage_ids)).order_by(DealStage.sort_order)
    )
    stages = list((await db.execute(stages_query)).scalars().all())

    deals_by_stage: dict[int, list[Deal]] = {}
    for deal in deals:
        deals_by_stage.setdefault(deal.stage_id, []).append(deal)

    return [(stage, deals_by_stage.get(stage.id, [])) for stage in stages]


async def _get_deal_or_raise(db: AsyncSession, deal_id: int, requester: User) -> Deal:
    result = await db.execute(select(Deal).where(Deal.id == deal_id))
    deal = result.scalar_one_or_none()
    if deal is None:
        raise DealNotFoundError(f"Deal not found: {deal_id}")
    if DEALS_VIEW_ALL not in requester.permission_codes and deal.owner_id != requester.id:
        raise DealAccessForbiddenError(f"Not permitted to access deal: {deal_id}")
    return deal


async def get_deal(db: AsyncSession, deal_id: int, requester: User) -> Deal:
    return await _get_deal_or_raise(db, deal_id, requester)


async def update_deal(db: AsyncSession, deal_id: int, data: DealUpdate, requester: User) -> Deal:
    deal = await _get_deal_or_raise(db, deal_id, requester)

    updates = data.model_dump(exclude_unset=True, exclude={"note", "contact_ids"})
    contact_ids_set = "contact_ids" in data.model_fields_set

    if "account_id" in updates:
        result = await db.execute(select(Account).where(Account.id == updates["account_id"]))
        if result.scalar_one_or_none() is None:
            raise AccountNotFoundError(f"Account not found: {updates['account_id']}")

    if "stage_id" in updates:
        await _get_stage_or_raise(db, updates["stage_id"])

    old_stage_id = deal.stage_id
    stage_changed = "stage_id" in updates and updates["stage_id"] != old_stage_id
    old_stage = await _get_stage_or_raise(db, old_stage_id) if stage_changed else None

    for field, value in updates.items():
        setattr(deal, field, value)

    if contact_ids_set:
        await _set_deal_contacts(db, deal.id, data.contact_ids or [])

    if stage_changed:
        db.add(
            DealStageHistory(
                deal_id=deal.id,
                from_stage_id=old_stage_id,
                to_stage_id=deal.stage_id,
                changed_by=requester.id,
                note=data.note,
            )
        )
        new_stage = await _get_stage_or_raise(db, deal.stage_id)
        await create_notification(
            db,
            recipient_id=deal.owner_id,
            type=NotificationType.DEAL_STAGE_CHANGED,
            title="Deal stage updated",
            body=f"{deal.deal_name} moved to {new_stage.name}.",
            actor_id=requester.id,
            entity_type="deal",
            entity_id=deal.id,
        )

    current_stage = await _get_stage_or_raise(db, deal.stage_id)
    if current_stage.is_cold and deal.cold_reason is None:
        raise ColdReasonRequiredError("cold_reason is required when the stage is cold")

    await db.flush()
    description = (
        f"Deal '{deal.deal_name}' moved from '{old_stage.name}' to '{current_stage.name}'"
        if old_stage is not None
        else f"Deal '{deal.deal_name}' updated"
    )
    await log_audit(
        db, table_name="deals", record_id=deal.id, action=AuditAction.UPDATED,
        actor_id=requester.id, description=description,
    )
    # Setting deal.account_id/stage_id/owner_id via setattr() above doesn't
    # sync the already-loaded account/stage/owner relationship attributes --
    # they'd still hold whichever row was linked when _get_deal_or_raise
    # first loaded this deal, so DealRead.account_name/stage_name/
    # stage_is_cold/owner_name would echo back the *old* value after a
    # reassignment.
    fk_to_relationship = {"account_id": "account", "stage_id": "stage", "owner_id": "owner"}
    changed_relationships = [rel for fk, rel in fk_to_relationship.items() if fk in updates]
    if changed_relationships:
        await db.refresh(deal, attribute_names=changed_relationships)
    return deal


async def delete_deal(db: AsyncSession, deal_id: int, requester: User) -> None:
    deal = await _get_deal_or_raise(db, deal_id, requester)
    deal_id_, deal_name = deal.id, deal.deal_name
    await db.delete(deal)
    await db.flush()
    await log_audit(
        db, table_name="deals", record_id=deal_id_, action=AuditAction.DELETED,
        actor_id=requester.id, description=f"Deal '{deal_name}' deleted",
    )


async def list_stage_history(
    db: AsyncSession, deal_id: int, requester: User
) -> list[DealStageHistory]:
    await _get_deal_or_raise(db, deal_id, requester)

    query = (
        select(DealStageHistory)
        .where(DealStageHistory.deal_id == deal_id)
        .order_by(DealStageHistory.created_at.asc(), DealStageHistory.id.asc())
    )
    result = await db.execute(query)
    return list(result.scalars().all())


async def list_deals_for_account(db: AsyncSession, account_id: int, requester: User) -> list[Deal]:
    await get_account(db, account_id, requester)

    result = await db.execute(select(Deal).where(Deal.account_id == account_id))
    return list(result.scalars().all())


async def list_deals_for_contact(db: AsyncSession, contact_id: int) -> list[Deal]:
    """Deals the Contact is a stakeholder on, via DealContact -- not
    ownership-scoped (Contact itself is role-gated only, see
    contact_service.py's module docstring)."""
    await get_contact(db, contact_id)

    result = await db.execute(
        select(Deal).join(DealContact, DealContact.deal_id == Deal.id).where(DealContact.contact_id == contact_id)
    )
    return list(result.scalars().all())


async def export_deals(
    db: AsyncSession,
    *,
    requester: User,
    owner_id: int | None = None,
    stage_id: int | None = None,
    tier: list[LeadTier] | None = None,
    search: str | None = None,
) -> list[dict[str, Any]]:
    """All deals matching the requester's role-scoping, ignoring any
    account_id filter (export is always cross-account). No pagination."""
    filters, _owner_id, _needs_join = _deal_filters(
        requester=requester, owner_id=owner_id, account_id=None, stage_id=stage_id, tier=tier, search=search
    )

    owner_name = func.trim(
        func.concat(func.coalesce(User.first_name, ""), " ", func.coalesce(User.last_name, ""))
    )

    query = (
        select(
            Deal.id,
            Deal.deal_name,
            Account.company,
            Deal.value,
            Deal.currency,
            DealStage.name,
            Deal.tier,
            owner_name,
            Deal.expected_close_date,
            Deal.cold_reason,
        )
        .join(Account, Deal.account_id == Account.id)
        .join(DealStage, Deal.stage_id == DealStage.id)
        .join(User, Deal.owner_id == User.id)
        .where(*filters)
        .order_by(Deal.created_at.desc())
    )

    rows = (await db.execute(query)).all()
    deal_ids = [row[0] for row in rows]
    contacts_by_deal = await get_deal_contact_ids_by_deal(db, deal_ids)

    return [
        {
            "deal_name": row[1],
            "account": row[2],
            "contact": ", ".join(name for _cid, name, _email, _phone in contacts_by_deal.get(row[0], [])) or None,
            "value": row[3],
            "currency": row[4],
            "stage": row[5],
            "tier": row[6].value if row[6] is not None else None,
            "owner": row[7],
            "expected_close_date": row[8],
            "cold_reason": row[9],
        }
        for row in rows
    ]
