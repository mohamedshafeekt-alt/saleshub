"""Deal business logic: account/stage-existence-gated creation with initial
stage history, role-scoped listing/search/sort (flat or grouped-by-stage
board), ownership-checked get/update/delete, stage-transition history
logging, cold-reason enforcement (driven by the referenced DealStage's
`is_cold` flag, plus a name check for Closed Lost specifically — see
CLOSED_LOST_STAGE_NAME), and xlsx export rows."""

from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal, get_args

from sqlalchemy import ColumnElement, and_, case, delete, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.account_options import ENGAGEMENT_TYPES, SOURCE_LABELS
from app.core.deal_scoring import (
    MODE_A_MIN,
    SCORING_DIMENSIONS,
    proposal_sla_due,
    scoring_export_fields,
    total_score,
)
from app.core.permission_codes import DEALS_NOTIFY_ON_CREATE, DEALS_VIEW_ALL
from app.models.account import Account
from app.models.contact import Contact
from app.models.contact_account import ContactAccount
from app.models.deal import Deal
from app.models.deal_activity import DealActivity
from app.models.deal_contact import DealContact
from app.models.deal_stage import CLOSED_LOST_STAGE_NAME, DealStage, is_terminal_stage
from app.models.deal_stage_history import DealStageHistory, entered_current_stage_in
from app.models.enums import AuditAction, LeadTier, NotificationType
from app.models.permission import Permission
from app.models.role import Role
from app.models.role_permission import role_permissions
from app.models.user import User
from app.schemas.account_source import SourcePersonRef, SourcePersonRead
from app.schemas.deal import DealCreate, DealUpdate
from app.services.account_service import AccountNotFoundError, get_account
from app.services.account_source_service import list_people, source_chain_by_account
from app.services.audit_service import log_audit
from app.services.contact_service import ContactNotFoundError, contact_exists
from app.services.notification_service import create_notification

SortBy = Literal["value", "expected_close_date", "created_at"]
SortDir = Literal["asc", "desc"]
# Which timestamp date_from/date_to filter on. "closed_at" is the lens the
# dashboard's Deals Closed tile and Closed Won/Lost/Cold funnel bars use, so a
# tile can drill down to exactly the deals it counted.
DateField = Literal["created_at", "closed_at"]
# Whether the deal is still in the pipeline. Kept server-side deliberately:
# DealStage exposes only `is_cold`, so Closed Won/Closed Lost are
# indistinguishable from open stages in the API -- a client filtering by
# stage_id would have to hardcode those two names itself.
StageState = Literal["all", "open", "closed"]
# The dashboard deal tiles; each is "open deals" narrowed by one rule, shared
# by the tile count and its drill-down list (see _quick_filter_predicate).
QuickFilter = Literal["in_view", "very_high", "overdue", "due_today", "past_sla"]

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
    """Raised when a deal's stage is cold (DealStage.is_cold) or Closed Lost, without a cold_reason."""


class InvalidOriginatorError(Exception):
    """Raised when a deal's originator isn't an active User or an is_originator Contact."""


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


async def _originator_columns(db: AsyncSession, ref: SourcePersonRef | None) -> dict[str, int | None]:
    """Deal column values for an originator ref (None clears both). Users must
    be active; Contacts must be flagged is_originator."""
    if ref is None:
        return {"originator_user_id": None, "originator_contact_id": None}
    if ref.type == "user":
        ok = await db.scalar(
            select(User.id).where(User.id == ref.id, User.is_active.is_(True), User.is_delete.is_(False))
        )
        if ok is None:
            raise InvalidOriginatorError(f"Unknown user: {ref.id}")
        return {"originator_user_id": ref.id, "originator_contact_id": None}
    ok = await db.scalar(
        select(Contact.id).where(
            Contact.id == ref.id, Contact.is_originator.is_(True), Contact.is_delete.is_(False)
        )
    )
    if ok is None:
        raise InvalidOriginatorError(f"Contact {ref.id} does not exist or is not marked as an originator")
    return {"originator_user_id": None, "originator_contact_id": ref.id}


