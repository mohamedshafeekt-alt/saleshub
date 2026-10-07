"""Account Source Detail: read/replace the ordered User/Contact chain, and
the picker list of everyone selectable."""

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account_source_member import AccountSourceMember
from app.models.contact import Contact
from app.models.user import User
from app.schemas.account_source import SourcePersonRead, SourcePersonRef
from app.services.account_service import get_account  # also enforces 404/403

PEOPLE_LIMIT = 500


class UnknownSourcePersonError(Exception):
    """A User/Contact in the chain doesn't exist (or is inactive/deleted)."""


def _full_name(first: str | None, last: str | None) -> str:
    return " ".join(filter(None, [first, last]))


def _user_read(user: User) -> SourcePersonRead:
    return SourcePersonRead(
        type="user", id=user.id, name=_full_name(user.first_name, user.last_name),
        email=user.email, phone=user.phone_number,
    )


def _contact_read(contact: Contact) -> SourcePersonRead:
    return SourcePersonRead(
        type="contact", id=contact.id, name=_full_name(contact.first_name, contact.last_name),
        email=contact.email, phone=contact.phone,
    )


async def list_people(
    db: AsyncSession, search: str | None = None, *, originator_contacts_only: bool = False
) -> list[SourcePersonRead]:
    user_q = select(User).where(User.is_active.is_(True), User.is_delete.is_(False))
    contact_q = select(Contact).where(Contact.is_delete.is_(False))
    if originator_contacts_only:
        contact_q = contact_q.where(Contact.is_originator.is_(True))
    if search:
        like = f"%{search}%"
        user_q = user_q.where(
            or_(User.first_name.ilike(like), User.last_name.ilike(like), User.email.ilike(like))
        )
        contact_q = contact_q.where(
            or_(Contact.first_name.ilike(like), Contact.last_name.ilike(like), Contact.email.ilike(like))
        )
    users = (await db.execute(user_q.order_by(User.first_name).limit(PEOPLE_LIMIT))).scalars().all()
    contacts = (await db.execute(contact_q.order_by(Contact.first_name).limit(PEOPLE_LIMIT))).scalars().all()
    return [_user_read(u) for u in users] + [_contact_read(c) for c in contacts]


async def list_source_detail(db: AsyncSession, account_id: int, requester: User) -> list[SourcePersonRead]:
    await get_account(db, account_id, requester)
    members = (
        await db.execute(
            select(AccountSourceMember)
            .where(AccountSourceMember.account_id == account_id)
            .order_by(AccountSourceMember.position)
        )
    ).scalars().all()
    user_ids = [m.user_id for m in members if m.user_id is not None]
    contact_ids = [m.contact_id for m in members if m.contact_id is not None]
    users = {
        u.id: u for u in (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars()
    } if user_ids else {}
    contacts = {
        c.id: c for c in (await db.execute(select(Contact).where(Contact.id.in_(contact_ids)))).scalars()
    } if contact_ids else {}
    return [
        _user_read(users[m.user_id]) if m.user_id is not None else _contact_read(contacts[m.contact_id or 0])
        for m in members
    ]


async def replace_source_detail(
    db: AsyncSession, account_id: int, refs: list[SourcePersonRef], requester: User
) -> list[SourcePersonRead]:
    await get_account(db, account_id, requester)

    user_ids = {r.id for r in refs if r.type == "user"}
    contact_ids = {r.id for r in refs if r.type == "contact"}
    if user_ids:
        found = set((await db.execute(
            select(User.id).where(User.id.in_(user_ids), User.is_active.is_(True), User.is_delete.is_(False))
        )).scalars())
        if found != user_ids:
            raise UnknownSourcePersonError(f"Unknown user id(s): {sorted(user_ids - found)}")
    if contact_ids:
        found = set((await db.execute(
            select(Contact.id).where(Contact.id.in_(contact_ids), Contact.is_delete.is_(False))
        )).scalars())
        if found != contact_ids:
            raise UnknownSourcePersonError(f"Unknown contact id(s): {sorted(contact_ids - found)}")

    await db.execute(delete(AccountSourceMember).where(AccountSourceMember.account_id == account_id))
    for position, ref in enumerate(refs):
        db.add(AccountSourceMember(
            account_id=account_id,
            position=position,
            user_id=ref.id if ref.type == "user" else None,
            contact_id=ref.id if ref.type == "contact" else None,
        ))
    await db.flush()
    return await list_source_detail(db, account_id, requester)


async def source_chain_by_account(db: AsyncSession, account_ids: list[int]) -> dict[int, str]:
    """{account_id: "A --> B --> C"} for the accounts that have a chain (export)."""
    if not account_ids:
        return {}
    members = (
        await db.execute(
            select(AccountSourceMember)
            .where(AccountSourceMember.account_id.in_(account_ids))
            .order_by(AccountSourceMember.account_id, AccountSourceMember.position)
        )
    ).scalars().all()
    user_ids = {m.user_id for m in members if m.user_id is not None}
    contact_ids = {m.contact_id for m in members if m.contact_id is not None}
    users = {u.id: u for u in (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars()} if user_ids else {}
    contacts = (
        {c.id: c for c in (await db.execute(select(Contact).where(Contact.id.in_(contact_ids)))).scalars()}
        if contact_ids else {}
    )
    names: dict[int, list[str]] = {}
    for m in members:
        person = users[m.user_id] if m.user_id is not None else contacts[m.contact_id or 0]
        names.setdefault(m.account_id, []).append(_full_name(person.first_name, person.last_name))
    return {account_id: " --> ".join(chain) for account_id, chain in names.items()}
