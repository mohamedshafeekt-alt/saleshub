"""Email templates: message content for transactional emails."""

from app.core.config import settings
from app.services.email.sender import EmailSender


async def send_new_user_credentials_email(sender: EmailSender, to: str, password: str) -> None:
    subject = "Your SalesHub account"
    body = (
        f"An account has been created for you on SalesHub.\n\n"
        f"Email: {to}\n"
        f"Temporary password: {password}\n\n"
        f"Please log in and change your password."
    )
    await sender.send(to=to, subject=subject, body=body)


async def send_password_reset_email(sender: EmailSender, to: str, reset_token: str) -> None:
    reset_link = f"{settings.frontend_base_url}/reset-password?token={reset_token}"
    subject = "Reset your SalesHub password"
    body = (
        f"A password reset was requested for your SalesHub account.\n\n"
        f"Reset link: {reset_link}\n\n"
        f"If you didn't request this, you can ignore this email."
    )
    await sender.send(to=to, subject=subject, body=body)


async def send_new_lead_notification_email(
    sender: EmailSender, to: str, lead_name: str, company: str
) -> None:
    subject = f"New lead created: {company}"
    body = f"A new lead has been created on SalesHub.\n\nName: {lead_name}\nCompany: {company}"
    await sender.send(to=to, subject=subject, body=body)