async def list_originator_options(db: AsyncSession) -> list[SourcePersonRead]:
    """Everyone selectable as a deal's Originator: users + is_originator contacts."""
    return await list_people(db, originator_contacts_only=True)


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

    if (stage.is_cold or stage.name == CLOSED_LOST_STAGE_NAME) and data.cold_reason is None:
        raise ColdReasonRequiredError("cold_reason is required when the stage is cold or Closed Lost")

    await _assert_contacts_exist(db, data.contact_ids)

    originator_cols = await _originator_columns(db, data.originator)
    deal_fields = data.model_dump(exclude={"contact_ids", "originator"}) | originator_cols
    deal = Deal(**deal_fields)
    db.add(deal)
    await db.flush()
    # created_at is a server default -- load it to date the proposal SLA.
    await db.refresh(deal, attribute_names=["created_at"])
    deal.proposal_sla_due_at = proposal_sla_due(deal.created_at, total_score(deal.scores))

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

    result = await db.execute(
        select(User)
        .join(Role, User.role_id == Role.id)
        .join(role_permissions, Role.id == role_permissions.c.role_id)
        .join(Permission, role_permissions.c.permission_id == Permission.id)
        .where(
            Permission.code == DEALS_NOTIFY_ON_CREATE,
            User.is_active.is_(True),
            User.is_delete.is_(False),
        )
    )
    for notifiable in result.scalars():
        await create_notification(
            db,
            recipient_id=notifiable.id,
            type=NotificationType.DEAL_CREATED,
            title="New deal created",
            body=f"{deal.deal_name} was just created.",
            actor_id=requester.id,
            entity_type="deal",
            entity_id=deal.id,
        )

    # deal is a freshly-constructed instance, never loaded via a `select(Deal)`
    # -- account/stage/owner (lazy="joined" only applies to query-time loads)
    # are unpopulated relationship attributes. Accessing them later to build
    # DealRead would trigger an implicit lazy load, which crashes
    # (MissingGreenlet) because that happens outside any awaited call. Whether
    # it accidentally works instead depends on those rows still being
    # strongly referenced elsewhere in the session (e.g. the account/stage
    # lookups above going out of scope) -- not something to rely on.
    await db.refresh(
        deal, attribute_names=["account", "stage", "owner", "originator_user", "originator_contact"]
    )
    return deal


def _deal_filters(
    *,
    requester: User,
    owner_id: int | None,
    account_id: int | None,
    stage_id: list[int] | None,
    tier: list[LeadTier] | None,
    search: str | None,
    date_from: date | None = None,
    date_to: date | None = None,
    date_field: DateField = "created_at",
    stage_state: StageState = "all",
    quick_filter: QuickFilter | None = None,
) -> tuple[list[Any], int | None, bool]:
    if DEALS_VIEW_ALL not in requester.permission_codes:
        owner_id = requester.id

    filters: list[Any] = []
    if owner_id is not None:
        filters.append(Deal.owner_id == owner_id)
    if account_id is not None:
        filters.append(Deal.account_id == account_id)
    if stage_id:
        filters.append(Deal.stage_id.in_(stage_id))
    if tier:
        filters.append(Deal.tier.in_(tier))
    # `stage_state="closed"` means "any terminal stage" (Closed Won, Closed
    # Lost, or cold) -- a general closed-deals filter. `.has()` keeps this a
    # correlated EXISTS so it works whether or not the caller already joined
    # DealStage (list and board don't, export does).
    if stage_state == "open":
        filters.append(~Deal.stage.has(is_terminal_stage()))
    elif stage_state == "closed":
        filters.append(Deal.stage.has(is_terminal_stage()))
    # ponytail: used to also infer "Closed Won only" whenever `date_field ==
    # "closed_at" and not stage_id`, guessing that meant the dashboard's Deals
    # Closed tile drill-down (which is Closed Won only, not "any terminal
    # stage"). That drill-down's onTap is currently disabled frontend-side, so
    # nothing calls it that way -- but the plain on-page date-range filter
    # shares the exact same signature (closed_at, no stage_id) on its very
    # first request, before the page's own defensive "select every stage"
    # dispatch lands, so it silently collapsed a normal "show deals closed or
    # open in this range" query down to Closed-Won-only. Removed rather than
    # patched: a future drill-down should pass `stage_id=[<closed won id>]`
    # explicitly, which already composes correctly above, instead of being
    # inferred from what's absent.

    if date_field == "closed_at":
        if date_from is not None or date_to is not None:
            # entered_current_stage_in -- the same predicate every dashboard
            # widget uses -- for every stage, open or terminal, so this list
            # agrees with the tiles/funnel/distribution by construction, for
            # any date range.
            filters.append(entered_current_stage_in(date_from, date_to))
    else:
        if date_from is not None:
            filters.append(Deal.created_at >= date_from)
        if date_to is not None:
            # date_to is inclusive, matching the dashboard's end_date. It used to
            # be exclusive, which silently dropped deals created on the very day
            # the caller asked for and split the two endpoints' counts.
            filters.append(Deal.created_at < date_to + timedelta(days=1))

    if quick_filter is not None:
        filters.append(_quick_filter_predicate(quick_filter))

    needs_account_join = search is not None
    if search is not None:
        pattern = f"%{search}%"
        filters.append(or_(Deal.deal_name.ilike(pattern), Account.company.ilike(pattern)))

    return filters, owner_id, needs_account_join


