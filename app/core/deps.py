"""FastAPI auth dependencies. Authorization (who's allowed to hit this route)
lives in app.core.rbac_middleware now — this just exposes the user the
middleware already resolved."""

from fastapi import Depends
from fastapi.security import HTTPBearer
from starlette.requests import Request

from app.core.config import settings
from app.models.user import User
from app.services.email.sender import EmailSender, SMTPEmailSender

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(request: Request, _=Depends(bearer_scheme)) -> User:
    return request.state.user


def get_email_sender() -> EmailSender:
    return SMTPEmailSender(
        host=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username,
        password=settings.smtp_password,
        from_address=settings.smtp_from_address,
    )
