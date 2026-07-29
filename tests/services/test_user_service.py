"""User service: soft-delete, list filtering, profile updates, and password change."""

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, verify_password
from app.models.user import User, UserStatus
from app.schemas.user import UserCreate, UserUpdate
from app.services.user_service import (
    EmailAlreadyExistsError,
    IncorrectPasswordError,
    UnsupportedImageTypeError,
    UserNotFoundError,
    change_password,
    create_user,
    list_users,
    save_avatar,
    soft_delete_user,
    update_profile,
)
from tests.support.roles import UserRole, role_id_for


class _FakeEmailSender:
    async def send(self, to: str, subject: str, body: str) -> None:
        pass


async def _make_user(db_session: AsyncSession, email: str, role: UserRole = UserRole.SALES_REP) -> User:
    user = User(
        email=email, hashed_password="x", first_name="Test", role_id=await role_id_for(db_session, role)
    )
    db_session.add(user)
    await db_session.flush()
    return user


async def _make_user_with_password(db_session: AsyncSession, email: str, password: str) -> User:
    user = User(
        email=email,
        hashed_password=hash_password(password),
        first_name="Test",
        role_id=await role_id_for(db_session, UserRole.SALES_REP),
    )
    db_session.add(user)
    await db_session.flush()
    return user


async def test_list_users_filters_by_role(db_session: AsyncSession):
    rep = await _make_user(db_session, "rep-svc-filter@example.com")
    admin = await _make_user(db_session, "admin-svc-filter@example.com", role=UserRole.ADMIN)

    users = await list_users(db_session, role_id=rep.role_id)

    emails = {u.email for u in users}
    assert rep.email in emails
    assert admin.email not in emails


async def test_list_users_filters_by_is_active(db_session: AsyncSession):
    active = await _make_user(db_session, "active-svc-filter@example.com")
    inactive = User(
        email="inactive-svc-filter@example.com",
        hashed_password="x",
        first_name="Test",
        role_id=await role_id_for(db_session, UserRole.SALES_REP),
        is_active=False,
    )
    db_session.add(inactive)
    await db_session.flush()

    users = await list_users(db_session, is_active=False)

    emails = {u.email for u in users}
    assert inactive.email in emails
    assert active.email not in emails


async def test_list_users_search_matches_name_or_email(db_session: AsyncSession):
    match = User(
        email="findme-svc@example.com",
        hashed_password="x",
        first_name="Karthick",
        role_id=await role_id_for(db_session, UserRole.SALES_REP),
    )
    other = await _make_user(db_session, "other-svc-search@example.com")
    db_session.add(match)
    await db_session.flush()

    by_name = await list_users(db_session, search="karthick")
    assert {u.email for u in by_name} == {match.email}

    by_email = await list_users(db_session, search="findme-svc")
    assert {u.email for u in by_email} == {match.email}

    assert other.email not in {u.email for u in by_name}


async def test_list_users_filters_by_status_invited(db_session: AsyncSession):
    from datetime import UTC, datetime

    invited = await _make_user(db_session, "invited-svc-filter@example.com")
    active = User(
        email="active-svc-status-filter@example.com",
        hashed_password="x",
        first_name="Test",
        role_id=await role_id_for(db_session, UserRole.SALES_REP),
        last_login_at=datetime.now(UTC).replace(tzinfo=None),
    )
    db_session.add(active)
    await db_session.flush()

    users = await list_users(db_session, status=UserStatus.INVITED)

    emails = {u.email for u in users}
    assert invited.email in emails
    assert active.email not in emails


async def test_list_users_filters_by_status_deactivated(db_session: AsyncSession):
    active = await _make_user(db_session, "active-svc-deactivated-filter@example.com")
    deactivated = User(
        email="deactivated-svc-filter@example.com",
        hashed_password="x",
        first_name="Test",
        role_id=await role_id_for(db_session, UserRole.SALES_REP),
        is_active=False,
    )
    db_session.add(deactivated)
    await db_session.flush()

    users = await list_users(db_session, status=UserStatus.DEACTIVATED)

    emails = {u.email for u in users}
    assert deactivated.email in emails
    assert active.email not in emails


