"""Email templates: message content for transactional emails."""

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


async def send_new_lead_notification_email(
    sender: EmailSender, to: str, lead_name: str, company: str
) -> None:
    subject = f"New lead created: {company}"
    body = f"A new lead has been created on SalesHub.\n\nName: {lead_name}\nCompany: {company}"
    await sender.send(to=to, subject=subject, body=body)