def _total_score_sql() -> ColumnElement[Any]:
    """SQL twin of deal_scoring.total_score, built from SCORING_DIMENSIONS so
    adding/removing a level there changes this too."""
    return sum(
        (
            case(
                *[(Deal.scores[dim].astext == level, pts) for level, (_label, pts) in spec["levels"].items()],
                else_=0,
            )
            for dim, spec in SCORING_DIMENSIONS.items()
        ),
        literal(0),
    )


def _quick_filter_predicate(quick_filter: QuickFilter) -> ColumnElement[bool]:
    """Open deals narrowed by the tile's rule. "Open" is the same
    not-a-terminal-stage test as stage_state="open"."""
    open_ = ~Deal.stage.has(is_terminal_stage())
    today = date.today()
    if quick_filter == "very_high":
        return and_(open_, Deal.scores.is_not(None), _total_score_sql() >= MODE_A_MIN)
    if quick_filter == "overdue":
        return and_(open_, Deal.follow_up_date < today)
    if quick_filter == "due_today":
        return and_(open_, Deal.follow_up_date == today)
    if quick_filter == "past_sla":
        now = datetime.now(UTC).replace(tzinfo=None)  # created_at & co. are naive UTC
        return and_(open_, Deal.proposal_sla_due_at < now, Deal.proposal_status != "proposal_sent")
    return open_


async def count_quick_filters(db: AsyncSession, *, requester: User) -> dict[str, int]:
    """Deal counts for every QuickFilter, scoped to what `requester` may see."""
    counts = {}
    for quick_filter in get_args(QuickFilter):
        filters, _owner, _join = _deal_filters(
            requester=requester, owner_id=None, account_id=None, stage_id=None, tier=None,
            search=None, quick_filter=quick_filter,
        )
        counts[quick_filter] = await db.scalar(select(func.count(Deal.id)).where(*filters)) or 0
    return counts


def _order_by(sort_by: SortBy, sort_dir: SortDir) -> ColumnElement[Any]:
    column = _SORT_COLUMNS[sort_by]
    return column.desc() if sort_dir == "desc" else column.asc()


