"""POST /users (admin-only user creation), GET /users (list, for owner assignment),
GET/PATCH /users/me (own profile), POST /users/me/password (own password change)."""

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_email_sender
from app.core.permission_codes import USERS_MANAGE, USERS_VIEW
from app.core.rbac import requires_permission
from app.db.session import get_db
from app.models.user import User, UserStatus
from app.schemas.user import PasswordChange, UserCreate, UserRead, UserUpdate
from app.services import auth_service
from app.services.email.sender import EmailSender
from app.services.user_service import (
    EmailAlreadyExistsError,
    IncorrectPasswordError,
    RoleNotFoundError,
    UnsupportedImageTypeError,
    UserNotFoundError,
    activate_user,
    change_password,
    create_user,
    list_users,
    remove_avatar,
    save_avatar,
    soft_delete_user,
    update_profile,
)

router = APIRouter(prefix="/users", tags=["users"])


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
@requires_permission(USERS_MANAGE)
async def create_user_route(
    data: UserCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    email_sender: EmailSender = Depends(get_email_sender),
) -> UserRead:
    try:
        user = await create_user(
            db, data, email_sender, actor_id=current_user.id, background_tasks=background_tasks
        )
    except EmailAlreadyExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except RoleNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

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

    # Force every other session (and the current access token, per
    # rbac_middleware.enforce_rbac's iat check) to log in again.
    await auth_service.revoke_all_refresh_tokens(db, current_user)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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


@router.delete("/me/avatar", response_model=UserRead)
async def delete_my_avatar(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserRead:
    await remove_avatar(db, current_user)
    await db.commit()
    return UserRead.model_validate(current_user)


@router.get("", response_model=list[UserRead])
@requires_permission(USERS_VIEW)
async def list_users_route(
    role_id: int | None = Query(None),
    is_active: bool | None = Query(None),
    status: UserStatus | None = Query(None),
    search: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> list[UserRead]:
    users = await list_users(db, role_id=role_id, is_active=is_active, status=status, search=search)
    return [UserRead.model_validate(user) for user in users]


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
@requires_permission(USERS_MANAGE)
async def delete_user_route(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    try:
        await soft_delete_user(db, user_id, actor_id=current_user.id)
    except UserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    await db.commit()


@router.post("/{user_id}/activate", response_model=UserRead)
@requires_permission(USERS_MANAGE)
async def activate_user_route(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserRead:
    try:
        await activate_user(db, user_id, actor_id=current_user.id)
    except UserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    await db.commit()
    user = await db.get(User, user_id)
    return UserRead.model_validate(user)
