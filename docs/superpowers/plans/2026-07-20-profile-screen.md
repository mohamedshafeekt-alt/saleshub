# Profile Screen Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the logged-in user's profile-edit screen (name/email/phone display, editable name+phone, avatar upload, password change, account-created/last-login display) a real backend, on top of the existing JWT auth system.

**Architecture:** Add three new nullable columns to `User` (`phone_number`, `avatar_url`, `last_login_at`) via one Alembic migration. Extend `app/schemas/user.py` with `UserUpdate`/`PasswordChange` and a fuller `UserRead`. Add three service functions to `app/services/user_service.py` (`update_profile`, `change_password`, `save_avatar`) and stamp `last_login_at` inside the existing `auth_service.issue_tokens`. Expose `GET/PATCH /users/me`, `POST /users/me/password`, `POST /users/me/avatar` on the existing `app/api/v1/users.py` router. Avatars are saved to local disk under `media/avatars/` and served via a `StaticFiles` mount — no new external dependency beyond `python-multipart` (required by FastAPI/Starlette to parse `UploadFile`/`File` uploads).

**Tech Stack:** FastAPI, SQLAlchemy (async) + Alembic, Pydantic v2, pytest-asyncio + httpx `AsyncClient`, `passlib[bcrypt]`.

## Global Constraints

