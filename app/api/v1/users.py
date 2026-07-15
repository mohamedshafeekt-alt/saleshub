"""POST /users (admin-only user creation)."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_email_sender, require_role
from app.db.session import get_db
from app.models.user import UserRole
from app.schemas.user import UserCreate, UserRead
from app.services.email.sender import EmailSender
from app.services.user_service import EmailAlreadyExistsError, create_user

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
