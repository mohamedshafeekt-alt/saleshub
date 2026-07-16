"""app.services.email: templated new-user-credentials email.

Business rule (CLAUDE.md / admin-create-user flow): admin-created users never
submit or receive a password via the API — the server generates one and
emails it. These tests pin down the templating function's contract against a
fake EmailSender so no test ever touches real SMTP.
"""

from app.services.email.templates import send_new_lead_notification_email, send_new_user_credentials_email


class FakeEmailSender:
    """Records calls instead of sending anything."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def send(self, to: str, subject: str, body: str) -> None:
        self.calls.append({"to": to, "subject": subject, "body": body})


async def test_send_new_user_credentials_email_calls_sender_once_with_recipient_and_password():
    fake = FakeEmailSender()

    await send_new_user_credentials_email(fake, "someone@example.com", "hunter2-generated")

    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["to"] == "someone@example.com"
    assert "hunter2-generated" in call["body"]


async def test_send_new_lead_notification_email_calls_sender_once_with_recipient_and_lead_details():
    fake = FakeEmailSender()

    await send_new_lead_notification_email(fake, "admin@example.com", "Jane Doe", "Acme Corp")

    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["to"] == "admin@example.com"
    assert "Jane Doe" in call["body"]
    assert "Acme Corp" in call["body"]