- Never expose `hashed_password` (or any password) in a response — existing tests already assert this pattern (`tests/api/test_users.py`), keep it true for new endpoints.
- Email is NOT editable through `PATCH /users/me` — changing login email is a separate, bigger flow, out of scope for this plan.
- No real session/device tracking in this plan — logout stays exactly as it is today (`POST /auth/logout` revokes the caller's own refresh token).
- No notification-preferences backend in this plan — the screen's link is frontend-only.
- Every task must leave `uv run ruff check .`, `uv run mypy app`, and `uv run pytest` green (per `saleshub/CLAUDE.md` rule 6 — `.claude/hooks/post-edit.sh` runs these after every edit; a failure is a blocker, not something to defer).
- Migration chain: current head is `6853f7269cee` (`is_active_is_delete_on_base_soft_delete_...`) — verified via `grep -H "^revision\|^down_revision" app/db/migrations/versions/*.py`; no file has `down_revision` pointing past it.

---

### Task 1: Migration — add `phone_number`, `avatar_url`, `last_login_at` to `users`

**Files:**
- Create: `app/db/migrations/versions/b7f3a91c2e04_add_user_profile_fields.py`

**Interfaces:**
- Consumes: nothing (pure schema migration)
- Produces: three new nullable columns on the `users` table that Task 2's model must match exactly: `phone_number VARCHAR NULL`, `avatar_url VARCHAR NULL`, `last_login_at TIMESTAMP NULL`.

- [ ] **Step 1: Write the migration file**

```python
"""add phone_number, avatar_url, last_login_at to users

Revision ID: b7f3a91c2e04
Revises: 6853f7269cee
Create Date: 2026-07-20 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7f3a91c2e04'
down_revision: Union[str, Sequence[str], None] = '6853f7269cee'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('users', sa.Column('phone_number', sa.String(), nullable=True))
    op.add_column('users', sa.Column('avatar_url', sa.String(), nullable=True))
    op.add_column('users', sa.Column('last_login_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('users', 'last_login_at')
    op.drop_column('users', 'avatar_url')
    op.drop_column('users', 'phone_number')
```

- [ ] **Step 2: Apply it against the dev DB**

Run: `uv run alembic upgrade head`
Expected: no errors, ends on revision `b7f3a91c2e04`.

- [ ] **Step 3: Commit**

```bash
git add app/db/migrations/versions/b7f3a91c2e04_add_user_profile_fields.py
git commit -m "feat: add phone_number, avatar_url, last_login_at columns to users"
```

---

### Task 2: `User` model — add the three fields

**Files:**
- Modify: `app/models/user.py`

**Interfaces:**
- Consumes: columns created in Task 1 (must match name/nullability exactly).
- Produces: `User.phone_number: str | None`, `User.avatar_url: str | None`, `User.last_login_at: datetime | None` — every later task (schemas, services, routes) reads/writes these exact attribute names.

- [ ] **Step 1: Write the failing test**

Add to `tests/models/test_user.py`:

```python
async def test_profile_fields_default_to_none(db_session: AsyncSession):
    user = User(
        email="profile-fields-default@example.com",
        hashed_password="x",
        first_name="Test",
        role=UserRole.SALES_REP,
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)

    assert user.phone_number is None
    assert user.avatar_url is None
    assert user.last_login_at is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/models/test_user.py::test_profile_fields_default_to_none -v`
Expected: FAIL with `AttributeError: 'User' object has no attribute 'phone_number'`

- [ ] **Step 3: Add the fields to the model**

`app/models/user.py` full new contents:

```python
"""User ORM model: login identity + role for RBAC."""

from datetime import datetime

from sqlalchemy import Enum
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import UserRole

__all__ = ["User", "UserRole"]


class User(Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(nullable=False)
    first_name: Mapped[str] = mapped_column(nullable=False)
    last_name: Mapped[str | None] = mapped_column(nullable=True)
    phone_number: Mapped[str | None] = mapped_column(nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(nullable=True)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role", values_callable=lambda enum_cls: [member.value for member in enum_cls]),
        nullable=False,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/models/test_user.py -v`
Expected: PASS (all tests in the file, including the new one)

- [ ] **Step 5: Commit**

```bash
git add app/models/user.py tests/models/test_user.py
git commit -m "feat: add phone_number/avatar_url/last_login_at to User model"
```

---

### Task 3: Schemas — `UserRead` gains fields, add `UserUpdate` and `PasswordChange`

**Files:**
- Modify: `app/schemas/user.py`

**Interfaces:**
- Consumes: `User.phone_number`, `User.avatar_url`, `User.last_login_at`, `User.created_at` (from `Base`) from Task 2.
- Produces: `UserUpdate(first_name: str, last_name: str | None, phone_number: str | None)` and `PasswordChange(current_password: str, new_password: str)` — Task 4/6 import these exact names.

- [ ] **Step 1: Write the failing test**

Add a new file `tests/schemas/test_user_schemas.py`:

```python
"""app.schemas.user: UserRead/UserUpdate/PasswordChange shape."""

import pytest
from pydantic import ValidationError

from app.schemas.user import PasswordChange, UserUpdate


def test_user_update_allows_optional_last_name_and_phone():
    update = UserUpdate(first_name="Sarah")

    assert update.last_name is None
    assert update.phone_number is None


def test_password_change_rejects_short_new_password():
    with pytest.raises(ValidationError):
        PasswordChange(current_password="whatever", new_password="short")


def test_password_change_accepts_valid_new_password():
    change = PasswordChange(current_password="whatever", new_password="longenoughpassword")

    assert change.new_password == "longenoughpassword"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/schemas/test_user_schemas.py -v`
Expected: FAIL with `ImportError: cannot import name 'UserUpdate' from 'app.schemas.user'`

- [ ] **Step 3: Write the schemas**

`app/schemas/user.py` full new contents:

```python
"""User request/response schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.user import UserRole


class UserCreate(BaseModel):
    email: EmailStr
    first_name: str
    last_name: str | None = None
    # Deliberate default (confirmed product decision, not an oversight):
    # omitting role on creation grants Admin, not a lower-privilege role.
    role: UserRole = UserRole.ADMIN


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    first_name: str
    last_name: str | None
    phone_number: str | None
    avatar_url: str | None
    role: UserRole
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None


class UserUpdate(BaseModel):
    first_name: str
    last_name: str | None = None
    phone_number: str | None = None


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/schemas/test_user_schemas.py -v`
Expected: PASS

- [ ] **Step 5: Run full test suite to check for regressions**

Run: `uv run pytest`
Expected: PASS (existing `UserRead` consumers — `tests/api/test_users.py` — still pass since all new fields are nullable/have defaults)

- [ ] **Step 6: Commit**

```bash
git add app/schemas/user.py tests/schemas/test_user_schemas.py
git commit -m "feat: add UserUpdate/PasswordChange schemas, extend UserRead"
```

---

### Task 4: `user_service` — `update_profile` and `change_password`

**Files:**
- Modify: `app/services/user_service.py`
- Modify: `tests/services/test_user_service.py`

**Interfaces:**
- Consumes: `UserUpdate`, `PasswordChange` (Task 3); `User.phone_number` (Task 2); `hash_password`/`verify_password` from `app.core.security` (already imported in this file).
- Produces: `async def update_profile(db: AsyncSession, user: User, data: UserUpdate) -> User`, `async def change_password(db: AsyncSession, user: User, current_password: str, new_password: str) -> None`, `class IncorrectPasswordError(Exception)` — Task 6 (routes) imports all three by these exact names.

- [ ] **Step 1: Write the failing tests**

Add to `tests/services/test_user_service.py`:

```python
from app.core.security import hash_password, verify_password
from app.schemas.user import UserUpdate
from app.services.user_service import IncorrectPasswordError, change_password, update_profile


async def _make_user_with_password(db_session: AsyncSession, email: str, password: str) -> User:
    user = User(
        email=email,
        hashed_password=hash_password(password),
        first_name="Test",
        role=UserRole.SALES_REP,
    )
    db_session.add(user)
    await db_session.flush()
    return user


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/services/test_user_service.py -v`
Expected: FAIL with `ImportError: cannot import name 'update_profile' from 'app.services.user_service'`

- [ ] **Step 3: Implement in `app/services/user_service.py`**

Add these imports at the top (alongside the existing ones):

```python
from app.core.security import hash_password, verify_password
from app.schemas.user import UserUpdate
```

(`hash_password`, `verify_password` are already imported in this file for `authenticate_user` — do not duplicate the import line, just add `verify_password` to the existing `from app.core.security import hash_password, verify_password` line if it isn't already there.)

Add these functions (anywhere after `soft_delete_user`, before `authenticate_user`):

```python
class IncorrectPasswordError(Exception):
    """Raised when current_password doesn't match the user's stored hash."""


async def update_profile(db: AsyncSession, user: User, data: UserUpdate) -> User:
    user.first_name = data.first_name
    user.last_name = data.last_name
    user.phone_number = data.phone_number
    await db.flush()
    return user


async def change_password(db: AsyncSession, user: User, current_password: str, new_password: str) -> None:
    if not verify_password(current_password, user.hashed_password):
        raise IncorrectPasswordError("Current password is incorrect")
    user.hashed_password = hash_password(new_password)
    await db.flush()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/services/test_user_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/user_service.py tests/services/test_user_service.py
git commit -m "feat: add update_profile and change_password to user_service"
```

---

### Task 5: Stamp `last_login_at` on successful login

**Files:**
- Modify: `app/services/auth_service.py`
- Modify: `tests/services/test_auth_service.py`

**Interfaces:**
- Consumes: `User.last_login_at` (Task 2); `_utcnow()` helper already defined in this file.
- Produces: `issue_tokens` now has the side effect of setting `user.last_login_at` — no signature change, so Task 6/route code is unaffected.

- [ ] **Step 1: Write the failing test**

Add to `tests/services/test_auth_service.py` (open the file first to match its existing fixture/import style, then add):

```python
async def test_issue_tokens_sets_last_login_at(db_session: AsyncSession):
    user = User(
        email="stamps-last-login@example.com",
        hashed_password=hash_password("whatever-password"),
        first_name="Test",
        role=UserRole.SALES_REP,
    )
    db_session.add(user)
    await db_session.flush()
    assert user.last_login_at is None

    await issue_tokens(db_session, user)

    assert user.last_login_at is not None
```

(Use whatever `hash_password`/`User`/`UserRole`/`issue_tokens` imports this test file already has — don't add duplicate imports.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/services/test_auth_service.py::test_issue_tokens_sets_last_login_at -v`
Expected: FAIL with `assert None is not None`

- [ ] **Step 3: Update `issue_tokens` in `app/services/auth_service.py`**

```python
async def issue_tokens(db: AsyncSession, user: User) -> tuple[str, str]:
    access_token = create_access_token(subject=str(user.id))
    refresh_token = create_refresh_token()
    user.last_login_at = _utcnow()
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_token(refresh_token),
            expires_at=_utcnow() + timedelta(days=settings.refresh_token_expire_days),
        )
    )
    await db.commit()
    return access_token, refresh_token
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/services/test_auth_service.py tests/api/test_auth.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/auth_service.py tests/services/test_auth_service.py
git commit -m "feat: stamp last_login_at when tokens are issued at login"
```

---

### Task 6: Routes — `GET /users/me`, `PATCH /users/me`, `POST /users/me/password`

**Files:**
- Modify: `app/api/v1/users.py`
- Modify: `tests/api/test_users.py`

**Interfaces:**
- Consumes: `get_current_user` from `app.core.deps` (already used by `auth.py`); `UserUpdate`, `PasswordChange`, `UserRead` (Task 3); `update_profile`, `change_password`, `IncorrectPasswordError` (Task 4).
- Produces: three new endpoints other frontend/API tests can hit at `/api/v1/users/me` (GET/PATCH) and `/api/v1/users/me/password` (POST).

- [ ] **Step 1: Write the failing tests**

Add to `tests/api/test_users.py`:

```python
ME_URL = f"{USERS_URL}/me"
ME_PASSWORD_URL = f"{USERS_URL}/me/password"


async def test_get_me_returns_own_profile(client: AsyncClient, make_user, auth_headers):
    user = await make_user(email="get-me@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(user)

    response = await client.get(ME_URL, headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "get-me@example.com"
    assert body["phone_number"] is None
    assert body["avatar_url"] is None
    assert "created_at" in body


async def test_get_me_no_auth_header_returns_401(client: AsyncClient):
    response = await client.get(ME_URL)

    assert response.status_code == 401


async def test_patch_me_updates_name_and_phone(client: AsyncClient, make_user, auth_headers):
    user = await make_user(email="patch-me@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(user)

    response = await client.patch(
        ME_URL,
        json={"first_name": "Sarah", "last_name": "Jenkins", "phone_number": "+919845012233"},
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["first_name"] == "Sarah"
    assert body["last_name"] == "Jenkins"
    assert body["phone_number"] == "+919845012233"


async def test_patch_me_does_not_accept_email_change(client: AsyncClient, make_user, auth_headers):
    user = await make_user(email="patch-me-email@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(user)

    response = await client.patch(
        ME_URL,
        json={"first_name": "Sarah", "email": "changed@example.com"},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["email"] == "patch-me-email@example.com"


async def test_change_password_with_correct_current_password_returns_204(
    client: AsyncClient, make_user, auth_headers
):
    user = await make_user(email="change-pw@example.com", password="correct-password", role=UserRole.SALES_REP)
    headers = auth_headers(user)

    response = await client.post(
        ME_PASSWORD_URL,
        json={"current_password": "correct-password", "new_password": "brand-new-password"},
        headers=headers,
    )

    assert response.status_code == 204

    login_response = await client.post(
        "/api/v1/auth/login",
        json={"email": "change-pw@example.com", "password": "brand-new-password"},
    )
    assert login_response.status_code == 200


async def test_change_password_wrong_current_password_returns_400(
    client: AsyncClient, make_user, auth_headers
):
    user = await make_user(email="change-pw-wrong@example.com", password="correct-password", role=UserRole.SALES_REP)
    headers = auth_headers(user)

    response = await client.post(
        ME_PASSWORD_URL,
        json={"current_password": "wrong-password", "new_password": "brand-new-password"},
        headers=headers,
    )

    assert response.status_code == 400


async def test_change_password_too_short_returns_422(client: AsyncClient, make_user, auth_headers):
    user = await make_user(email="change-pw-short@example.com", password="correct-password", role=UserRole.SALES_REP)
    headers = auth_headers(user)

    response = await client.post(
        ME_PASSWORD_URL,
        json={"current_password": "correct-password", "new_password": "short"},
        headers=headers,
    )

    assert response.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/test_users.py -k "me or password" -v`
Expected: FAIL with 404s (routes don't exist yet)

- [ ] **Step 3: Add the routes to `app/api/v1/users.py`**

Full new contents:

```python
"""POST /users (admin-only user creation), GET /users (list, for owner assignment),
GET/PATCH /users/me (own profile), POST /users/me/password (own password change)."""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_email_sender, require_role
from app.db.session import get_db
from app.models.user import User, UserRole
from app.schemas.user import PasswordChange, UserCreate, UserRead, UserUpdate
from app.services.email.sender import EmailSender
from app.services.user_service import (
    EmailAlreadyExistsError,
    IncorrectPasswordError,
    UserNotFoundError,
    change_password,
    create_user,
    list_users,
    soft_delete_user,
    update_profile,
)

router = APIRouter(prefix="/users", tags=["users"])


@router.post(
    "",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)
async def create_user_route(
    data: UserCreate,
    db: AsyncSession = Depends(get_db),
    email_sender: EmailSender = Depends(get_email_sender),
) -> UserRead:
    try:
        user = await create_user(db, data, email_sender)
    except EmailAlreadyExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    await db.commit()
    return UserRead.model_validate(user)


@router.get("/me", response_model=UserRead)
async def get_me(current_user: User = Depends(get_current_user)) -> UserRead:
    return UserRead.model_validate(current_user)


@router.patch("/me", response_model=UserRead)
async def update_me(
    data: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserRead:
    user = await update_profile(db, current_user, data)
    await db.commit()
    return UserRead.model_validate(user)


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_my_password(
    data: PasswordChange,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    try:
        await change_password(db, current_user, data.current_password, data.new_password)
    except IncorrectPasswordError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "",
    response_model=list[UserRead],
    dependencies=[
        Depends(
            require_role(
                UserRole.SALES_REP, UserRole.SALES_MANAGER, UserRole.ADMIN, UserRole.DELIVERY_SME
            )
        )
    ],
)
async def list_users_route(db: AsyncSession = Depends(get_db)) -> list[UserRead]:
    users = await list_users(db)
    return [UserRead.model_validate(user) for user in users]


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)
async def delete_user_route(user_id: int, db: AsyncSession = Depends(get_db)) -> None:
    try:
        await soft_delete_user(db, user_id)
    except UserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    await db.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_users.py -v`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Run full suite for regressions**

Run: `uv run pytest`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/api/v1/users.py tests/api/test_users.py
git commit -m "feat: add GET/PATCH /users/me and POST /users/me/password endpoints"
```

---

### Task 7: Avatar upload — `POST /users/me/avatar` + static file serving

**Files:**
- Modify: `app/services/user_service.py`
- Modify: `app/api/v1/users.py`
- Modify: `app/main.py`
- Modify: `pyproject.toml`
- Modify: `tests/services/test_user_service.py`
- Modify: `tests/api/test_users.py`

**Interfaces:**
- Consumes: `User.avatar_url` (Task 2).
- Produces: `async def save_avatar(db: AsyncSession, user: User, content: bytes, content_type: str) -> str` (returns the new `avatar_url`), `class UnsupportedImageTypeError(Exception)`; `/media/avatars/<filename>` served as static files from `app.main:app`.

- [ ] **Step 1: Add the `python-multipart` dependency**

`UploadFile`/`File(...)` parsing in FastAPI/Starlette requires this package at runtime (it isn't in `pyproject.toml` yet).

Edit `pyproject.toml`, in the `dependencies` list, add:

```toml
    "python-multipart>=0.0.20",
```

Run: `uv sync`
Expected: installs `python-multipart` with no errors.

- [ ] **Step 2: Write the failing service test**

Add to `tests/services/test_user_service.py`:

```python
from pathlib import Path

from app.services.user_service import UnsupportedImageTypeError, save_avatar


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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/services/test_user_service.py -k avatar -v`
Expected: FAIL with `ImportError: cannot import name 'save_avatar' from 'app.services.user_service'`

- [ ] **Step 4: Implement `save_avatar` in `app/services/user_service.py`**

Add near the top of the file (with the other imports):

```python
from pathlib import Path
```

Add this constant and function (after `change_password`):

```python
class UnsupportedImageTypeError(Exception):
    """Raised when an avatar upload isn't image/png or image/jpeg."""


_AVATAR_DIR = Path("media/avatars")
_AVATAR_EXTENSION_BY_CONTENT_TYPE = {"image/png": ".png", "image/jpeg": ".jpg"}


async def save_avatar(db: AsyncSession, user: User, content: bytes, content_type: str) -> str:
    extension = _AVATAR_EXTENSION_BY_CONTENT_TYPE.get(content_type)
    if extension is None:
        raise UnsupportedImageTypeError(f"Unsupported image type: {content_type}")

    _AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    # ponytail: fixed filename per user means switching png<->jpeg leaves the
    # old file orphaned on disk; not worth a cleanup pass for an internal tool.
    filename = f"{user.id}{extension}"
    (_AVATAR_DIR / filename).write_bytes(content)

    user.avatar_url = f"/media/avatars/{filename}"
    await db.flush()
    return user.avatar_url
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/services/test_user_service.py -v`
Expected: PASS

- [ ] **Step 6: Write the failing API test**

Add to `tests/api/test_users.py`:

```python
ME_AVATAR_URL = f"{USERS_URL}/me/avatar"


async def test_upload_avatar_returns_updated_profile(client: AsyncClient, make_user, auth_headers):
    import pathlib

    user = await make_user(email="upload-avatar@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(user)

    response = await client.post(
        ME_AVATAR_URL,
        headers=headers,
        files={"file": ("avatar.png", b"fake-png-bytes", "image/png")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["avatar_url"] == f"/media/avatars/{user.id}.png"

    pathlib.Path(f"media/avatars/{user.id}.png").unlink()


async def test_upload_avatar_rejects_unsupported_type_returns_400(client: AsyncClient, make_user, auth_headers):
    user = await make_user(email="upload-avatar-bad-type@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(user)

    response = await client.post(
        ME_AVATAR_URL,
        headers=headers,
        files={"file": ("doc.pdf", b"whatever", "application/pdf")},
    )

    assert response.status_code == 400


async def test_upload_avatar_no_auth_header_returns_401(client: AsyncClient):
    response = await client.post(
        ME_AVATAR_URL,
        files={"file": ("avatar.png", b"fake-png-bytes", "image/png")},
    )

    assert response.status_code == 401
```

- [ ] **Step 7: Run test to verify it fails**

Run: `uv run pytest tests/api/test_users.py -k avatar -v`
Expected: FAIL with 404 (route doesn't exist yet)

- [ ] **Step 8: Add the route to `app/api/v1/users.py`**

Update the import block:

```python
from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
```

```python
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
```

Add this route (after `change_my_password`):

```python
@router.post("/me/avatar", response_model=UserRead)
async def upload_my_avatar(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserRead:
    content = await file.read()
    try:
        await save_avatar(db, current_user, content, file.content_type or "")
    except UnsupportedImageTypeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    await db.commit()
    return UserRead.model_validate(current_user)
```

- [ ] **Step 9: Mount static file serving in `app/main.py`**

Full new contents:

```python
"""FastAPI app entrypoint: router registration."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.v1 import accounts, auth, contacts, deals, leads, users
from app.core.error_handler import register_error_handlers
from app.core.logging import configure_logging

configure_logging()

Path("media/avatars").mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Sales CRM Platform")

# Wildcard is safe here (no allow_credentials): auth is a Bearer token in
# the Authorization header, not a cookie, so there's nothing ambient for a
# malicious origin to ride along.
# ponytail: wildcard origins, scope to a real allowlist before prod launch.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

register_error_handlers(app)

app.mount("/media", StaticFiles(directory="media"), name="media")

app.include_router(auth.router, prefix="/api/v1")
app.include_router(users.router, prefix="/api/v1")
app.include_router(leads.router, prefix="/api/v1")
app.include_router(accounts.router, prefix="/api/v1")
app.include_router(contacts.router, prefix="/api/v1")
app.include_router(deals.router, prefix="/api/v1")
```

- [ ] **Step 10: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_users.py -v`
Expected: PASS

- [ ] **Step 11: Run full suite, lint, and typecheck**

Run: `uv run ruff check . && uv run mypy app && uv run pytest`
Expected: all green

- [ ] **Step 12: Commit**

```bash
git add app/services/user_service.py app/api/v1/users.py app/main.py pyproject.toml uv.lock \
  tests/services/test_user_service.py tests/api/test_users.py
git commit -m "feat: add avatar upload endpoint with local disk storage + static serving"
```

---

### Task 8: Update README.md

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add a line under "Implemented"**

Add this bullet after the "Refresh tokens + logout" line:

```markdown
- [x] Profile self-service — `GET/PATCH /api/v1/users/me` (name/phone, email not editable here), `POST /api/v1/users/me/password` (current-password verified), `POST /api/v1/users/me/avatar` (image/png or image/jpeg, saved to local disk under `media/avatars/`, served via `/media` static mount); `User` gained `phone_number`/`avatar_url`/`last_login_at`, the last one stamped on every successful login
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: track profile self-service in README"
```

---

## Self-Review Notes

- **Spec coverage:** name/email/phone display → Task 3/6; name+phone edit → Task 4/6; email read-only → Task 6 test; avatar upload → Task 7; password change with strength floor → Task 3/4/6; Account Created/Last Login display → Task 2/3; sessions panel → explicitly out of scope per your call; notification-preferences link → explicitly out of scope, frontend-only.
- **Type consistency:** `UserUpdate`/`PasswordChange`/`update_profile`/`change_password`/`save_avatar`/`IncorrectPasswordError`/`UnsupportedImageTypeError` are spelled identically everywhere they're defined (Tasks 3/4/7) and imported (Task 6/7).
- **No placeholders:** every step has runnable code and exact test/command text.
