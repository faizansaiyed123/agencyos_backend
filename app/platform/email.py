"""Transactional email abstraction.

Dev/test can use console or memory backends. Production requires SMTP so invite,
password-recovery, and other account messages can actually reach users.
"""

import smtplib
from email.message import EmailMessage

from app.core.config import get_settings

_sent: list[dict[str, str]] = []


def send_email(*, to: str, subject: str, body: str) -> None:
    settings = get_settings()
    if settings.email_backend == "memory":
        _sent.append({"to": to, "subject": subject, "body": body})
        return
    if settings.email_backend == "console":
        print(f"[email:console] to={to} subject={subject!r}\n{body}")  # noqa: T201
        return

    if not settings.smtp_host:
        raise RuntimeError("SMTP is not configured")

    message = EmailMessage()
    message["From"] = settings.smtp_from_email
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
        smtp.ehlo()
        if settings.smtp_starttls:
            smtp.starttls()
            smtp.ehlo()
        if settings.smtp_username:
            password = settings.smtp_password.get_secret_value() if settings.smtp_password else None
            if password is None:
                raise RuntimeError("SMTP password is not configured")
            smtp.login(settings.smtp_username, password)
        smtp.send_message(message)


def sent_emails() -> list[dict[str, str]]:
    return list(_sent)


def clear_sent_emails() -> None:
    _sent.clear()
