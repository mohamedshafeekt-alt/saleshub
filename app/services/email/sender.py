"""Email sending: a Protocol tests fake against, plus a real SMTP implementation."""

import asyncio
import smtplib
from email.message import EmailMessage
from typing import Protocol


class EmailSender(Protocol):
    async def send(self, to: str, subject: str, body: str) -> None: ...


class SMTPEmailSender:
    """Sends mail via smtplib. smtplib is blocking, so the actual send is
    pushed to a thread with asyncio.to_thread so it doesn't stall the event loop.
    """

    def __init__(self, host: str, port: int, username: str, password: str, from_address: str) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.from_address = from_address

    async def send(self, to: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = self.from_address
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)

        await asyncio.to_thread(self._send_sync, message)

    def _send_sync(self, message: EmailMessage) -> None:
        with smtplib.SMTP(self.host, self.port) as smtp:
            smtp.starttls()
            smtp.login(self.username, self.password)
            smtp.send_message(message)