async def test_soft_delete_user_sets_is_delete_true(db_session: AsyncSession):
    user = await _make_user(db_session, "soft-delete-me@example.com")

    await soft_delete_user(db_session, user.id, actor_id=user.id)

    await db_session.refresh(user)
    assert user.is_delete is True


async def test_soft_delete_user_missing_id_raises_not_found(db_session: AsyncSession):
    user = await _make_user(db_session, "acting-user-missing-id@example.com")
    with pytest.raises(UserNotFoundError):
        await soft_delete_user(db_session, 999_999, actor_id=user.id)


async def test_soft_delete_user_already_deleted_raises_not_found(db_session: AsyncSession):
    user = await _make_user(db_session, "already-deleted@example.com")
    await soft_delete_user(db_session, user.id, actor_id=user.id)

    with pytest.raises(UserNotFoundError):
        await soft_delete_user(db_session, user.id, actor_id=user.id)


async def test_list_users_excludes_soft_deleted(db_session: AsyncSession):
    kept = await _make_user(db_session, "kept@example.com")
    deleted = await _make_user(db_session, "deleted-from-list@example.com")
    await soft_delete_user(db_session, deleted.id, actor_id=kept.id)

    users = await list_users(db_session)

    emails = {u.email for u in users}
    assert kept.email in emails
    assert deleted.email not in emails


async def test_create_user_reactivates_soft_deleted_email(db_session: AsyncSession):
    original = await _make_user(db_session, "reactivate-me@example.com", role=UserRole.SALES_REP)
    admin_actor = await _make_user(db_session, "reactivate-admin-actor@example.com", role=UserRole.ADMIN)
    await soft_delete_user(db_session, original.id, actor_id=admin_actor.id)
    admin_role_id = await role_id_for(db_session, UserRole.ADMIN)

    reactivated = await create_user(
        db_session,
        UserCreate(
            email="reactivate-me@example.com",
            first_name="New First",
            last_name="New Last",
            role_id=admin_role_id,
        ),
        _FakeEmailSender(),
        actor_id=admin_actor.id,
    )

    assert reactivated.id == original.id
    assert reactivated.is_delete is False
    assert reactivated.is_active is True
    assert reactivated.first_name == "New First"
    assert reactivated.last_name == "New Last"
    assert reactivated.role_id == admin_role_id


async def test_create_user_rejects_active_duplicate_email(db_session: AsyncSession):
    await _make_user(db_session, "already-active@example.com")
    role_id = await role_id_for(db_session, UserRole.SALES_REP)
    actor = await _make_user(db_session, "dup-email-actor@example.com", role=UserRole.ADMIN)

    with pytest.raises(EmailAlreadyExistsError):
        await create_user(
            db_session,
            UserCreate(
                email="already-active@example.com",
                first_name="Dup",
                last_name=None,
                role_id=role_id,
            ),
            _FakeEmailSender(),
            actor_id=actor.id,
        )


async def test_update_profile_sets_name_and_phone(db_session: AsyncSession):
    user = await _make_user(db_session, "update-me@example.com")

    updated = await update_profile(
        db_session, user, UserUpdate(first_name="New First", last_name="New Last", phone_number="+911234567890")
    )

    assert updated.first_name == "New First"
    assert updated.last_name == "New Last"
    assert updated.phone_number == "+911234567890"


async def test_update_profile_clears_phone_when_set_to_none(db_session: AsyncSession):
    user = await _make_user(db_session, "clear-phone@example.com")
    await update_profile(db_session, user, UserUpdate(first_name="Test", phone_number="+911111111111"))

    updated = await update_profile(db_session, user, UserUpdate(first_name="Test", phone_number=None))

    assert updated.phone_number is None