async def list_deals(
    db: AsyncSession,
    *,
    requester: User,
    owner_id: int | None = None,
    account_id: int | None = None,
    stage_id: list[int] | None = None,
    tier: list[LeadTier] | None = None,
    search: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    date_field: DateField = "created_at",
    stage_state: StageState = "all",
    quick_filter: QuickFilter | None = None,
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
        date_from=date_from,
        date_to=date_to,
        date_field=date_field,
        stage_state=stage_state,
        quick_filter=quick_filter,
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
    stage_id: list[int] | None = None,
    tier: list[LeadTier] | None = None,
    search: str | None = None,
    stage_state: StageState = "all",
    quick_filter: QuickFilter | None = None,
    sort_by: SortBy = "created_at",
    sort_dir: SortDir = "desc",
) -> list[tuple[DealStage, list[Deal]]]:
    """Same filtered result set as list_deals, grouped by stage (ordered by
    each stage's sort_order), no pagination -- it's a kanban board, not a
    paged list. Only stages with at least one matching deal are returned.

    Note the board applies no date filter at all, so it is always a live
    "where does every deal sit right now" view."""
    filters, _owner_id, needs_account_join = _deal_filters(
        requester=requester,
        owner_id=owner_id,
        account_id=account_id,
        stage_id=stage_id,
        tier=tier,
        search=search,
        stage_state=stage_state,
        quick_filter=quick_filter,
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

    updates = data.model_dump(exclude_unset=True, exclude={"note", "contact_ids", "originator"})
    originator_set = "originator" in data.model_fields_set
    if originator_set:
        updates |= await _originator_columns(db, data.originator)
    if updates.get("proposal_status") is None:
        updates.pop("proposal_status", None)  # not nullable: ignore an explicit null
    status_ = updates.get("proposal_status")
    if status_ == "proposal_sent":
        # Re-saving an already-sent deal keeps its original sent date.
        updates["proposal_sent_at"] = updates.get("proposal_sent_at") or deal.proposal_sent_at or date.today()
    elif status_ == "not_sent":
        updates["proposal_sent_at"] = None
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
    if "scores" in updates:
        deal.proposal_sla_due_at = proposal_sla_due(deal.created_at, total_score(deal.scores))

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
    if (current_stage.is_cold or current_stage.name == CLOSED_LOST_STAGE_NAME) and deal.cold_reason is None:
        raise ColdReasonRequiredError("cold_reason is required when the stage is cold or Closed Lost")

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
    if originator_set:
        changed_relationships += ["originator_user", "originator_contact"]
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
    """Deals the Contact is a stakeholder on, via DealContact -- not itself
    deal-ownership-scoped (the route checks the requester can see the
    Contact at all before calling this; existence-only here, see
    contact_service.contact_exists)."""
    await contact_exists(db, contact_id)

    result = await db.execute(
        select(Deal).join(DealContact, DealContact.deal_id == Deal.id).where(DealContact.contact_id == contact_id)
    )
    return list(result.scalars().all())


# Lead Tracker sheet columns first, then this app's own deal columns, then
# scoring (appended from deal_scoring). Shared by the list and single-deal exports.
EXPORT_COLUMNS = [
    "ID", "Date Received", "Source", "Source Detail", "Company Name", "Contact Name", "Designation",
    "Stage", "Comment", "Email", "Phone/WhatsApp", "Industry/Vertical", "Country/Region", "Engagement Type",
    "Deal Name", "All Contacts", "Value", "Currency", "Tier", "Owner", "Expected Close Date", "Cold Reason",
    "Follow-up Date", "Originator", "Proposal Status", "Proposal Sent Date", "Proposal SLA Due Date",
]
EXPORT_HEADERS = [*EXPORT_COLUMNS, *scoring_export_fields(None)]


async def deal_export_rows(db: AsyncSession, deals: list[Deal]) -> list[dict[str, Any]]:
    """One ordered {column: value} dict per deal, keyed by EXPORT_HEADERS."""
    deal_ids = [d.id for d in deals]
    contacts_by_deal = await get_deal_contact_ids_by_deal(db, deal_ids)
    chains = await source_chain_by_account(db, list({d.account_id for d in deals}))

    # Contact name/designation/email/phone: the account's primary contact if
    # linked to the deal, else the first linked one.
    primary_pairs = set()
    if deal_ids:
        primary_pairs = set((await db.execute(
            select(DealContact.deal_id, DealContact.contact_id)
            .join(Deal, Deal.id == DealContact.deal_id)
            .join(
                ContactAccount,
                (ContactAccount.contact_id == DealContact.contact_id) & (ContactAccount.account_id == Deal.account_id),
            )
            .where(DealContact.deal_id.in_(deal_ids), ContactAccount.is_primary.is_(True))
        )).all())
    contact_ids = {cid for links in contacts_by_deal.values() for cid, *_ in links}
    contact_rows = {
        c.id: c for c in (await db.execute(select(Contact).where(Contact.id.in_(contact_ids)))).scalars()
    } if contact_ids else {}

    latest_comment: dict[int, str] = {}
    if deal_ids:
        latest_comment = {
            deal_id: note
            for deal_id, note in (await db.execute(
                select(DealActivity.deal_id, DealActivity.note)
                .where(DealActivity.deal_id.in_(deal_ids))
                .distinct(DealActivity.deal_id)
                .order_by(DealActivity.deal_id, DealActivity.created_at.desc(), DealActivity.id.desc())
            )).all()
        }

    rows = []
    for deal in deals:
        links = contacts_by_deal.get(deal.id, [])
        chosen = next((cid for cid, *_ in links if (deal.id, cid) in primary_pairs), links[0][0] if links else None)
        contact = contact_rows.get(chosen) if chosen is not None else None
        account = deal.account
        originator = deal.originator
        values: dict[str, Any] = {
            "ID": deal.id,
            "Date Received": deal.created_at.date(),
            "Source": SOURCE_LABELS.get(account.source.value) if account.source else None,
            "Source Detail": chains.get(deal.account_id),
            "Company Name": account.company,
            "Contact Name": " ".join(filter(None, [contact.first_name, contact.last_name])) if contact else None,
            "Designation": contact.job_title if contact else None,
            "Stage": deal.stage.name,
            "Comment": latest_comment.get(deal.id),
            "Email": contact.email if contact else None,
            "Phone/WhatsApp": contact.phone if contact else None,
            "Industry/Vertical": account.industry,
            "Country/Region": account.country,
            "Engagement Type": ENGAGEMENT_TYPES.get(account.engagement_type) if account.engagement_type else None,
            "Deal Name": deal.deal_name,
            "All Contacts": ", ".join(name for _cid, name, _email, _phone in links) or None,
            "Value": deal.value,
            "Currency": deal.currency,
            "Tier": deal.tier.value if deal.tier is not None else None,
            "Owner": deal.owner_name,
            "Expected Close Date": deal.expected_close_date,
            "Cold Reason": deal.cold_reason,
            "Follow-up Date": deal.follow_up_date,
            "Originator": originator["name"] if originator else None,
            "Proposal Status": "Proposal Sent" if deal.proposal_status == "proposal_sent" else "Not Sent",
            "Proposal Sent Date": deal.proposal_sent_at,
            "Proposal SLA Due Date": deal.proposal_sla_due_at,
        }
        rows.append({column: values[column] for column in EXPORT_COLUMNS} | scoring_export_fields(deal.scores))
    return rows


async def export_deals(
    db: AsyncSession,
    *,
    requester: User,
    owner_id: int | None = None,
    stage_id: list[int] | None = None,
    tier: list[LeadTier] | None = None,
    search: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    date_field: DateField = "created_at",
    stage_state: StageState = "all",
    quick_filter: QuickFilter | None = None,
) -> list[dict[str, Any]]:
    """All deals matching the requester's role-scoping, ignoring any
    account_id filter (export is always cross-account). No pagination. Rows
    are keyed by EXPORT_HEADERS."""
    filters, _owner_id, _needs_join = _deal_filters(
        requester=requester,
        owner_id=owner_id,
        account_id=None,
        stage_id=stage_id,
        tier=tier,
        search=search,
        date_from=date_from,
        date_to=date_to,
        date_field=date_field,
        stage_state=stage_state,
        quick_filter=quick_filter,
    )
    query = (
        select(Deal)
        .join(Account, Deal.account_id == Account.id)
        .where(*filters)
        .order_by(Deal.created_at.desc())
    )
    deals = list((await db.execute(query)).unique().scalars().all())
    return await deal_export_rows(db, deals)
