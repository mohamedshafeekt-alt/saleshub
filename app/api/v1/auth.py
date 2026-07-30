"""POST /auth/login, /auth/refresh, /auth/logout."""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_email_sender
from app.core.rbac import public
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    ResetPasswordRequest,
    Token,
)
from app.services import auth_service
from app.services.email.sender import EmailSender
from app.services.user_service import authenticate_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=Token)
@public
async def login(data: LoginRequest, db: AsyncSession = Depends(get_db)) -> Token:
    user = await authenticate_user(db, data.email, data.password)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    access_token, refresh_token = await auth_service.issue_tokens(db, user)
    return Token(
        access_token=access_token,
        refresh_token=refresh_token,
        permissions=sorted(user.permission_codes),
    )


@router.post("/refresh", response_model=Token)
@public
async def refresh(data: RefreshRequest, db: AsyncSession = Depends(get_db)) -> Token:
    try:
        access_token = await auth_service.refresh_access_token(db, data.refresh_token)
    except auth_service.InvalidRefreshTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    # No rotation: the same refresh token stays valid until logout/expiry.
    return Token(access_token=access_token, refresh_token=data.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    data: LogoutRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    # Idempotent: an unknown/already-revoked/foreign token still returns 204,
    # not an error -- calling logout twice isn't a client mistake.
    await auth_service.revoke_refresh_token(db, current_user, data.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/forgot-password", status_code=status.HTTP_204_NO_CONTENT)
@public
async def forgot_password(
    data: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
    email_sender: EmailSender = Depends(get_email_sender),
) -> Response:
    # Always 204, whether or not the email is registered -- prevents user enumeration.
    await auth_service.request_password_reset(db, data.email, email_sender)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
@public
async def reset_password(data: ResetPasswordRequest, db: AsyncSession = Depends(get_db)) -> Response:
    try:
        await auth_service.reset_password(db, data.token, data.new_password)
    except auth_service.InvalidResetTokenError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