async def test_change_password_updates_hash(db_session: AsyncSession):
    user = await _make_user_with_password(db_session, "change-pw@example.com", "old-password-123")

    await change_password(db_session, user, "old-password-123", "brand-new-password")

    assert verify_password("brand-new-password", user.hashed_password)
    assert not verify_password("old-password-123", user.hashed_password)


async def test_change_password_wrong_current_password_raises(db_session: AsyncSession):
    user = await _make_user_with_password(db_session, "wrong-current-pw@example.com", "old-password-123")

    with pytest.raises(IncorrectPasswordError):
        await change_password(db_session, user, "totally-wrong", "brand-new-password")


async def test_change_password_sets_password_changed_at(db_session: AsyncSession):
    user = await _make_user_with_password(db_session, "stamps-pw-change@example.com", "old-password-123")
    assert user.password_changed_at is None

    await change_password(db_session, user, "old-password-123", "brand-new-password")

    assert user.password_changed_at is not None


async def test_change_password_writes_audit_log(db_session: AsyncSession):
    from sqlalchemy import select
    from app.models.audit_log import AuditLog

    user = await _make_user_with_password(db_session, "audit-pw-change@example.com", "old-password-123")

    await change_password(db_session, user, "old-password-123", "brand-new-password")
    await db_session.flush()

    result = await db_session.execute(
        select(AuditLog).where(AuditLog.table_name == "users", AuditLog.record_id == user.id, AuditLog.action == "updated")
    )
    assert result.scalar_one() is not None


async def test_save_avatar_writes_file_and_sets_avatar_url(db_session: AsyncSession):
    user = await _make_user(db_session, "avatar-me@example.com")

    avatar_url = await save_avatar(db_session, user, b"fake-png-bytes", "image/png")

    assert avatar_url == f"/media/avatars/{user.id}.png"
    assert user.avatar_url == avatar_url
    assert Path(f"media/avatars/{user.id}.png").read_bytes() == b"fake-png-bytes"

    Path(f"media/avatars/{user.id}.png").unlink()


async def test_save_avatar_rejects_unsupported_content_type(db_session: AsyncSession):
    user = await _make_user(db_session, "bad-avatar-type@example.com")

    with pytest.raises(UnsupportedImageTypeError):
        await save_avatar(db_session, user, b"whatever", "application/pdf")


async def test_create_user_writes_audit_log(db_session, make_user):
    from sqlalchemy import select
    from app.models.audit_log import AuditLog
    from app.services.email.sender import EmailSender
    from app.services.user_service import create_user
    from app.schemas.user import UserCreate
    from tests.support.roles import UserRole, role_id_for

    admin = await make_user(email="user-audit-admin@example.com", role=UserRole.ADMIN)
    role_id = await role_id_for(db_session, UserRole.SALES_REP)

    class _NoopSender(EmailSender):
        async def send(self, *args, **kwargs):
            pass

    data = UserCreate(email="user-audit-new@example.com", first_name="New", last_name="User", role_id=role_id)
    user = await create_user(db_session, data, _NoopSender(), actor_id=admin.id)
    await db_session.flush()

    result = await db_session.execute(
        select(AuditLog).where(AuditLog.table_name == "users", AuditLog.record_id == user.id, AuditLog.action == "created")
    )
    entry = result.scalar_one()
    assert entry.actor_id == admin.id


async def test_soft_delete_user_writes_audit_log(db_session, make_user):
    from sqlalchemy import select
    from app.models.audit_log import AuditLog
    from app.services.user_service import soft_delete_user
    from tests.support.roles import UserRole

    admin = await make_user(email="user-audit-admin2@example.com", role=UserRole.ADMIN)
    target = await make_user(email="user-audit-target@example.com")
    target_id = target.id
    await soft_delete_user(db_session, target_id, actor_id=admin.id)
    await db_session.flush()

    result = await db_session.execute(
        select(AuditLog).where(AuditLog.table_name == "users", AuditLog.record_id == target_id, AuditLog.action == "deactivated")
    )
    assert result.scalar_one() is not None
